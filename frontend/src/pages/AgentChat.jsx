import React, { useEffect, useRef, useState, useCallback } from 'react'
import {
  Button, Card, Input, Space, Typography, Spin, Tag, Dropdown, Switch, message, Tooltip, Drawer, List, Alert,
} from 'antd'
import {
  ArrowLeftOutlined, SendOutlined, MoreOutlined, SettingOutlined, AppstoreOutlined,
  ThunderboltOutlined, RobotOutlined, MenuOutlined,
  PauseCircleOutlined, PlayCircleOutlined, NodeIndexOutlined,
  ClusterOutlined, CheckSquareOutlined, CommentOutlined, TeamOutlined,
  ApartmentOutlined, HomeOutlined, CreditCardOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams, useLocation } from 'react-router-dom'
import { api, connectAuthedWs, safeJsonParse } from '../api'
import { hapticMedium, hapticSuccess, hapticError, acquireKeepAwake, releaseKeepAwake, forceAllowSleep } from '../native'
import VoiceControls, { speakText, stopSpeaking } from '../components/VoiceControls'
import MediaActions from '../components/MediaActions'
import MessageActions from '../components/MessageActions'

const { Text } = Typography
const { TextArea } = Input

const STARTERS = [
  'What can you do for me right now?',
  'Summarise my open work',
  'Draft a professional follow-up',
  'Run a quick plan for today',
]

/** Pull ```questions blocks out of assistant text for UI chips under the bubble. */
function splitAssistantContent(raw) {
  const text = String(raw || '')
  const questions = []
  // ```questions ... ```
  let display = text.replace(/```questions\s*([\s\S]*?)```/gi, (_, body) => {
    String(body || '')
      .split('\n')
      .map((l) => l.replace(/^[-*•\d.)\s]+/, '').trim())
      .filter((l) => l.length > 2 && l.length < 200)
      .forEach((q) => {
        if (!questions.includes(q)) questions.push(q.endsWith('?') ? q : `${q}?`)
      })
    return ''
  })
  // Hide skill / code dumps from the spoken bubble (still ran server-side)
  display = display
    .replace(/```skill\s*[\s\S]*?```/gi, '')
    .replace(/```json\s*[\s\S]*?```/gi, '')
    .replace(/```[a-z0-9_-]*\s*[\s\S]*?```/gi, (block) => {
      // Keep short non-code fences; strip long code-looking blocks
      if (block.length > 280 || /[{;}=<>]|function |const |import /.test(block)) return ''
      return block
    })
    .replace(/\n{3,}/g, '\n\n')
    .trim()
  // Fallback: trailing lines that look like bare questions when model forgot the fence
  if (!questions.length) {
    const lines = display.split('\n').map((l) => l.trim()).filter(Boolean)
    const tail = []
    for (let i = lines.length - 1; i >= 0 && tail.length < 4; i--) {
      const l = lines[i].replace(/^[-*•\d.)\s]+/, '')
      if (l.endsWith('?') && l.length < 160) tail.unshift(l)
      else break
    }
    if (tail.length >= 1 && tail.length <= 4 && lines.length > tail.length) {
      questions.push(...tail)
      display = lines.slice(0, lines.length - tail.length).join('\n').trim()
    }
  }
  return { display: display || text.trim(), questions: questions.slice(0, 6) }
}

/** Normalize optional API `goal_chain` payload — never throw on shape. */
function parseGoalChain(gc) {
  if (!gc || typeof gc !== 'object') return null
  try {
    const parentRaw = gc.parent_task_id ?? gc.parent_id ?? null
    const parentId = parentRaw != null && parentRaw !== '' ? parentRaw : null
    let stepCount = null
    if (gc.steps != null && gc.steps !== '' && Number.isFinite(Number(gc.steps))) {
      stepCount = Number(gc.steps)
    } else if (Array.isArray(gc.children)) {
      stepCount = gc.children.length
    }
    const apiMessage = typeof gc.message === 'string' && gc.message.trim()
      ? gc.message.trim()
      : null
    return {
      parent_task_id: parentId,
      steps: stepCount,
      deduped: !!gc.deduped,
      ok: gc.ok !== false,
      message: apiMessage,
    }
  } catch {
    return null
  }
}

