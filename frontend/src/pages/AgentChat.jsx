import React, { useEffect, useRef, useState, useCallback } from 'react'
import {
  Button, Input, Space, Typography, Spin, Tag, Dropdown, Switch, message, Tooltip, Drawer, List,
} from 'antd'
import {
  ArrowLeftOutlined, SendOutlined, MoreOutlined, SettingOutlined, AppstoreOutlined,
  ThunderboltOutlined, AudioOutlined, RobotOutlined, PlusOutlined, MenuOutlined,
  CheckCircleOutlined, PauseCircleOutlined, PlayCircleOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { api, connectAuthedWs } from '../api'
import { hapticMedium } from '../native'
import VoiceControls, { speakText, stopSpeaking } from '../components/VoiceControls'
import MediaActions from '../components/MediaActions'

const { Text } = Typography
const { TextArea } = Input

const STARTERS = [
  'What can you do for me right now?',
  'Summarise my open work',
  'Draft a professional follow-up',
  'Run a quick plan for today',
]

/**
 * ChatGPT-style one-agent page — full focus conversation on mobile & desktop.
 */
export default function AgentChat() {
  const { id } = useParams()
  const nav = useNavigate()
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
  const taRef = useRef(null)
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
        if (a.chat?.messages?.length) {
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
          const m = JSON.parse(e.data)
          if (m.type === 'auth_ok') return
          if (m.type === 'error') {
            message.error(m.content)
            setBusy(false)
          }
          if (m.type === 'start') {
            setMessages((prev) => [...prev, { role: 'assistant', content: '', streaming: true }])
            scrollBottom()
          }
          if (m.type === 'chunk') {
            setMessages((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]
              if (last?.streaming) last.content += m.content
              else next.push({ role: 'assistant', content: m.content, streaming: true })
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
            setMessages((prev) => {
              const next = prev.map((x) => ({ ...x, streaming: false }))
              if (speakRef.current) {
                const last = [...next].reverse().find((x) => x.role === 'assistant' && x.content)
                if (last?.content) speakText(last.content)
              }
              return next
            })
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

  const send = async (text) => {
    hapticMedium()
    const msg = (text ?? input).trim()
    if (!msg || busy) return
    setMessages((prev) => [...prev, { role: 'user', content: msg }])
    setInput('')
    setBusy(true)
    // Show thinking bubble immediately so mobile users don't only see a spinner
    setMessages((prev) => [...prev, { role: 'assistant', content: '', streaming: true, pending: true }])
    if (taRef.current) taRef.current.style.height = 'auto'
    scrollBottom()

    // Prefer REST always in production; WS only if fully open (local)
    if (!import.meta.env.PROD && wsRef.current?.readyState === 1) {
      // Remove pending bubble — WS path will emit start/chunk/done
      setMessages((prev) => prev.filter((m) => !m.pending))
      wsRef.current.send(JSON.stringify({ message: msg }))
      return
    }

    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
    const timeoutMs = 120000
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
      setMessages((prev) => {
        const next = [...prev]
        // Replace pending thinking bubble
        const pi = next.findIndex((m) => m.pending || (m.streaming && m.role === 'assistant' && !m.content))
        if (pi >= 0) {
          next[pi] = { role: 'assistant', content: replyText }
        } else {
          next.push({ role: 'assistant', content: replyText })
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
      if (speakRef.current && replyText) speakText(replyText)
    } catch (e) {
      const aborted = e?.name === 'AbortError' || /abort/i.test(String(e?.message || ''))
      const err = aborted
        ? 'Reply timed out (over 2 minutes). Check connection and try a shorter message.'
        : (e.message || 'Chat failed')
      message.error(err)
      setMessages((prev) => {
        const next = prev.filter((m) => !m.pending)
        next.push({ role: 'assistant', content: `Sorry — ${err}` })
        return next
      })
    } finally {
      if (timer) clearTimeout(timer)
      setBusy(false)
    }
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const autoGrow = (e) => {
    const el = e?.target
    if (!el || !el.style) {
      setInput(e?.target?.value ?? '')
      return
    }
    try {
      el.style.height = 'auto'
      el.style.height = `${Math.min(el.scrollHeight || 40, 160)}px`
    } catch { /* ignore measure errors */ }
    setInput(el.value)
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
          onClick={() => nav('/console')}
          aria-label="Back to agents"
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

      {/* Messages */}
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
            {messages.map((m, i) => (
              <div
                key={i}
                className={`agent-chat-row ${m.role === 'user' ? 'is-user' : 'is-assistant'}`}
              >
                {m.role !== 'user' && (
                  <div className="agent-chat-msg-avatar">
                    <RobotOutlined />
                  </div>
                )}
                <div className={`agent-chat-bubble ${m.streaming ? 'is-streaming' : ''}`}>
                  {m.content || (m.streaming ? (
                    <span className="agent-chat-dots"><i /><i /><i /></span>
                  ) : '')}
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </main>

      {/* Composer */}
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
            <MediaActions disabled={busy} />
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
              ref={taRef}
              value={input}
              onChange={autoGrow}
              onKeyDown={onKeyDown}
              placeholder={`Message ${agent.name}…`}
              autoSize={{ minRows: 1, maxRows: 6 }}
              disabled={busy && false}
              className="agent-chat-textarea"
              bordered={false}
            />
            <Button
              type="primary"
              shape="circle"
              size="large"
              icon={<SendOutlined />}
              loading={busy}
              disabled={!input.trim() && !busy}
              onClick={() => send()}
              className="agent-chat-send"
            />
          </div>
          <Text type="secondary" className="agent-chat-hint">
            Enter to send · Shift+Enter for new line · Mic for voice
          </Text>
        </div>
      </footer>

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
            { label: 'Open full workspace', icon: <SettingOutlined />, go: () => nav(`/agents/${id}/manage`) },
            { label: 'Console', icon: <MenuOutlined />, go: () => nav('/console') },
            { label: 'Business CRM', icon: <AppstoreOutlined />, go: () => nav('/business') },
            { label: 'Live ops', icon: <ThunderboltOutlined />, go: () => nav('/ops') },
          ]}
          renderItem={(item) => (
            <List.Item
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
