import React, { useEffect, useRef, useState } from 'react'
import {
  Card, Select, Input, Button, Tag, Tabs, Space, Typography, message as antdMessage,
  List, Empty, Spin,
} from 'antd'
import { SendOutlined, ThunderboltOutlined, PlusOutlined, MessageOutlined } from '@ant-design/icons'
import { useLocation } from 'react-router-dom'
import { api, createRealtime } from '../api'
import ModelSelect from '../components/ModelSelect'
import VoiceControls, { speakText, stopSpeaking } from '../components/VoiceControls'
import MediaActions from '../components/MediaActions'
import PageShell from '../components/PageShell'
import { hapticMedium, hapticSuccess, hapticError } from '../native'

const TEMPLATES = ['Write a follow-up email', 'Summarise this for a customer', 'Draft a quote cover note', 'Reply to a bad review', 'Fix this Python bug', 'Write a FastAPI endpoint']

export default function Chat() {
  const loc = useLocation()
  const [model, setModel] = useState('vps-fast')
  const [mode, setMode] = useState('general')
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [sessionTokens, setSessionTokens] = useState(0)
  const [conversations, setConversations] = useState([])
  const [convLoading, setConvLoading] = useState(true)
  const [activeConv, setActiveConv] = useState(loc.state?.conversation_id || null)
  const [speakReplies, setSpeakReplies] = useState(
    () => localStorage.getItem('voice_speak_replies') === '1',
  )
  const convRef = useRef(loc.state?.conversation_id || null)
  const wsRef = useRef(null)
  const bottomRef = useRef(null)
  const speakRepliesRef = useRef(speakReplies)
  speakRepliesRef.current = speakReplies

  const loadConversations = () => {
    setConvLoading(true)
    api('/conversations')
      .then((data) => {
        const list = Array.isArray(data) ? data : (data.conversations || data.items || [])
        setConversations(list)
      })
      .catch(() => setConversations([]))
      .finally(() => setConvLoading(false))
  }

  const loadConversation = async (id) => {
    if (!id) return
    try {
      const msgs = await api(`/conversations/${id}/messages`)
      setMessages(Array.isArray(msgs) ? msgs : (msgs.messages || []))
      convRef.current = id
      setActiveConv(id)
    } catch (e) {
      antdMessage.error(e.message || 'Could not load conversation')
    }
  }

  const newChat = () => {
    convRef.current = null
    setActiveConv(null)
    setMessages([])
    setSessionTokens(0)
  }

  useEffect(() => {
    loadConversations()
    if (convRef.current) {
      loadConversation(convRef.current)
    }
    const ws = createRealtime({ path: '/ws/chat' })
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data)
      if (m.type === 'auth_ok') return
      if (m.type === 'conversation') {
        convRef.current = m.conversation_id
        setActiveConv(m.conversation_id)
        loadConversations()
      }
      if (m.type === 'error') {
        setBusy(false)
        antdMessage.error(m.content || 'Chat error')
        setMessages(prev => prev.filter(x => !(x.role === 'assistant' && x.streaming && !x.content)))
      }
      if (m.type === 'chunk') {
        setMessages(prev => {
          const next = [...prev]
          const last = next[next.length - 1]
          if (last?.role === 'assistant' && last.streaming) last.content += m.content
          else next.push({ role: 'assistant', content: m.content, streaming: true })
          return next
        })
      }
      if (m.type === 'done') {
        setBusy(false)
        setSessionTokens(t => t + m.tokens)
        setMessages(prev => {
          const next = prev.map(x => ({ ...x, streaming: false }))
          if (speakRepliesRef.current) {
            const last = [...next].reverse().find(x => x.role === 'assistant' && x.content)
            if (last?.content) speakText(last.content)
          }
          return next
        })
        loadConversations()
      }
    }
    ws.onerror = () => antdMessage.warning('Live chat unavailable — will use REST fallback when you send.')
    wsRef.current = ws
    return () => {
      ws.close()
      stopSpeaking()
    }
  }, [])

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const send = async (text) => {
    const msg = (text ?? input).trim()
    if (!msg) return
    if (busy) {
      setInput(msg)
      antdMessage.info('Still generating a reply — your speech is in the box. Tap Send when ready.')
      return
    }
    hapticMedium()
    setMessages(prev => [...prev, { role: 'user', content: msg }])
    setInput('')
    setBusy(true)
    if (wsRef.current?.readyState === 1) {
      wsRef.current.send(JSON.stringify({ message: msg, model, mode, conversation_id: convRef.current }))
      return
    }
    try {
      const r = await api('/conversations/messages', {
        method: 'POST',
        body: { message: msg, model, mode, conversation_id: convRef.current },
      })
      convRef.current = r.conversation_id
      setActiveConv(r.conversation_id)
      setMessages(prev => [...prev, { role: 'assistant', content: r.reply }])
      setSessionTokens(t => t + (r.tokens || 0))
      hapticSuccess()
      if (speakRepliesRef.current && r.reply) speakText(r.reply)
      loadConversations()
    } catch (e) {
      hapticError()
      antdMessage.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <PageShell wide className="aba-chat-page">
      <div
        style={{
          display: 'flex',
          gap: 12,
          height: 'calc(100vh - 160px)',
          minHeight: 480,
          width: '100%',
        }}
      >
        <Card
          size="small"
          className="aba-soft-card"
          title="Conversations"
          extra={
            <Button type="link" size="small" icon={<PlusOutlined />} onClick={newChat}>
              New chat
            </Button>
          }
          style={{ width: 260, flexShrink: 0, display: 'flex', flexDirection: 'column' }}
          styles={{ body: { flex: 1, overflow: 'auto', padding: 0 } }}
        >
          {convLoading ? (
            <div style={{ textAlign: 'center', padding: 24 }}><Spin size="small" /></div>
          ) : conversations.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No chats yet" style={{ padding: 16 }} />
          ) : (
            <List
              size="small"
              dataSource={conversations}
              renderItem={(c) => {
                const id = c.id
                const selected = activeConv === id
                return (
                  <List.Item
                    style={{
                      cursor: 'pointer',
                      padding: '8px 12px',
                      background: selected ? '#e6f4ff' : undefined,
                      borderLeft: selected ? '3px solid #1668dc' : '3px solid transparent',
                    }}
                    onClick={() => loadConversation(id)}
                  >
                    <List.Item.Meta
                      avatar={<MessageOutlined style={{ color: selected ? '#1668dc' : undefined }} />}
                      title={
                        <Typography.Text ellipsis style={{ maxWidth: 180, fontWeight: selected ? 600 : 400 }}>
                          {c.title || c.preview || 'Conversation'}
                        </Typography.Text>
                      }
                      description={
                        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                          {c.updated_at || c.created_at
                            ? new Date(c.updated_at || c.created_at).toLocaleString()
                            : null}
                        </Typography.Text>
                      }
                    />
                  </List.Item>
                )
              }}
            />
          )}
        </Card>

        <Card
          className="aba-soft-card"
          style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}
          styles={{ body: { display: 'flex', flexDirection: 'column', flex: 1, height: '100%', overflow: 'hidden' } }}
          title={
            <Space wrap>
              <ModelSelect value={model} onChange={setModel} style={{ width: 300 }} />
              <Tabs activeKey={mode} onChange={setMode} items={[
                { key: 'general', label: 'General' },
                { key: 'sales', label: 'Sales Mode' },
                { key: 'support', label: 'Customer Service' },
                { key: 'coding', label: 'Coding' },
              ]} tabBarStyle={{ margin: 0 }} />
            </Space>
          }
          extra={
            <Space wrap>
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
              <MediaActions
                disabled={busy}
                onUsage={(u) => {
                  if (u?.tokens) setSessionTokens((n) => n + (u.tokens || 0))
                }}
              />
              <Button size="small" icon={<PlusOutlined />} onClick={newChat}>New chat</Button>
              <Tag icon={<ThunderboltOutlined />} color="processing">{sessionTokens.toLocaleString()} tokens this session</Tag>
            </Space>
          }
        >
          <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
            {messages.length === 0 && (
              <div style={{ textAlign: 'center', marginTop: 48 }}>
                <Typography.Text type="secondary">Ask anything, use the mic, or start from a template:</Typography.Text>
                <div style={{ marginTop: 12 }}>
                  <Space wrap>{TEMPLATES.map(t => <Button key={t} size="small" onClick={() => send(t)}>{t}</Button>)}</Space>
                </div>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start', marginBottom: 8 }}>
                <div style={{
                  maxWidth: '70%', padding: '8px 14px', borderRadius: 10, whiteSpace: 'pre-wrap',
                  background: m.role === 'user' ? '#1668dc' : '#fff',
                  color: m.role === 'user' ? '#fff' : '#000',
                  border: m.role === 'user' ? 'none' : '1px solid #e8e8e8',
                  fontFamily: mode === 'coding' && m.role === 'assistant' ? 'ui-monospace, monospace' : undefined,
                }}>{m.content}</div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
          <Space.Compact style={{ width: '100%' }}>
            <Input value={input} onChange={e => setInput(e.target.value)} onPressEnter={() => send()}
                   placeholder="Type a message or click the mic to talk…" disabled={busy} />
            <Button type="primary" icon={<SendOutlined />} onClick={() => send()} loading={busy}>Send</Button>
          </Space.Compact>
        </Card>
      </div>
    </PageShell>
  )
}
