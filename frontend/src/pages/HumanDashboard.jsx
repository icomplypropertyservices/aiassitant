import React, { useCallback, useEffect, useState } from 'react'
import {
  Alert, Badge, Button, Card, Col, Empty, Input, List, Row, Space, Statistic, Tag, Typography, message,
} from 'antd'
import {
  BellOutlined, CheckOutlined, MessageOutlined, ReloadOutlined, RobotOutlined,
  SendOutlined, TeamOutlined, UserOutlined, CheckSquareOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/PageHeader'
import PageShell from '../components/PageShell'

const { Text, Paragraph, Title } = Typography
const { TextArea } = Input

function fmtWhen(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return String(iso)
    return d.toLocaleString()
  } catch {
    return String(iso)
  }
}

function roleTag(role) {
  const r = (role || '').toLowerCase()
  if (r === 'agent') return <Tag color="blue" icon={<RobotOutlined />}>Agent</Tag>
  if (r === 'system') return <Tag>System</Tag>
  if (r === 'owner') return <Tag color="gold" icon={<UserOutlined />}>You</Tag>
  if (r === 'human') return <Tag color="purple">Human</Tag>
  return <Tag>{role || '—'}</Tag>
}

/**
 * Load human desk using new APIs when deployed, else fall back to /humans/ + messages
 * (production may still route /inbox|/dashboard to /{human_id} until backend is redeployed).
 */
async function loadHumanDesk() {
  const longGet = { timeoutMs: 90000 }
  // Prefer dedicated dashboard
  try {
    const d = await api('/humans/dashboard', longGet)
    if (d && d.ok !== false && d.my_human && !d.detail) {
      let messages = d.recent_messages || []
      try {
        const ib = await api('/humans/inbox?limit=80', longGet)
        if (ib?.messages) messages = ib.messages
      } catch {
        /* keep dashboard recent_messages */
      }
      return {
        dash: d,
        inbox: messages,
        source: 'dashboard',
      }
    }
  } catch {
    /* fall through */
  }

  // Fallback: classic team APIs (always on production)
  const h = await api('/humans/', longGet)
  const my = h?.my_human || (h?.humans || []).find((x) => x.is_my_human) || null
  let messages = []
  if (my?.id) {
    try {
      const r = await api(`/humans/${my.id}/messages`, longGet)
      messages = (r?.messages || []).slice().reverse()
    } catch {
      messages = []
    }
  }
  let openTasks = []
  try {
    const board = await api('/agents/tasks/board', longGet)
    const cols = board?.columns || {}
    for (const st of ['todo', 'queued', 'in_progress', 'review']) {
      for (const t of cols[st] || []) {
        if (t.human_id || String(t.assignee_type || '') === 'human') {
          openTasks.push({ ...t, status: t.status || st })
        }
      }
    }
  } catch {
    openTasks = []
  }
  const unread = my?.unread_messages || messages.filter((m) => m.unread || !m.read_at).length
  return {
    dash: {
      ok: true,
      my_human: my,
      unread_count: unread,
      recent_messages: messages,
      open_human_tasks: openTasks,
      team: h?.humans || [],
      stats: {
        team_size: (h?.humans || []).length,
        unread,
        open_tasks: openTasks.length,
        messages: messages.length,
      },
    },
    inbox: messages,
    source: 'fallback',
  }
}

/**
 * Human Dashboard — inbox for notifications + messages from agents.
 */
