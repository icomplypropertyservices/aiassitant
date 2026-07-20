import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Tag, Typography, Space, Button, Tooltip } from 'antd'
import {
  ThunderboltOutlined, RobotOutlined, UserOutlined, ApiOutlined,
  ClusterOutlined, CheckCircleOutlined, LoadingOutlined, CloseCircleOutlined,
  RightOutlined, WarningOutlined, DollarOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, connectAuthedWs } from '../api'
import { hapticLight, hapticSuccess, hapticError, notifyLocal, isNative } from '../native'

const KIND_ICON = {
  plan: <ClusterOutlined />,
  step: <ThunderboltOutlined />,
  skill: <ThunderboltOutlined />,
  action: <ThunderboltOutlined />,
  agent: <RobotOutlined />,
  human: <UserOutlined />,
  app: <ApiOutlined />,
  system: <ThunderboltOutlined />,
}

const STATUS_COLOR = {
  running: 'processing',
  queued: 'default',
  done: 'success',
  failed: 'error',
  info: 'blue',
}

const CREDIT_RE = /credit|top.?up|billing|hard.?block|insufficient|out of (fuel|balance)|spending.?limit|payment.?required|402/i

function eventAgentId(e) {
  if (!e) return null
  const id = e.agent_id ?? e.payload?.agent_id ?? e.payload?.from_agent_id
  if (id == null || id === '') return null
  const n = Number(id)
  return Number.isFinite(n) ? n : null
}

function eventAgentLabel(e, nameMap) {
  if (!e) return ''
  const id = eventAgentId(e)
  return (
    e.agent_name
    || e.payload?.agent_name
    || (id != null ? nameMap[id] : null)
    || (id != null ? `Agent #${id}` : '')
  )
}

function eventLooksLikeCredits(e) {
  if (!e) return false
  const blob = [
    e.title, e.detail, e.message, e.status, e.kind,
    e.reason, e.error, e.code,
    e.payload?.error, e.payload?.message, e.payload?.reason,
  ].filter(Boolean).join(' ')
  return CREDIT_RE.test(blob)
}

/**
 * Derive lightweight health from ops payload only (no extra meter polls).
 * Prefer explicit snapshot.health / snapshot.credits when present.
 */
function deriveHealth(events, snapshot) {
  const health = snapshot?.health || snapshot?.status || null
  const credits = snapshot?.credits ?? snapshot?.billing ?? snapshot?.meter ?? null

  const failed = (events || []).filter((e) => {
    const st = String(e?.status || '').toLowerCase()
    return st === 'failed' || st === 'error' || st === 'terminal'
  })

  const creditFromEvents = (events || []).some(eventLooksLikeCredits)
  const creditFromSnap = !!(
    health
    && (
      health.credits_issue
      || health.needs_topup
      || health.hard_block
      || health.credits_exhausted
      || CREDIT_RE.test(String(health.message || health.detail || health.reason || ''))
    )
  ) || !!(
    credits
    && (
      credits.needs_topup
      || credits.hard_block
      || credits.hard_block_soon
      || credits.credits_exhausted
      || (typeof credits.credits === 'number' && credits.credits <= 0)
      || (typeof credits.balance === 'number' && credits.balance <= 0)
    )
  )

  const terminalFail = !!(
    health?.terminal_fail
    || health?.terminal
    || (health?.status && /terminal|fatal|hard/i.test(String(health.status)))
  ) || failed.some((e) => /terminal|fatal|hard.?fail/i.test(
    [e.title, e.detail, e.message, e.kind].filter(Boolean).join(' '),
  ))

  return {
    failedCount: failed.length,
    latestFail: failed[0] || null,
    creditsIssue: creditFromEvents || creditFromSnap,
    terminalFail,
    headline: health?.headline || health?.message || snapshot?.headline || null,
  }
}

/**
 * Sticky real-time action/plan ticker under the app header.
 * - Horizontal scroll marquee that restarts on every new event
 * - Each chip opens that agent’s chat when agent_id is present
 * - Polls REST sparingly in production (WS preferred; skip REST while WS healthy)
 * - Surfaces terminal fail / credits from existing ops payload only
 */