/** Compact Alert under an assistant bubble when auto-chain / execute_goal fired. */
function GoalChainAlert({ chain, onOpenTasks }) {
  if (!chain || typeof chain !== 'object') return null
  const failed = chain.ok === false
  const type = failed ? 'warning' : (chain.deduped ? 'info' : 'success')
  const title = failed
    ? 'Goal chain issue'
    : (chain.deduped ? 'Goal chain already running' : 'Goal chain started')
  const meta = []
  if (chain.parent_task_id != null) meta.push(`task #${chain.parent_task_id}`)
  if (chain.steps != null && Number.isFinite(Number(chain.steps))) {
    const n = Number(chain.steps)
    meta.push(`${n} step${n === 1 ? '' : 's'}`)
  }
  const description = chain.message
    || 'Auto-chain: prompt → task → delegate → monitor → complete'

  return (
    <Card
      size="small"
      bordered
      className="agent-chat-goal-chain-card"
      styles={{ body: { padding: 0 } }}
    >
      <Alert
        type={type}
        showIcon
        icon={failed ? undefined : <NodeIndexOutlined />}
        className="agent-chat-goal-chain"
        banner
        message={(
          <span className="agent-chat-goal-chain-title">
            {title}
            {meta.length ? ` · ${meta.join(' · ')}` : ''}
          </span>
        )}
        description={(
          <span className="agent-chat-goal-chain-desc">{description}</span>
        )}
        action={onOpenTasks ? (
          <Button size="small" type="link" onClick={onOpenTasks}>
            Tasks
          </Button>
        ) : null}
      />
    </Card>
  )
}

/**
 * ChatGPT-style one-agent page — full focus conversation on mobile & desktop.
 * Messages + composer sit in bordered Cards; goal_chain from chat API shows as Alert.
 */
