import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Card, Button, Space, Typography, Tag, Input, List, Empty, Spin, message,
  Avatar, Modal, Form, Select, Alert, Popconfirm, Switch, Tooltip,
} from 'antd'
import {
  ArrowLeftOutlined, SendOutlined, ReloadOutlined, CommentOutlined,
  RobotOutlined, UserOutlined, TeamOutlined, StopOutlined, PlusOutlined,
  ThunderboltOutlined, FileSearchOutlined, FileTextOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/PageHeader'
import PageShell from '../components/PageShell'

const { Text, Paragraph } = Typography
const { TextArea } = Input


const STATUS_COLOR = {
  open: 'blue',
  active: 'green',
  closed: 'default',
}

function senderIcon(kind) {
  if (kind === 'agent') return <RobotOutlined />
  if (kind === 'human') return <TeamOutlined />
  if (kind === 'system') return <CommentOutlined />
  return <UserOutlined />
}

function senderColor(kind) {
  if (kind === 'agent') return '#1668dc'
  if (kind === 'human') return '#722ed1'
  if (kind === 'system') return '#8c8c8c'
  return '#52c41a'
}

function senderLabel(m, participants) {
  if (!m || typeof m !== 'object') return 'Unknown'
  if (m.sender_name) return m.sender_name
  if (m.sender_kind === 'agent' && m.sender_agent_id) {
    const p = (participants || []).find(
      (x) => x && x.kind === 'agent' && x.agent_id === m.sender_agent_id,
    )
    if (p?.name) return p.name
    return `Agent #${m.sender_agent_id}`
  }
  if (m.sender_kind === 'human' && m.sender_human_id) {
    const p = (participants || []).find(
      (x) => x && x.kind === 'human' && x.human_id === m.sender_human_id,
    )
    if (p?.name) return p.name
    return `Human #${m.sender_human_id}`
  }
  if (m.sender_kind === 'system') return 'System'
  if (m.sender_kind === 'user') {
    const p = (participants || []).find((x) => x && x.kind === 'user')
    return p?.name || 'You'
  }
  return m.sender_kind || 'user'
}

function parseRoomId(raw) {
  const n = Number(raw)
  if (!raw || Number.isNaN(n) || n <= 0 || !Number.isFinite(n)) return null
  return Math.floor(n)
}

function normalizeAgents(data) {
  if (Array.isArray(data)) return data
  if (Array.isArray(data?.agents)) return data.agents
  if (Array.isArray(data?.items)) return data.items
  return []
}

function normalizeMessages(raw) {
  let list = []
  if (Array.isArray(raw)) list = raw
  else if (Array.isArray(raw?.messages)) list = raw.messages
  else if (Array.isArray(raw?.items)) list = raw.items
  return list.filter((m) => m && typeof m === 'object')
}

function formatWhen(v) {
  if (!v) return ''
  try {
    const d = new Date(v)
    if (Number.isNaN(d.getTime())) return ''
    return d.toLocaleString()
  } catch {
    return ''
  }
}

function messageKey(m, index) {
  if (m?.id != null) return String(m.id)
  const snippet = typeof m?.content === 'string' ? m.content.slice(0, 24) : ''
  return `msg-${index}-${m?.created_at || ''}-${snippet}`
}

/** Shared empty-state body padding for full-height Card placeholders */
const emptyCardBody = {
  minHeight: 240,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
}

export default function MeetingRoom() {
  const { id: rawId } = useParams()
  const id = parseRoomId(rawId)
  const nav = useNavigate()
  const [room, setRoom] = useState(null)
  const [messages, setMessages] = useState([])
  const [participants, setParticipants] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [closing, setClosing] = useState(false)
  const [roundBusy, setRoundBusy] = useState(false)
  const [extractBusy, setExtractBusy] = useState(false)
  const [summarizeBusy, setSummarizeBusy] = useState(false)
  const [taskOpen, setTaskOpen] = useState(false)
  const [taskSaving, setTaskSaving] = useState(false)
  const [agents, setAgents] = useState([])
  const [taskForm] = Form.useForm()
  const bottomRef = useRef(null)
  const skipScrollRef = useRef(false)
  const listRef = useRef(null)

  const applyRoomPayload = (data) => {
    if (!data || typeof data !== 'object') return
    // Prefer nested meeting if API wraps it
    const payload = data.meeting && typeof data.meeting === 'object' ? { ...data, ...data.meeting } : data
    setRoom((prev) => {
      const next = { ...(prev || {}), ...payload }
      // Do not wipe local messages via null from endpoints that omit them
      if (payload.messages === null || payload.messages === undefined) {
        delete next.messages
      }
      return next
    })
    if (Array.isArray(payload.participants)) {
      setParticipants(payload.participants.filter((p) => p && typeof p === 'object'))
    }
    if (Array.isArray(payload.messages)) {
      setMessages(normalizeMessages(payload.messages))
    }
  }

  const load = useCallback(async (opts = {}) => {
    const quiet = Boolean(opts.quiet)
    if (id == null) {
      setLoading(false)
      setRoom(null)
      setError('Invalid meeting id')
      return
    }
    if (!quiet) setLoading(true)
    else setRefreshing(true)
    setError(null)
    try {
      const data = await api(`/meetings/${id}`)
      applyRoomPayload(data)
      if (!Array.isArray(data?.messages)) {
        try {
          const thread = await api(`/meetings/${id}/messages`)
          setMessages(normalizeMessages(thread))
        } catch {
          // Keep existing thread on quiet refresh if secondary fetch fails
          if (!quiet) setMessages([])
        }
      }
    } catch (e) {
      const msg = e?.message || 'Failed to load meeting'
      setError(msg)
      if (!quiet) {
        setRoom(null)
        setMessages([])
        setParticipants([])
      }
      message.error(msg)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [id])

  useEffect(() => {
    load()
    api('/agents/')
      .then((a) => setAgents(normalizeAgents(a).filter((x) => x && x.id != null)))
      .catch(() => setAgents([]))
  }, [load])

  useEffect(() => {
    if (skipScrollRef.current) {
      skipScrollRef.current = false
      return
    }
    requestAnimationFrame(() => {
      try {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
      } catch {
        /* ignore scroll errors */
      }
    })
  }, [messages.length])

  // Ant Design TextArea — never touch .style (breaks with autoSize / ref wrappers)
  const onInputChange = (e) => {
    const v = e?.target?.value
    setInput(typeof v === 'string' ? v : String(v ?? ''))
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const agentParticipants = useMemo(
    () => participants.filter((p) => p && p.kind === 'agent' && p.agent_id != null),
    [participants],
  )
  const hasAgents = agentParticipants.length > 0 || Boolean(room?.chair_agent_id)
  const chatMessages = useMemo(
    () => messages.filter((m) => m && typeof m === 'object'),
    [messages],
  )
  const hasTranscript = chatMessages.length > 0 || Boolean((room?.summary_text || '').trim())

  const send = async () => {
    const content = input.trim()
    if (!content || sending || id == null) return
    if (room?.status === 'closed') {
      message.warning('Meeting is closed')
      return
    }
    setSending(true)
    try {
      const msg = await api(`/meetings/${id}/messages`, {
        method: 'POST',
        body: { content },
      })
      if (msg && typeof msg === 'object') {
        setMessages((prev) => {
          if (msg.id != null && prev.some((m) => m?.id === msg.id)) return prev
          return [...prev, msg]
        })
      }
      setInput('')
      if (room?.status === 'open') {
        setRoom((r) => (r ? { ...r, status: 'active' } : r))
      }
    } catch (e) {
      message.error(e?.message || 'Failed to send')
    } finally {
      setSending(false)
    }
  }

  const closeRoom = async () => {
    if (id == null || closing) return
    setClosing(true)
    try {
      const updated = await api(`/meetings/${id}/close`, { method: 'POST' })
      const next = updated?.meeting || updated
      if (next && typeof next === 'object') {
        setRoom((prev) => {
          const merged = { ...(prev || {}), ...next }
          delete merged.messages
          return merged
        })
        if (Array.isArray(next.participants)) {
          setParticipants(next.participants.filter((p) => p && typeof p === 'object'))
        }
      }
      message.success(updated?.already_closed ? 'Meeting already closed' : 'Meeting closed')
      skipScrollRef.current = true
      await load({ quiet: true })
    } catch (e) {
      message.error(e?.message || 'Failed to close')
    } finally {
      setClosing(false)
    }
  }

  /** POST /meetings/:id/round — multi-agent discussion turn */
  const runRound = async () => {
    if (id == null || roundBusy || room?.status === 'closed') return
    if (!hasAgents) {
      message.warning('Add an agent participant before running a round')
      return
    }
    setRoundBusy(true)
    try {
      const res = await api(`/meetings/${id}/round`, {
        method: 'POST',
        body: { prompt: '', max_turns: 1 },
      })
      if (res?.meeting) {
        applyRoomPayload(res.meeting)
      }
      const newMsgs = normalizeMessages(res?.messages)
      if (newMsgs.length) {
        setMessages((prev) => {
          const ids = new Set(prev.map((m) => m?.id).filter((x) => x != null))
          const added = newMsgs.filter((m) => m.id == null || !ids.has(m.id))
          if (!added.length && Array.isArray(res.meeting?.messages)) {
            return normalizeMessages(res.meeting.messages)
          }
          return added.length ? [...prev, ...added] : prev
        })
      } else if (!res?.meeting) {
        skipScrollRef.current = true
        await load({ quiet: true })
      }
      const n = res?.count ?? newMsgs.length
      message.success(n ? `Round complete · ${n} new message${n === 1 ? '' : 's'}` : 'Round complete')
      if (room?.status === 'open') {
        setRoom((r) => (r ? { ...r, status: 'active' } : r))
      }
    } catch (e) {
      message.error(e?.message || 'Failed to run round')
    } finally {
      setRoundBusy(false)
    }
  }

  /** POST /meetings/:id/extract-tasks — create tasks from transcript */
  const extractTasks = async () => {
    if (id == null || extractBusy) return
    if (!hasTranscript) {
      message.info('Send a few messages first, then extract action items')
      return
    }
    setExtractBusy(true)
    try {
      const res = await api(`/meetings/${id}/extract-tasks`, {
        method: 'POST',
        body: { create: true, assign_to_chair: true },
      })
      const n = res?.count ?? (Array.isArray(res?.tasks) ? res.tasks.length : 0)
      if (n === 0) {
        message.info('No action items found to extract')
      } else {
        message.success(
          `Extracted ${n} task${n === 1 ? '' : 's'}${res?.source ? ` (${res.source})` : ''}`,
        )
      }
      skipScrollRef.current = true
      await load({ quiet: true })
    } catch (e) {
      message.error(e?.message || 'Failed to extract tasks')
    } finally {
      setExtractBusy(false)
    }
  }

  /** POST /meetings/:id/summarize — LLM summary → summary_text */
  const summarize = async () => {
    if (id == null || summarizeBusy) return
    if (chatMessages.length === 0) {
      message.info('No messages to summarize yet')
      return
    }
    setSummarizeBusy(true)
    try {
      const res = await api(`/meetings/${id}/summarize`, {
        method: 'POST',
        body: { style: 'concise', model: 'fast' },
      })
      const summary = (res?.summary || res?.meeting?.summary_text || '').trim()
      if (summary) {
        setRoom((r) => (r ? { ...r, summary_text: summary } : r))
      }
      if (res?.meeting) {
        applyRoomPayload(res.meeting)
      }
      message.success('Summary updated')
      skipScrollRef.current = true
      await load({ quiet: true })
    } catch (e) {
      message.error(e?.message || 'Failed to summarize')
    } finally {
      setSummarizeBusy(false)
    }
  }

  const createTask = async (values) => {
    if (id == null) return
    const agentId = values.agent_id
    if (!agentId) {
      message.error('Pick an agent to assign the task')
      return
    }
    setTaskSaving(true)
    try {
      const title = (values.title || '').trim()
      const description = (values.description || '').trim() || title
      const body = {
        title,
        description,
        priority: values.priority || 'medium',
        run_now: Boolean(values.run_now),
        labels: 'meeting',
      }
      if (room?.project_id) body.project_id = room.project_id

      // Agent tasks API — there is no POST /meetings/:id/tasks
      const task = await api(`/agents/${agentId}/tasks`, {
        method: 'POST',
        body,
      })

      try {
        const note = await api(`/meetings/${id}/messages`, {
          method: 'POST',
          body: {
            content: `Task created: ${title}${task?.id ? ` (#${task.id})` : ''}`,
            msg_type: 'task_created',
            meta: { task_id: task?.id, agent_id: agentId },
          },
        })
        if (note && typeof note === 'object') {
          setMessages((prev) => (
            note.id != null && prev.some((m) => m?.id === note.id)
              ? prev
              : [...prev, note]
          ))
        }
      } catch {
        /* non-fatal if room is closed or message fails */
      }

      message.success(`Task created: ${task?.title || title}`)
      setTaskOpen(false)
      taskForm.resetFields()
    } catch (e) {
      message.error(e?.message || 'Failed to create task')
    } finally {
      setTaskSaving(false)
    }
  }

  if (id == null) {
    return (
      <PageShell>
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Card className="aba-soft-card" styles={{ body: { paddingBlock: 16 } }}>
            <PageHeader
              title="Meeting"
              subtitle="Invalid room link"
              style={{ marginBottom: 0 }}
              extra={(
                <Button icon={<ArrowLeftOutlined />} onClick={() => nav('/meetings')}>
                  Back
                </Button>
              )}
            />
          </Card>
          <Card className="aba-soft-card" styles={{ body: emptyCardBody }}>
            <Empty
              style={{ width: '100%', marginBlock: 0 }}
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={`Invalid meeting id “${rawId}”`}
            >
              <Button type="primary" onClick={() => nav('/meetings')}>All meetings</Button>
            </Empty>
          </Card>
        </Space>
      </PageShell>
    )
  }

  if (loading && !room) {
    return (
      <PageShell>
        <Card className="aba-soft-card" styles={{ body: emptyCardBody }}>
          <div style={{ textAlign: 'center', padding: 48, width: '100%' }}>
            <Spin size="large" tip="Loading meeting…" />
          </div>
        </Card>
      </PageShell>
    )
  }

  if (!room) {
    return (
      <PageShell>
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Card className="aba-soft-card" styles={{ body: { paddingBlock: 16 } }}>
            <PageHeader
              title="Meeting"
              subtitle={error ? 'Could not load this room' : 'Room not found'}
              style={{ marginBottom: 0 }}
              extra={(
                <Button icon={<ArrowLeftOutlined />} onClick={() => nav('/meetings')}>
                  Back
                </Button>
              )}
            />
          </Card>
          <Card className="aba-soft-card" styles={{ body: emptyCardBody }}>
            {error ? (
              <Empty
                style={{ width: '100%', marginBlock: 0 }}
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={(
                  <span>
                    Could not load meeting
                    <br />
                    <Text type="secondary">{error}</Text>
                  </span>
                )}
              >
                <Space>
                  <Button onClick={() => load()}>Retry</Button>
                  <Button type="primary" onClick={() => nav('/meetings')}>All meetings</Button>
                </Space>
              </Empty>
            ) : (
              <Empty
                style={{ width: '100%', marginBlock: 0 }}
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={`Meeting #${id} not found`}
              >
                <Button type="primary" onClick={() => nav('/meetings')}>All meetings</Button>
              </Empty>
            )}
          </Card>
        </Space>
      </PageShell>
    )
  }

  const title = room.title || `Meeting #${room.id || id}`
  const status = (room.status || 'open').toLowerCase()
  const roomType = (room.room_type || 'brainstorm').replace(/_/g, ' ')
  const closed = status === 'closed'
  const summary = (room.summary_text || '').trim()
  const busy = sending || roundBusy || extractBusy || summarizeBusy || closing

  const emptyDescription = closed
    ? 'No messages in this closed meeting'
    : !hasAgents
      ? 'No messages yet — invite agents from Agents, then run a round or send a note'
      : 'No messages yet — send a note or run a round so agents can discuss'

  return (
    <PageShell>
      <Space direction="vertical" size={12} style={{ width: '100%', flex: 1 }}>
        {/* Header — boxed Card */}
        <Card className="aba-soft-card" styles={{ body: { paddingBlock: 16 } }}>
          <PageHeader
            title={title}
            subtitle={room.purpose || roomType}
            style={{ marginBottom: 0 }}
            extra={(
              <Space wrap>
                <Tag color={STATUS_COLOR[status] || 'default'}>{status}</Tag>
                <Tag>{roomType}</Tag>
                {!closed && (
                  <Tooltip
                    title={
                      hasAgents
                        ? 'Let agent participants take a discussion turn'
                        : 'Add an agent participant first'
                    }
                  >
                    <Button
                      type="primary"
                      icon={<ThunderboltOutlined />}
                      loading={roundBusy}
                      disabled={(busy && !roundBusy) || !hasAgents}
                      onClick={runRound}
                    >
                      Run round
                    </Button>
                  </Tooltip>
                )}
                <Tooltip title={hasTranscript ? 'Create tasks from the transcript' : 'Need messages or a summary first'}>
                  <Button
                    icon={<FileSearchOutlined />}
                    loading={extractBusy}
                    disabled={(busy && !extractBusy) || !hasTranscript}
                    onClick={extractTasks}
                  >
                    Extract tasks
                  </Button>
                </Tooltip>
                <Tooltip title={chatMessages.length ? 'Generate an LLM summary of the thread' : 'Need messages first'}>
                  <Button
                    icon={<FileTextOutlined />}
                    loading={summarizeBusy}
                    disabled={(busy && !summarizeBusy) || chatMessages.length === 0}
                    onClick={summarize}
                  >
                    Summarize
                  </Button>
                </Tooltip>
                {!closed && (
                  <Button icon={<PlusOutlined />} onClick={() => setTaskOpen(true)}>
                    Create task
                  </Button>
                )}
                {!closed && (
                  <Popconfirm
                    title="Close this meeting?"
                    description="Participants will no longer be able to send messages."
                    okText="Close meeting"
                    okButtonProps={{ danger: true }}
                    onConfirm={closeRoom}
                  >
                    <Button danger icon={<StopOutlined />} loading={closing} disabled={busy && !closing}>
                      Close
                    </Button>
                  </Popconfirm>
                )}
                <Button
                  icon={<ReloadOutlined />}
                  onClick={() => load({ quiet: true })}
                  loading={refreshing}
                >
                  Refresh
                </Button>
                <Button icon={<ArrowLeftOutlined />} onClick={() => nav('/meetings')}>Back</Button>
              </Space>
            )}
          />
        </Card>

        {error && (
          <Card className="aba-soft-card" size="small">
            <Alert
              type="warning"
              showIcon
              closable
              message="Could not refresh meeting"
              description={error}
              action={<Button size="small" onClick={() => load({ quiet: true })}>Retry</Button>}
              onClose={() => setError(null)}
              style={{ marginBottom: 0 }}
            />
          </Card>
        )}

        {/* Participants Card */}
        <Card
          className="aba-soft-card"
          size="small"
          title={(
            <Space size={8}>
              <TeamOutlined />
              <span>In room</span>
              {participants.length > 0 && (
                <Tag style={{ marginInlineStart: 4 }}>{participants.length}</Tag>
              )}
            </Space>
          )}
          styles={participants.length === 0
            ? { body: { ...emptyCardBody, minHeight: 160 } }
            : undefined}
        >
          {participants.length > 0 ? (
            <Space wrap size={[8, 8]}>
              {participants.map((p, i) => (
                <Tag
                  key={p.id ?? `${p.kind}-${p.agent_id || p.human_id || p.user_id || i}`}
                  icon={senderIcon(p.kind)}
                  color={p.role === 'chair' ? 'gold' : undefined}
                >
                  {p.name || p.display_name || p.kind || 'Participant'}
                  {p.role === 'chair' ? ' · chair' : ''}
                </Tag>
              ))}
            </Space>
          ) : (
            <Empty
              style={{ width: '100%', marginBlock: 0 }}
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={(
                <span>
                  No participants listed for this room
                  <br />
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    Open Agents and start a meeting with agents, or create a new room with participants.
                  </Text>
                </span>
              )}
            >
              <Button size="small" onClick={() => nav('/console')}>Open Agents</Button>
            </Empty>
          )}
        </Card>

        {/* Summary Card — only when present */}
        {summary ? (
          <Card
            className="aba-soft-card"
            size="small"
            title={(
              <Space size={8}>
                <FileTextOutlined />
                <span>Summary</span>
              </Space>
            )}
          >
            <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{summary}</Paragraph>
          </Card>
        ) : null}

        {/* Linked task Card */}
        {room.task_id ? (
          <Card className="aba-soft-card" size="small" styles={{ body: { padding: 12 } }}>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 0 }}
              message={room.task_title ? `Linked task: ${room.task_title}` : `Linked task #${room.task_id}`}
              action={(
                <Button size="small" type="link" onClick={() => nav('/tasks')}>
                  Tasks board
                </Button>
              )}
            />
          </Card>
        ) : null}

        {/* Transcript — bordered Card; empty state lives inside */}
        <Card
          className="aba-soft-card"
          title={(
            <Space size={8}>
              <CommentOutlined />
              <span>Transcript</span>
              {chatMessages.length > 0 && (
                <Tag style={{ marginInlineStart: 4 }}>{chatMessages.length}</Tag>
              )}
            </Space>
          )}
          size="small"
          style={{ flex: 1, display: 'flex', flexDirection: 'column' }}
          styles={{
            body: {
              display: 'flex',
              flexDirection: 'column',
              flex: 1,
              padding: chatMessages.length === 0 ? 24 : 12,
              minHeight: 280,
              ...(chatMessages.length === 0
                ? { alignItems: 'center', justifyContent: 'center' }
                : null),
            },
          }}
        >
          {chatMessages.length === 0 ? (
            <Empty
              style={{
                width: '100%',
                marginBlock: 0,
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={emptyDescription}
            >
              {!closed && (
                <Space wrap>
                  <Button
                    type="primary"
                    icon={<ThunderboltOutlined />}
                    loading={roundBusy}
                    disabled={!hasAgents}
                    onClick={runRound}
                  >
                    Run round
                  </Button>
                  <Button icon={<PlusOutlined />} onClick={() => setTaskOpen(true)}>
                    Create task
                  </Button>
                </Space>
              )}
              {closed && (
                <Button type="primary" onClick={() => nav('/meetings')}>
                  All meetings
                </Button>
              )}
            </Empty>
          ) : (
            <div
              ref={listRef}
              style={{ flex: 1, overflowY: 'auto', maxHeight: 'min(60vh, 560px)' }}
            >
              <List
                dataSource={chatMessages}
                rowKey={(m, index) => messageKey(m, index)}
                locale={{
                  emptyText: (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No messages" />
                  ),
                }}
                renderItem={(m) => (
                  <List.Item style={{ border: 'none', padding: '8px 0', alignItems: 'flex-start' }}>
                    <List.Item.Meta
                      avatar={(
                        <Avatar
                          size={32}
                          icon={senderIcon(m.sender_kind)}
                          style={{ background: senderColor(m.sender_kind) }}
                        />
                      )}
                      title={(
                        <Space size={8} wrap>
                          <Text strong>
                            {senderLabel(m, participants)}
                          </Text>
                          {m.msg_type && m.msg_type !== 'chat' && (
                            <Tag color="gold">{String(m.msg_type).replace(/_/g, ' ')}</Tag>
                          )}
                          <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                            {formatWhen(m.created_at)}
                          </Text>
                        </Space>
                      )}
                      description={(
                        <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                          {typeof m.content === 'string' ? m.content : (m.content != null ? String(m.content) : '')}
                        </Paragraph>
                      )}
                    />
                  </List.Item>
                )}
              />
              <div ref={bottomRef} />
            </div>
          )}
          {chatMessages.length === 0 && <div ref={bottomRef} />}
        </Card>

        {/* Composer — separate bordered Card */}
        <Card
          className="aba-soft-card"
          size="small"
          title={closed ? (
            <Space size={8}>
              <StopOutlined />
              <span>Meeting closed</span>
            </Space>
          ) : (
            <Space size={8}>
              <SendOutlined />
              <span>Message the room</span>
            </Space>
          )}
          styles={{ body: { padding: closed ? 16 : '12px 16px' } }}
        >
          {closed ? (
            <Alert
              type="info"
              showIcon
              message="This meeting is closed"
              description="You can still review the transcript, summarize, and extract tasks. Open a new meeting to continue the discussion."
              action={(
                <Space wrap>
                  <Button
                    size="small"
                    icon={<FileTextOutlined />}
                    loading={summarizeBusy}
                    disabled={!chatMessages.length}
                    onClick={summarize}
                  >
                    Summarize
                  </Button>
                  <Button
                    size="small"
                    icon={<FileSearchOutlined />}
                    loading={extractBusy}
                    disabled={!hasTranscript}
                    onClick={extractTasks}
                  >
                    Extract tasks
                  </Button>
                  <Button size="small" type="primary" onClick={() => nav('/meetings')}>
                    All meetings
                  </Button>
                </Space>
              )}
              style={{ marginBottom: 0 }}
            />
          ) : (
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', width: '100%' }}>
              <TextArea
                value={input}
                onChange={onInputChange}
                onKeyDown={onKeyDown}
                placeholder="Message the room… (Enter to send, Shift+Enter for newline)"
                autoSize={{ minRows: 1, maxRows: 4 }}
                disabled={sending}
                style={{ flex: 1 }}
              />
              <Button
                type="primary"
                icon={<SendOutlined />}
                loading={sending}
                disabled={!input.trim() || busy}
                onClick={send}
              >
                Send
              </Button>
            </div>
          )}
        </Card>
      </Space>

      <Modal
        title="Create task from meeting"
        open={taskOpen}
        onCancel={() => { setTaskOpen(false); taskForm.resetFields() }}
        onOk={() => taskForm.submit()}
        confirmLoading={taskSaving}
        destroyOnClose
        okText="Create task"
        okButtonProps={{ disabled: agents.length === 0 }}
      >
        <Form
          form={taskForm}
          layout="vertical"
          onFinish={createTask}
          initialValues={{ priority: 'medium', run_now: false }}
        >
          <Form.Item
            name="title"
            label="Title"
            rules={[
              { required: true, message: 'Title required' },
              { whitespace: true, message: 'Title required' },
            ]}
          >
            <Input placeholder="Task title" maxLength={240} showCount />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <TextArea rows={3} placeholder="Optional details" maxLength={4000} />
          </Form.Item>
          <Form.Item
            name="agent_id"
            label="Assign agent"
            rules={[{ required: true, message: 'Pick an agent' }]}
            extra={agents.length === 0 ? 'No agents available — create one under Agents first.' : undefined}
          >
            <Select
              showSearch
              optionFilterProp="label"
              placeholder={agents.length ? 'Required' : 'No agents available'}
              disabled={!agents.length}
              options={agents.map((a) => ({
                value: a.id,
                label: `${a.name || `Agent #${a.id}`}${a.role ? ` · ${a.role}` : ''}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="priority" label="Priority">
            <Select
              options={[
                { value: 'low', label: 'Low' },
                { value: 'medium', label: 'Medium' },
                { value: 'high', label: 'High' },
                { value: 'urgent', label: 'Urgent' },
              ]}
            />
          </Form.Item>
          <Form.Item name="run_now" label="Run immediately" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </PageShell>
  )
}
