import React, { useEffect, useRef, useState } from 'react'
import { Tag, Typography, Space, Button, Tooltip } from 'antd'
import {
  ThunderboltOutlined, RobotOutlined, UserOutlined, ApiOutlined,
  ClusterOutlined, CheckCircleOutlined, LoadingOutlined, CloseCircleOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, getToken, getWsBase } from '../api'

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

/**
 * Sticky real-time action/plan ticker under the app header.
 */
export default function LiveOpsBanner() {
  const nav = useNavigate()
  const [events, setEvents] = useState([])
  const [running, setRunning] = useState([])
  const wsRef = useRef(null)

  const pushEntry = (entry) => {
    if (!entry) return
    setEvents((prev) => {
      const next = [entry, ...prev.filter((e) => e.id !== entry.id)].slice(0, 40)
      return next
    })
    setRunning((prev) => {
      if (entry.status === 'running' || entry.status === 'queued') {
        return [entry, ...prev.filter((e) => e.id !== entry.id)].slice(0, 8)
      }
      return prev.filter((e) => e.id !== entry.id && e.plan_id !== entry.plan_id || entry.status !== 'done')
        .filter((e) => !(e.id === entry.id && (entry.status === 'done' || entry.status === 'failed')))
    })
  }

  useEffect(() => {
    api('/ops/live?limit=20')
      .then((r) => {
        setEvents(r.events || [])
        setRunning((r.snapshot?.running) || (r.events || []).filter((e) => e.status === 'running').slice(0, 8))
      })
      .catch(() => {})

    let ws
    try {
      ws = new WebSocket(`${getWsBase()}/ops/ws?token=${getToken()}`)
      ws.onmessage = (ev) => {
        try {
          const m = JSON.parse(ev.data)
          if (m.event === 'ops' && m.entry) pushEntry(m.entry)
          if (m.event === 'snapshot' && m.snapshot) {
            setEvents(m.snapshot.events || [])
            setRunning(m.snapshot.running || [])
          }
        } catch { /* ignore */ }
      }
      wsRef.current = ws
    } catch { /* WS optional */ }
    return () => {
      try { ws?.close() } catch { /* ignore */ }
    }
  }, [])

  const latest = events[0]
  const ticker = running.length ? running : events.slice(0, 5)

  return (
    <div
      style={{
        background: 'linear-gradient(90deg,#0b1f3a 0%,#132f54 50%,#0b1f3a 100%)',
        color: '#fff',
        borderBottom: '1px solid rgba(255,255,255,0.08)',
        padding: '8px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        flexWrap: 'wrap',
        minHeight: 44,
      }}
    >
      <Space size={6}>
        <ThunderboltOutlined style={{ color: '#69b1ff' }} />
        <Typography.Text strong style={{ color: '#fff', fontSize: 12, letterSpacing: 0.4 }}>
          LIVE OPS
        </Typography.Text>
        {running.length > 0 && (
          <Tag icon={<LoadingOutlined />} color="processing" style={{ margin: 0 }}>
            {running.length} active
          </Tag>
        )}
      </Space>

      <div
        style={{
          flex: 1,
          minWidth: 200,
          overflow: 'hidden',
          whiteSpace: 'nowrap',
          textOverflow: 'ellipsis',
          fontSize: 13,
          opacity: 0.95,
        }}
      >
        {latest ? (
          <Tooltip title={latest.detail || latest.title}>
            <span>
              {KIND_ICON[latest.kind] || KIND_ICON.action}{' '}
              <strong>{latest.title}</strong>
              {latest.detail ? ` — ${latest.detail}` : ''}
            </span>
          </Tooltip>
        ) : (
          <span style={{ opacity: 0.65 }}>Waiting for agent plans & actions…</span>
        )}
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', maxWidth: '42%', justifyContent: 'flex-end' }}>
        {ticker.slice(0, 4).map((e) => (
          <Tag
            key={e.id}
            color={STATUS_COLOR[e.status] || 'default'}
            style={{ margin: 0, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis' }}
          >
            {e.status === 'done' && <CheckCircleOutlined />}
            {e.status === 'failed' && <CloseCircleOutlined />}
            {e.status === 'running' && <LoadingOutlined />}
            {' '}{e.title}
          </Tag>
        ))}
        <Button size="small" type="primary" ghost onClick={() => nav('/ops')}>
          Ops visual
        </Button>
      </div>
    </div>
  )
}