export default function HumanDashboard() {
  const nav = useNavigate()
  const [loading, setLoading] = useState(true)
  const [dash, setDash] = useState(null)
  const [inbox, setInbox] = useState([])
  const [reply, setReply] = useState('')
  const [sending, setSending] = useState(false)
  const [source, setSource] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await loadHumanDesk()
      setDash(r.dash)
      setInbox(r.inbox || [])
      setSource(r.source || '')
    } catch (e) {
      message.error(e.message || 'Failed to load human dashboard')
      setDash(null)
      setInbox([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    const t = setInterval(() => { load() }, 20000)
    return () => clearInterval(t)
  }, [load])

  const markAllRead = async () => {
    try {
      await api('/humans/inbox/mark-read', { method: 'POST', timeoutMs: 30000 })
      message.success('Marked read')
      load()
    } catch {
      // Fallback: opening messages marks read on classic API
      const id = dash?.my_human?.id
      if (id) {
        try {
          await api(`/humans/${id}/messages`, { timeoutMs: 60000 })
          message.success('Marked read')
          load()
          return
        } catch (e2) {
          message.error(e2.message)
          return
        }
      }
      message.info('Open a message thread on Team to mark read')
    }
  }

  const sendReply = async () => {
    const text = reply.trim()
    if (!text) return
    const humanId = dash?.my_human?.id
    if (!humanId) {
      message.error('No My Human profile yet — open Team admin once')
      return
    }
    setSending(true)
    try {
      await api(`/humans/${humanId}/messages`, {
        method: 'POST',
        body: { content: text, kind: 'message' },
        timeoutMs: 60000,
      })
      setReply('')
      message.success('Message posted')
      load()
    } catch (e) {
      message.error(e.message)
    } finally {
      setSending(false)
    }
  }

  const my = dash?.my_human
  const stats = dash?.stats || {}
  const unread = Number(stats.unread ?? dash?.unread_count ?? 0) || 0
  const tasks = Array.isArray(dash?.open_human_tasks) ? dash.open_human_tasks : []
  const safeInbox = Array.isArray(inbox) ? inbox : []

  if (!loading && !dash && !safeInbox.length) {
    return (
      <PageShell>
        <PageHeader title="Human Dashboard" subtitle="Inbox for agent messages" />
        <Alert
          type="error"
          showIcon
          message="Could not load human dashboard"
          description="Session may have expired or the API is still starting. Open Team admin or retry."
          action={(
            <Space>
              <Button size="small" type="primary" onClick={load}>Retry</Button>
              <Button size="small" onClick={() => nav('/humans')}>Team</Button>
            </Space>
          )}
        />
      </PageShell>
    )
  }

  return (
    <PageShell>
      <PageHeader
        title={(
          <span>
            <UserOutlined style={{ marginRight: 8 }} />
            Human Dashboard
            {unread > 0 ? (
              <Badge count={unread} style={{ marginLeft: 10 }} />
            ) : null}
          </span>
        )}
        subtitle="Your inbox for agent notifications, status updates, and human messages"
        extra={(
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
              Refresh
            </Button>
            <Button icon={<CheckOutlined />} onClick={markAllRead} disabled={!unread && !safeInbox.length}>
              Mark all read
            </Button>
            <Button icon={<TeamOutlined />} onClick={() => nav('/humans')}>
              Team admin
            </Button>
            <Button type="primary" icon={<CheckSquareOutlined />} onClick={() => nav('/tasks')}>
              Tasks
            </Button>
          </Space>
        )}
      />

      {source === 'fallback' && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="Using classic team inbox"
          description="Full /humans/dashboard API will light up after the next backend deploy. Messages still load from your My Human message box."
        />
      )}

      {!my?.email && my && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="Add your email on Team admin so SMS/email notifies also work"
          action={(
            <Button size="small" onClick={() => nav('/humans')}>
              Open Team
            </Button>
          )}
        />
      )}

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="Unread" value={unread} prefix={<BellOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="Inbox items" value={stats.messages ?? inbox.length} prefix={<MessageOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="Open human tasks" value={stats.open_tasks ?? tasks.length} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="Team size" value={stats.team_size ?? 0} prefix={<TeamOutlined />} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card
            title={(
              <Space>
                <BellOutlined />
                Notifications &amp; messages
                {unread > 0 && <Badge count={unread} />}
              </Space>
            )}
            loading={loading && !safeInbox.length}
            extra={<Text type="secondary">Agent updates appear here</Text>}
          >
            {safeInbox.length === 0 && !loading ? (
              <Empty description="No messages yet. When agents run status_update or notify_human, they appear here." />
            ) : (
              <List
                itemLayout="vertical"
                dataSource={safeInbox}
                renderItem={(m) => (
                  <List.Item
                    key={m.id}
                    style={{
                      background: (m.unread || !m.read_at) && m.sender_role !== 'owner'
                        ? 'rgba(22,104,220,0.06)'
                        : undefined,
                      borderRadius: 8,
                      padding: '10px 12px',
                      marginBottom: 8,
                    }}
                  >
                    <Space wrap size={6} style={{ marginBottom: 6 }}>
                      {roleTag(m.sender_role)}
                      {m.sender_agent_name && (
                        <Tag color="processing">{m.sender_agent_name}</Tag>
                      )}
                      {m.kind && m.kind !== 'message' && <Tag>{m.kind}</Tag>}
                      {(m.unread || (!m.read_at && m.sender_role !== 'owner')) && (
                        <Tag color="red">Unread</Tag>
                      )}
                      <Text type="secondary" style={{ fontSize: 12 }}>{fmtWhen(m.created_at)}</Text>
                    </Space>
                    <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                      {m.content}
                    </Paragraph>
                    {m.task_id ? (
                      <Button
                        type="link"
                        size="small"
                        style={{ paddingLeft: 0, marginTop: 4 }}
                        onClick={() => nav('/tasks')}
                      >
                        Related task #{m.task_id}
                      </Button>
                    ) : null}
                  </List.Item>
                )}
              />
            )}

            <Card size="small" type="inner" title="Reply as you (owner)" style={{ marginTop: 12 }}>
              <TextArea
                rows={3}
                value={reply}
                onChange={(e) => setReply(e.target.value)}
                placeholder="Write a note into your human inbox…"
              />
              <Button
                type="primary"
                icon={<SendOutlined />}
                loading={sending}
                onClick={sendReply}
                style={{ marginTop: 8 }}
                disabled={!reply.trim()}
              >
                Post message
              </Button>
            </Card>
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card title="Open work assigned to humans" loading={loading && !tasks.length} style={{ marginBottom: 16 }}>
            {tasks.length === 0 && !loading ? (
              <Empty description="No open human tasks" />
            ) : (
              <List
                size="small"
                dataSource={tasks}
                renderItem={(t) => (
                  <List.Item
                    actions={[
                      <Button key="t" type="link" size="small" onClick={() => nav('/tasks')}>
                        Board
                      </Button>,
                    ]}
                  >
                    <List.Item.Meta
                      title={(
                        <Space wrap>
                          <span>{t.title || `Task #${t.id}`}</span>
                          <Tag>{t.status}</Tag>
                          {t.priority && t.priority !== 'medium' && (
                            <Tag color="orange">{t.priority}</Tag>
                          )}
                        </Space>
                      )}
                      description={(
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {t.human_name ? `Human: ${t.human_name}` : ''}
                          {t.agent_name ? ` · Agent: ${t.agent_name}` : ''}
                        </Text>
                      )}
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>

          <Card title="My Human profile" size="small">
            {my ? (
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <Title level={5} style={{ margin: 0 }}>{my.name}</Title>
                <Text type="secondary">{my.email || 'No email set'}</Text>
                <div>
                  <Tag color="gold">My Human</Tag>
                  <Tag>{my.status || 'active'}</Tag>
                  <Tag>{my.permission_level || 'operator'}</Tag>
                </div>
                <Button block onClick={() => nav('/humans')}>
                  Manage team &amp; contacts
                </Button>
              </Space>
            ) : (
              <Empty
                description="No My Human yet"
              >
                <Button
                  type="primary"
                  onClick={() => api('/humans/my/ensure', { method: 'POST', timeoutMs: 60000 }).then(load)}
                >
                  Create My Human
                </Button>
              </Empty>
            )}
          </Card>
        </Col>
      </Row>
    </PageShell>
  )
}