export default function AgentChat() {
  const { id } = useParams()
  const nav = useNavigate()
  const loc = useLocation()
  const [agent, setAgent] = useState(null)
  const [loading, setLoading] = useState(true)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [live, setLive] = useState(false)
  const [speakReplies, setSpeakReplies] = useState(
    () => localStorage.getItem('voice_speak_replies') === '1',
  )
  const [menuOpen, setMenuOpen] = useState(false)
  const [sessionTokens, setSessionTokens] = useState(0)

  const bottomRef = useRef(null)
  const listRef = useRef(null)
  const wsRef = useRef(null)
  const speakRef = useRef(speakReplies)
  speakRef.current = speakReplies

  const scrollBottom = useCallback((smooth = true) => {
    requestAnimationFrame(() => {
      bottomRef.current?.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'end' })
    })
  }, [])

  const load = useCallback(() => {
    setLoading(true)
    api(`/agents/${id}`)
      .then((a) => {
        setAgent(a)
        if (Array.isArray(a.chat?.messages) && a.chat.messages.length) {
          setMessages(a.chat.messages.map((m) => ({ role: m.role, content: m.content })))
        } else {
          setMessages([])
        }
      })
      .catch((e) => {
        message.error(e.message)
        nav('/console')
      })
      .finally(() => setLoading(false))
  }, [id, nav])

  useEffect(() => {
    load()
    // Vercel serverless does not support durable WebSockets (handshake 403).
    // Production chat always uses REST POST /agents/:id/chat.
    // Local/native may still use WS for streaming.
    const allowWs = !import.meta.env.PROD
    let cws
    if (allowWs) {
      try {
        cws = connectAuthedWs(`/agents/${id}/ws/chat`)
        cws.onopen = () => setLive(true)
        cws.onclose = () => setLive(false)
        cws.onerror = () => setLive(false)
        cws.onmessage = (e) => {
          const m = safeJsonParse(e?.data)
          if (!m || typeof m !== 'object') return
          try {
            if (m.type === 'auth_ok') return
            if (m.type === 'error') {
              message.error(m.content || 'Chat error')
              setBusy(false)
            }
            if (m.type === 'start') {
              setMessages((prev) => {
                const next = [...prev, { role: 'assistant', content: '', streaming: true }]
                return next.length > 80 ? next.slice(-80) : next
              })
              scrollBottom()
            }
            if (m.type === 'chunk') {
              setMessages((prev) => {
                const next = [...prev]
                const last = next[next.length - 1]
                if (last?.streaming) last.content += (m.content || '')
                else next.push({ role: 'assistant', content: m.content || '', streaming: true })
                return next
              })
              scrollBottom(false)
            }
            if (m.type === 'done') {
              setBusy(false)
              setSessionTokens((t) => t + (m.tokens || 0))
              try {
                window.dispatchEvent(new CustomEvent('aba-usage', {
                  detail: {
                    tokens: m.tokens,
                    tokens_used_period: m.tokens_used_period,
                    credits: m.credits,
                    cost: m.cost,
                  },
                }))
              } catch { /* ignore */ }
              const goalChainMeta = parseGoalChain(m.goal_chain)
              setMessages((prev) => {
                const next = prev.map((x) => ({ ...x, streaming: false }))
                if (goalChainMeta) {
                  for (let i = next.length - 1; i >= 0; i -= 1) {
                    if (next[i].role === 'assistant') {
                      next[i] = { ...next[i], goal_chain: goalChainMeta }
                      break
                    }
                  }
                }
                if (speakRef.current) {
                  try {
                    const last = [...next].reverse().find((x) => x.role === 'assistant' && x.content)
                    if (last?.content) {
                      const spoken = splitAssistantContent(last.content).display || last.content
                      speakText(spoken)
                    }
                  } catch { /* TTS must never break chat */ }
                }
                return next.length > 80 ? next.slice(-80) : next
              })
            }
          } catch (err) {
            console.warn('[agent-chat ws]', err)
            setBusy(false)
          }
        }
        wsRef.current = cws
      } catch {
        setLive(false)
      }
    } else {
      setLive(false)
      wsRef.current = null
    }
    return () => {
      try { cws?.close() } catch { /* ignore */ }
      stopSpeaking()
    }
  }, [id, load, scrollBottom])

  useEffect(() => { scrollBottom() }, [messages.length, scrollBottom])

  const abortRef = useRef(null)

  // Leave page mid-reply without hanging the request forever in the UI
  useEffect(() => () => {
    try { abortRef.current?.abort() } catch { /* ignore */ }
    stopSpeaking()
    forceAllowSleep().catch(() => {})
  }, [])

  // Keep phone awake while the agent is generating a reply or speaking
  useEffect(() => {
    if (busy) {
      acquireKeepAwake('agent-busy').catch(() => {})
      return () => { releaseKeepAwake().catch(() => {}) }
    }
    return undefined
  }, [busy])

  const send = async (text) => {
    const msg = (text ?? input).trim()
    if (!msg) return
    // Voice can finish while a reply is still streaming — keep text, don't drop it
    if (busy) {
      setInput(msg)
      message.info('Agent is still replying — your speech is in the box. Tap Send when ready.')
      return
    }
    try { hapticMedium() } catch { /* ignore */ }
    // Stop any ongoing TTS before sending a new message
    try { stopSpeaking() } catch { /* ignore */ }
    setMessages((prev) => {
      const next = [...prev, { role: 'user', content: msg }, { role: 'assistant', content: '', streaming: true, pending: true }]
      // Cap history so long sessions don't freeze mobile browsers
      return next.length > 80 ? next.slice(-80) : next
    })
    setInput('')
    setBusy(true)
    scrollBottom()

    // Prefer REST always in production; WS only if fully open (local)
    if (!import.meta.env.PROD && wsRef.current?.readyState === 1) {
      // Remove pending bubble — WS path will emit start/chunk/done
      setMessages((prev) => prev.filter((m) => !m.pending))
      wsRef.current.send(JSON.stringify({ message: msg }))
      return
    }

    try { abortRef.current?.abort() } catch { /* ignore */ }
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
    abortRef.current = controller
    // Chat should return in ~10–40s; 90s hard cap so UI never feels stuck forever
    const timeoutMs = 90000
    const timer = controller
      ? setTimeout(() => controller.abort(), timeoutMs)
      : null

    try {
      const r = await api(`/agents/${id}/chat`, {
        method: 'POST',
        body: { message: msg },
        signal: controller?.signal,
      })
      const replyText = (r?.reply || r?.message || r?.content || '').toString().trim()
        || 'No reply text returned. Try again — if it keeps failing, refresh and re-send.'
      // Optional goal_chain from auto-chain / execute_goal — never crash on shape
      const goalChainMeta = parseGoalChain(r?.goal_chain)
      setMessages((prev) => {
        const next = [...prev]
        // Replace pending thinking bubble
        const pi = next.findIndex((m) => m.pending || (m.streaming && m.role === 'assistant' && !m.content))
        const assistantMsg = {
          role: 'assistant',
          content: replyText,
          ...(goalChainMeta ? { goal_chain: goalChainMeta } : {}),
        }
        if (pi >= 0) {
          next[pi] = assistantMsg
        } else {
          next.push(assistantMsg)
        }
        return next
      })
      setSessionTokens((t) => t + (r.tokens || 0))
      try {
        window.dispatchEvent(new CustomEvent('aba-usage', {
          detail: {
            tokens: r.tokens,
            tokens_used_period: r.tokens_used_period,
            credits: r.credits,
            cost: r.cost,
          },
        }))
      } catch { /* ignore */ }
      hapticSuccess()
      if (speakRef.current && replyText) {
        // Speak the human-facing text only (no skill/questions fences)
        const spoken = splitAssistantContent(replyText).display || replyText
        speakText(spoken)
      }
    } catch (e) {
      hapticError()
      const aborted = e?.name === 'AbortError' || /abort/i.test(String(e?.message || ''))
      const err = aborted
        ? 'Reply timed out. Try a shorter message, or wait a moment and send again (cold start can take ~30s once).'
        : (e.message || 'Chat failed')
      message.error(err)
      setMessages((prev) => {
        const next = prev.filter((m) => !m.pending)
        next.push({ role: 'assistant', content: `Sorry — ${err}` })
        return next
      })
    } finally {
      if (timer) clearTimeout(timer)
      if (abortRef.current === controller) abortRef.current = null
      setBusy(false)
    }
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const onInputChange = (e) => {
    // Ant Design TextArea + autoSize: only update controlled value.
    // Never set style.height / scrollHeight on the DOM node or textareaRef
    // (Ant Design owns height; manual writes crash / fight the ref wrapper).
    const v = e?.target?.value
    setInput(typeof v === 'string' ? v : String(v ?? ''))
  }

  const togglePause = async () => {
    if (!agent) return
    try {
      await api(`/agents/${id}/${agent.status === 'active' ? 'pause' : 'resume'}`, { method: 'POST' })
      load()
    } catch (e) {
      message.error(e.message)
    }
  }

  if (loading || !agent) {
    return (
      <div className="agent-chat-shell agent-chat-loading">
        <Spin size="large" tip="Opening agent…" />
      </div>
    )
  }

  const isEmpty = messages.length === 0

  return (
    <div className="agent-chat-shell">
      {/* Top bar */}
      <header className="agent-chat-top">
        <Button
          type="text"
          className="agent-chat-icon-btn"
          icon={<ArrowLeftOutlined />}
          onClick={() => {
            // Always allow leaving even while a reply is in flight
            try { abortRef.current?.abort() } catch { /* ignore */ }
            try { stopSpeaking() } catch { /* ignore */ }
            // Prefer browser history; fall back to agents list for deep links
            if (loc.key && loc.key !== 'default') {
              nav(-1)
              return
            }
            const p = loc.pathname || ''
            if (p.startsWith('/army')) nav('/army')
            else if (p.startsWith('/agents')) nav('/agents')
            else nav('/console')
          }}
          aria-label="Back"
        />
        <button type="button" className="agent-chat-identity" onClick={() => setMenuOpen(true)}>
          <div className="agent-chat-avatar">
            <RobotOutlined />
          </div>
          <div className="agent-chat-id-text">
            <strong>{agent.name}</strong>
            <span>
              {live ? 'Live' : 'Online'}
              {agent.hierarchy_role ? ` · ${agent.hierarchy_role}` : ''}
              {sessionTokens ? ` · ${sessionTokens} tok` : ''}
            </span>
          </div>
        </button>
        <Space size={4}>
          <Tag color={agent.status === 'active' ? 'success' : 'warning'} style={{ margin: 0 }}>
            {agent.status}
          </Tag>
          <Dropdown
            menu={{
              items: [
                {
                  key: 'manage',
                  icon: <SettingOutlined />,
                  label: 'Agent workspace',
                  onClick: () => nav(`/agents/${id}/manage`),
                },
                {
                  key: 'pause',
                  icon: agent.status === 'active' ? <PauseCircleOutlined /> : <PlayCircleOutlined />,
                  label: agent.status === 'active' ? 'Pause agent' : 'Resume agent',
                  onClick: togglePause,
                },
                {
                  key: 'ops',
                  icon: <ThunderboltOutlined />,
                  label: 'Live ops',
                  onClick: () => nav('/ops'),
                },
              ],
            }}
            trigger={['click']}
          >
            <Button type="text" className="agent-chat-icon-btn" icon={<MoreOutlined />} />
          </Dropdown>
        </Space>
      </header>

      {/* Messages — bordered panel, full remaining height */}
      <Card
        className="agent-chat-messages-card"
        bordered
        size="small"
        styles={{ body: { padding: 0, height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0 } }}
      >
        <main className="agent-chat-messages" ref={listRef}>
          {isEmpty ? (
            <div className="agent-chat-empty">
              <div className="agent-chat-empty-avatar">
                <RobotOutlined />
              </div>
              <h1>{agent.name}</h1>
              <p>
                {agent.personality
                  ? String(agent.personality).slice(0, 160)
                  : 'Your AI teammate — ask anything or tap a starter below.'}
              </p>
              <div className="agent-chat-starters">
                {STARTERS.map((s) => (
                  <button key={s} type="button" className="agent-chat-starter" onClick={() => send(s)} disabled={busy}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="agent-chat-thread">
              {messages.map((m, i) => {
                const isUser = m.role === 'user'
                const split = !isUser && m.content && !m.streaming
                  ? splitAssistantContent(m.content)
                  : { display: m.content, questions: [] }
                return (
                <div
                  key={i}
                  className={`agent-chat-row ${isUser ? 'is-user' : 'is-assistant'}`}
                >
                  {!isUser && (
                    <div className="agent-chat-msg-avatar">
                      <RobotOutlined />
                    </div>
                  )}
                  <div className="agent-chat-msg-stack">
                    <div className={`agent-chat-bubble ${m.streaming ? 'is-streaming' : ''}`}>
                      {split.display || (m.streaming ? (
                        <span className="agent-chat-dots"><i /><i /><i /></span>
                      ) : '')}
                    </div>
                    {!isUser && !m.streaming && (split.display || m.content) && (
                      <MessageActions
                        text={split.display || m.content}
                        filename={`${(agent?.name || 'agent').replace(/\s+/g, '-')}-reply`}
                        className="agent-chat-msg-actions"
                      />
                    )}
                    {!isUser && !m.streaming && split.questions?.length > 0 && (
                      <div className="agent-chat-questions" role="group" aria-label="Questions from agent">
                        <Text type="secondary" className="agent-chat-questions-label">
                          Quick answers — tap a question to reply
                        </Text>
                        <div className="agent-chat-questions-list">
                          {split.questions.map((q) => (
                            <button
                              key={q}
                              type="button"
                              className="agent-chat-question-chip"
                              disabled={busy}
                              onClick={() => {
                                setInput((prev) => {
                                  const base = (prev || '').trim()
                                  // Prefill an answer template so user can type under the question
                                  return base
                                    ? `${base}\n\nRe: ${q}\n`
                                    : `${q}\n\nMy answer: `
                                })
                                // Focus composer — soft scroll
                                try {
                                  document.querySelector('.agent-chat-textarea')?.focus?.()
                                } catch { /* ignore */ }
                              }}
                            >
                              {q}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    {m.goal_chain && typeof m.goal_chain === 'object' && (
                      <GoalChainAlert
                        chain={m.goal_chain}
                        onOpenTasks={() => nav('/tasks')}
                      />
                    )}
                  </div>
                </div>
                )
              })}
              <div ref={bottomRef} />
            </div>
          )}
        </main>
      </Card>

      {/* Composer — bordered panel */}
      <Card
        className="agent-chat-composer-card"
        bordered
        size="small"
        styles={{ body: { padding: '10px 12px 8px' } }}
      >
        <footer className="agent-chat-composer">
          <div className="agent-chat-composer-inner">
            <div className="agent-chat-tools">
              <VoiceControls
                disabled={busy}
                onTranscript={(text) => send(text)}
                onPartial={(t) => setInput(t)}
                speakReplies={speakReplies}
                onSpeakRepliesChange={(v) => {
                  setSpeakReplies(v)
                  localStorage.setItem('voice_speak_replies', v ? '1' : '0')
                }}
              />
              <MediaActions disabled={busy} compact />
              <Tooltip title="Agent workspace">
                <Button
                  type="text"
                  size="small"
                  icon={<AppstoreOutlined />}
                  onClick={() => nav(`/agents/${id}/manage`)}
                />
              </Tooltip>
            </div>
            <div className="agent-chat-input-wrap">
              <TextArea
                value={input}
                onChange={onInputChange}
                onKeyDown={onKeyDown}
                placeholder={`Message ${agent.name}… or tap mic to talk`}
                autoSize={{ minRows: 1, maxRows: 6 }}
                disabled={false}
                className="agent-chat-textarea"
                bordered={false}
              />
              <Button
                type="primary"
                size="large"
                icon={<SendOutlined />}
                loading={busy}
                disabled={!input.trim() && !busy}
                onClick={() => send()}
                className="agent-chat-send"
                aria-label="Send message"
              >
                <span className="agent-chat-send-label">Send</span>
              </Button>
            </div>
            <Text type="secondary" className="agent-chat-hint">
              Tap <strong>Send</strong> to message the agent · Mic to talk · Screen stays on while agent speaks
            </Text>
          </div>
        </footer>
      </Card>

      <Drawer
        title={agent.name}
        placement="bottom"
        height="auto"
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        className="agent-chat-drawer"
      >
        <List
          dataSource={[
            { label: 'Agent workspace (skills, spawn)', icon: <SettingOutlined />, go: () => nav(`/console/${id}/manage`) },
            { label: 'Agent Console', icon: <MenuOutlined />, go: () => nav('/console') },
            { label: 'Hierarchy', icon: <ClusterOutlined />, go: () => nav('/hierarchy') },
            { label: 'Tasks board', icon: <CheckSquareOutlined />, go: () => nav('/tasks') },
            { label: 'Meetings', icon: <CommentOutlined />, go: () => nav('/meetings') },
            { label: 'Business CRM', icon: <AppstoreOutlined />, go: () => nav('/business') },
            { label: 'Live ops', icon: <ThunderboltOutlined />, go: () => nav('/ops') },
            { label: 'Team / Humans', icon: <TeamOutlined />, go: () => nav('/humans') },
            { label: 'Workspace', icon: <ApartmentOutlined />, go: () => nav('/workspace') },
            { label: 'Dashboard', icon: <HomeOutlined />, go: () => nav('/') },
            { label: 'Billing', icon: <CreditCardOutlined />, go: () => nav('/billing') },
            { label: 'Settings', icon: <SettingOutlined />, go: () => nav('/settings') },
          ]}
          renderItem={(item) => (
            <List.Item
              className="aba-click-row"
              onClick={() => { setMenuOpen(false); item.go() }}
              style={{ cursor: 'pointer' }}
            >
              <Space>{item.icon}{item.label}</Space>
            </List.Item>
          )}
        />
        <div style={{ padding: '8px 0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>Speak replies</span>
          <Switch
            checked={speakReplies}
            onChange={(v) => {
              setSpeakReplies(v)
              localStorage.setItem('voice_speak_replies', v ? '1' : '0')
            }}
          />
        </div>
      </Drawer>
    </div>
  )
}