export default function LiveOpsBanner() {
  const nav = useNavigate()
  const [events, setEvents] = useState([])
  const [running, setRunning] = useState([])
  const [snapshot, setSnapshot] = useState(null)
  const [agentNames, setAgentNames] = useState({})
  const [tickKey, setTickKey] = useState(0)
  const [paused, setPaused] = useState(false)
  // Session dismiss so health pills don't thrash the bar after user acknowledges
  const [dismissedCredits, setDismissedCredits] = useState(false)
  const [dismissedFails, setDismissedFails] = useState(false)
  const scrollRef = useRef(null)
  const wsRef = useRef(null)
  const seenIds = useRef(new Set())
  const inflight = useRef(false)

  const bumpTicker = useCallback(() => {
    setTickKey((k) => k + 1)
  }, [])

  const pushEntry = useCallback((entry) => {
    if (!entry) return
    const id = entry.id ?? `${entry.title}-${entry.created_at}`
    const isNew = !seenIds.current.has(id)
    if (isNew) {
      seenIds.current.add(id)
      // Bound memory
      if (seenIds.current.size > 200) {
        seenIds.current = new Set([...seenIds.current].slice(-100))
      }
      // Re-surface health if a new credit/fail event arrives after dismiss
      if (eventLooksLikeCredits(entry)) setDismissedCredits(false)
      if (String(entry.status || '').toLowerCase() === 'failed') setDismissedFails(false)
    }

    setEvents((prev) => {
      const next = [entry, ...prev.filter((e) => e.id !== entry.id)].slice(0, 48)
      return next
    })
    setRunning((prev) => {
      if (entry.status === 'running' || entry.status === 'queued') {
        return [entry, ...prev.filter((e) => e.id !== entry.id)].slice(0, 12)
      }
      return prev.filter(
        (e) => !(e.id === entry.id && (entry.status === 'done' || entry.status === 'failed')),
      )
    })

    if (isNew) bumpTicker()

    if (isNative() && isNew) {
      if (entry.status === 'failed') {
        hapticError()
        notifyLocal({
          title: entry.title || 'Agent issue',
          body: entry.detail || entry.message || 'An agent step failed',
          extra: { path: eventAgentId(entry) ? `/console/${eventAgentId(entry)}` : '/ops' },
        })
      } else if (entry.status === 'done') {
        hapticSuccess()
      } else if (entry.status === 'running') {
        hapticLight()
      }
    }
  }, [bumpTicker])

  const mergeList = useCallback((list) => {
    if (!Array.isArray(list) || !list.length) return
    setEvents((prev) => {
      const byId = new Map()
      for (const e of [...list, ...prev]) {
        if (e?.id != null && !byId.has(e.id)) byId.set(e.id, e)
      }
      const next = [...byId.values()]
        .sort((a, b) => (b.id || 0) - (a.id || 0))
        .slice(0, 48)
      // New head?
      if (next[0]?.id && next[0].id !== prev[0]?.id) {
        setTimeout(bumpTicker, 0)
      }
      for (const e of next) {
        if (e?.id != null) seenIds.current.add(e.id)
      }
      return next
    })
    setRunning(
      list.filter((e) => e.status === 'running' || e.status === 'queued').slice(0, 12),
    )
  }, [bumpTicker])

  // Load agent names so chips show "Sales Lead" not just titles — once only
  useEffect(() => {
    let cancelled = false
    api('/agents/')
      .then((list) => {
        if (cancelled) return
        const map = {}
        for (const a of Array.isArray(list) ? list : []) {
          if (a?.id != null) map[a.id] = a.name || `Agent #${a.id}`
        }
        setAgentNames(map)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  // Initial load + sparse poll. Prefer WS when connected; pause when tab hidden.
  useEffect(() => {
    let cancelled = false
    let wsConnected = false
    let lastWsAt = 0
    // Sparse: was aggressive REST; keep ~18–20s and skip while WS is live
    const pollMs = import.meta.env.PROD ? 20000 : 22000
    const wsSkipMs = 28000

    const load = () => {
      if (cancelled) return
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
      if (wsConnected && Date.now() - lastWsAt < wsSkipMs) return
      if (inflight.current) return
      inflight.current = true
      api('/ops/live?limit=40')
        .then((r) => {
          if (cancelled) return
          const list = r?.events || []
          mergeList(list)
          if (r?.snapshot) {
            setSnapshot(r.snapshot)
            if (Array.isArray(r.snapshot.running)) setRunning(r.snapshot.running)
          } else if (r?.snapshot?.running) {
            setRunning(r.snapshot.running)
          }
        })
        .catch(() => {
          // Never crash the shell on ops poll failure
        })
        .finally(() => {
          inflight.current = false
        })
    }
    load()
    const iv = setInterval(load, pollMs)

    const onVisibility = () => {
      if (document.visibilityState === 'visible') load()
    }
    document.addEventListener('visibilitychange', onVisibility)

    let ws
    try {
      ws = connectAuthedWs('/ops/ws')
      ws.onopen = () => {
        wsConnected = true
        lastWsAt = Date.now()
      }
      ws.onclose = () => {
        wsConnected = false
      }
      ws.onerror = () => {
        wsConnected = false
      }
      ws.onmessage = (ev) => {
        try {
          const m = JSON.parse(ev.data)
          if (m.type === 'auth_ok') {
            wsConnected = true
            lastWsAt = Date.now()
            return
          }
          wsConnected = true
          lastWsAt = Date.now()
          if (m.event === 'ops' && m.entry) pushEntry(m.entry)
          if (m.event === 'snapshot' && m.snapshot) {
            setSnapshot(m.snapshot)
            mergeList(m.snapshot.events || [])
            setRunning(m.snapshot.running || [])
          }
        } catch { /* ignore bad frames */ }
      }
      wsRef.current = ws
    } catch { /* WS optional */ }

    return () => {
      cancelled = true
      clearInterval(iv)
      document.removeEventListener('visibilitychange', onVisibility)
      try { ws?.close() } catch { /* ignore */ }
    }
  }, [mergeList, pushEntry])

  // Keep horizontal scroll pinned to newest chips when list updates
  useEffect(() => {
    const el = scrollRef.current
    if (!el || paused) return
    try {
      el.scrollTo({ left: 0, behavior: 'smooth' })
    } catch {
      el.scrollLeft = 0
    }
  }, [events, tickKey, paused])

  const health = useMemo(
    () => deriveHealth(events, snapshot),
    [events, snapshot],
  )

  const openOps = () => nav('/ops')
  const openBilling = () => nav('/billing')

  const openEvent = (e, ev) => {
    ev?.stopPropagation?.()
    const aid = eventAgentId(e)
    if (aid != null) {
      nav(`/console/${aid}`)
      return
    }
    openOps()
  }

  // Prefer running, then recent events — all clickable
  const chips = useMemo(() => {
    const seen = new Set()
    const out = []
    for (const e of [...running, ...events]) {
      if (!e) continue
      const key = e.id ?? `${e.title}-${e.created_at}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push(e)
      if (out.length >= 24) break
    }
    return out
  }, [running, events])

  // Marquee track: duplicate chips for seamless CSS loop when enough items
  const marqueeItems = useMemo(() => {
    if (chips.length === 0) return []
    if (chips.length < 4) return chips
    return [...chips, ...chips]
  }, [chips])

  const useMarquee = chips.length >= 3 && !paused

  const showCredits = health.creditsIssue && !dismissedCredits
  const showFails = (health.terminalFail || health.failedCount > 0) && !dismissedFails
    && !showCredits // credits take priority when both fire

  return (
    <div className="aba-live-ops-banner" aria-label="Live ops ticker">
      <Button
        type="text"
        size="small"
        className="aba-live-ops-label"
        onClick={openOps}
        icon={<ThunderboltOutlined style={{ color: '#69b1ff' }} />}
      >
        <Typography.Text strong className="aba-live-ops-label-text">
          LIVE OPS
        </Typography.Text>
        {running.length > 0 ? (
          <Tag icon={<LoadingOutlined />} color="processing" className="aba-live-ops-active-tag">
            {running.length}
          </Tag>
        ) : null}
      </Button>

      {/* Health from ops payload only — dismissible, no extra polling */}
      {showCredits && (
        <Tooltip title={health.headline || 'Top up credits so agents can keep running tools and models'}>
          <Tag
            color="error"
            icon={<DollarOutlined />}
            className="aba-live-ops-health-tag"
            style={{ cursor: 'pointer', margin: 0, flex: '0 0 auto' }}
            onClick={openBilling}
            closable
            onClose={(e) => {
              e.preventDefault()
              e.stopPropagation()
              setDismissedCredits(true)
            }}
          >
            Credits
          </Tag>
        </Tooltip>
      )}
      {showFails && (
        <Tooltip
          title={
            health.latestFail
              ? `${health.latestFail.title || 'Failure'}${health.latestFail.detail ? `: ${String(health.latestFail.detail).slice(0, 120)}` : ''}`
              : (health.headline || 'Recent agent step failed')
          }
        >
          <Tag
            color="error"
            icon={<WarningOutlined />}
            className="aba-live-ops-health-tag"
            style={{ cursor: 'pointer', margin: 0, flex: '0 0 auto' }}
            onClick={() => {
              if (health.latestFail) openEvent(health.latestFail)
              else openOps()
            }}
            closable
            onClose={(e) => {
              e.preventDefault()
              e.stopPropagation()
              setDismissedFails(true)
            }}
          >
            {health.terminalFail
              ? 'Terminal fail'
              : `${health.failedCount} failed`}
          </Tag>
        </Tooltip>
      )}

      <div
        className={`aba-live-ops-track-wrap${useMarquee ? ' is-marquee' : ''}`}
        ref={scrollRef}
        onMouseEnter={() => setPaused(true)}
        onMouseLeave={() => setPaused(false)}
        onTouchStart={() => setPaused(true)}
        onTouchEnd={() => setTimeout(() => setPaused(false), 1200)}
      >
        {chips.length === 0 ? (
          <Button type="text" size="small" className="aba-live-ops-empty" onClick={openOps}>
            Waiting for agent plans &amp; actions…
          </Button>
        ) : (
          <div
            key={tickKey}
            className={`aba-live-ops-track${useMarquee ? ' aba-live-ops-track--scroll' : ''}${paused ? ' is-paused' : ''}`}
            style={useMarquee ? { animationDuration: `${Math.max(18, marqueeItems.length * 3.2)}s` } : undefined}
          >
            {marqueeItems.map((e, idx) => {
              const aid = eventAgentId(e)
              const agentLabel = eventAgentLabel(e, agentNames)
              const tip = [
                agentLabel && `Agent: ${agentLabel}`,
                e.title,
                e.detail && String(e.detail).slice(0, 160),
                aid != null ? 'Tap → agent chat' : 'Tap → Live ops',
              ].filter(Boolean).join('\n')

              return (
                <Tooltip
                  key={`${e.id ?? 'x'}-${idx}`}
                  title={<span style={{ whiteSpace: 'pre-line' }}>{tip}</span>}
                >
                  <Tag
                    color={STATUS_COLOR[e.status] || 'default'}
                    className={`aba-live-ops-chip status-${e.status || 'info'}${aid != null ? ' has-agent' : ''}${e.status === 'failed' ? ' is-failed' : ''}`}
                    onClick={(ev) => openEvent(e, ev)}
                    icon={(
                      <span className="aba-live-ops-chip-icon">
                        {e.status === 'done' && <CheckCircleOutlined />}
                        {e.status === 'failed' && <CloseCircleOutlined />}
                        {e.status === 'running' && <LoadingOutlined />}
                        {e.status !== 'done' && e.status !== 'failed' && e.status !== 'running'
                          && (KIND_ICON[e.kind] || KIND_ICON.action)}
                      </span>
                    )}
                  >
                    {agentLabel ? (
                      <span className="aba-live-ops-chip-agent">
                        <RobotOutlined /> {agentLabel}
                      </span>
                    ) : null}
                    <span className="aba-live-ops-chip-title">{e.title || e.kind || 'Update'}</span>
                    {aid != null ? <RightOutlined className="aba-live-ops-chip-go" /> : null}
                  </Tag>
                </Tooltip>
              )
            })}
          </div>
        )}
      </div>

      <div className="aba-live-ops-actions">
        <Space size={6} wrap>
          {running.slice(0, 2).map((e) => {
            const label = eventAgentLabel(e, agentNames) || e.title
            return (
              <Tag
                key={`run-${e.id}`}
                color={STATUS_COLOR[e.status] || 'processing'}
                className="aba-live-ops-run-tag"
                onClick={() => openEvent(e)}
                style={{ cursor: 'pointer', margin: 0, maxWidth: 120 }}
              >
                <LoadingOutlined />{' '}
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{label}</span>
              </Tag>
            )
          })}
          <Button size="small" type="primary" ghost onClick={openOps}>
            Ops
          </Button>
        </Space>
      </div>
    </div>
  )
}
