import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Card, Row, Col, Statistic, List, Tag, Space, Typography, Button, Spin, Empty,
  Progress, Badge, Segmented, Alert,
} from 'antd'
import {
  RobotOutlined, ThunderboltOutlined, CheckSquareOutlined, ReloadOutlined,
  MessageOutlined, PlayCircleOutlined, ClockCircleOutlined, WarningOutlined,
  ApartmentOutlined, FireOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import PageShell from '../components/PageShell'

const { Text, Paragraph, Title } = Typography

function normalizeAgents(data) {
  if (Array.isArray(data)) return data
  if (Array.isArray(data?.agents)) return data.agents
  if (Array.isArray(data?.items)) return data.items
  return []
}

function statusColor(s) {
  const v = (s || '').toLowerCase()
  if (v === 'active') return 'success'
  if (v === 'paused' || v === 'inactive') return 'default'
  if (v === 'error' || v === 'failed') return 'error'
  return 'processing'
}

function taskStatusColor(s) {
  const v = (s || '').toLowerCase()
  if (v === 'completed') return 'success'
  if (v === 'failed') return 'error'
  if (v === 'in_progress' || v === 'queued') return 'processing'
  if (v === 'review') return 'warning'
  return 'default'
}

function eventKindColor(kind) {
  const k = (kind || '').toLowerCase()
  if (k === 'skill' || k === 'action') return 'blue'
  if (k === 'plan' || k === 'step') return 'purple'
  if (k === 'system') return 'default'
  if (k === 'failed' || k === 'error') return 'red'
  return 'cyan'
}

/**
 * Agent dashboard — what the team is doing: live ops, tasks, activity per agent.
 */
export default function AgentDashboard() {
  const nav = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [agents, setAgents] = useState([])
  const [board, setBoard] = useState(null)
  const [events, setEvents] = useState([])
  const [snapshot, setSnapshot] = useState(null)
  const [filter, setFilter] = useState('all')

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    Promise.all([
      api('/agents/').catch(() => []),
      api('/agents/tasks/board').catch(() => null),
      api('/ops/live?limit=80').catch(() => ({ events: [], snapshot: null })),
    ])
      .then(([a, b, ops]) => {
        setAgents(normalizeAgents(a).filter((x) => x && x.id != null))
        setBoard(b && typeof b === 'object' ? b : null)
        setEvents(Array.isArray(ops?.events) ? ops.events : [])
        setSnapshot(ops?.snapshot || null)
      })
      .catch((e) => setError(e?.message || 'Failed to load agent dashboard'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 12000)
    return () => clearInterval(t)
  }, [load])

  const columns = board?.columns || {}
  const openTasks = useMemo(() => {
    const list = []
    for (const st of ['in_progress', 'queued', 'todo', 'review']) {
      const arr = columns[st] || []
      for (const t of arr) {
        if (t) list.push({ ...t, _status: st })
      }
    }
    return list
  }, [columns])

  const counts = useMemo(() => {
    const active = agents.filter((a) => (a.status || '') === 'active').length
    const paused = agents.length - active
    const inProg = (columns.in_progress || []).length
    const queued = (columns.queued || []).length
    const todo = (columns.todo || []).length
    const done = (columns.completed || []).length
    return { active, paused, inProg, queued, todo, done, open: inProg + queued + todo }
  }, [agents, columns])

  const agentTaskMap = useMemo(() => {
    const m = {}
    for (const t of openTasks) {
      const aid = t.agent_id
      if (aid == null) continue
      if (!m[aid]) m[aid] = []
      m[aid].push(t)
    }
    return m
  }, [openTasks])

  const filteredAgents = useMemo(() => {
    if (filter === 'active') return agents.filter((a) => a.status === 'active')
    if (filter === 'busy') {
      return agents.filter((a) => (agentTaskMap[a.id] || []).length > 0)
    }
    return agents
  }, [agents, filter, agentTaskMap])

  if (loading && agents.length === 0) {
    return (
      <PageShell title="Agent dashboard" showBack backTo="/console">
        <div style={{ textAlign: 'center', padding: 64 }}><Spin size="large" tip="Loading team…" /></div>
      </PageShell>
    )
  }

  return (
    <PageShell
      title="Agent dashboard"
      subtitle="What your agents are doing right now — tasks, skills, and live ops"
      showBack
      backTo="/console"
      extra={(
        <Space wrap>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>Refresh</Button>
          <Button type="primary" icon={<RobotOutlined />} onClick={() => nav('/console')}>
            Agent console
          </Button>
          <Button icon={<ThunderboltOutlined />} onClick={() => nav('/ops')}>Live ops</Button>
        </Space>
      )}
    >
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {error && (
          <Alert type="error" showIcon message={error} action={<Button size="small" onClick={load}>Retry</Button>} />
        )}

        <Row gutter={[12, 12]}>
          <Col xs={12} sm={8} md={4}>
            <Card className="aba-soft-card" size="small">
              <Statistic title="Agents" value={agents.length} prefix={<RobotOutlined />} />
            </Card>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Card className="aba-soft-card" size="small">
              <Statistic title="Active" value={counts.active} valueStyle={{ color: '#16a34a' }} />
            </Card>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Card className="aba-soft-card" size="small">
              <Statistic title="Open work" value={counts.open} prefix={<FireOutlined />} />
            </Card>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Card className="aba-soft-card" size="small">
              <Statistic title="In progress" value={counts.inProg} valueStyle={{ color: '#1668dc' }} />
            </Card>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Card className="aba-soft-card" size="small">
              <Statistic title="Queued" value={counts.queued} prefix={<ClockCircleOutlined />} />
            </Card>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Card className="aba-soft-card" size="small">
              <Statistic title="Completed" value={counts.done} prefix={<CheckSquareOutlined />} valueStyle={{ color: '#16a34a' }} />
            </Card>
          </Col>
        </Row>

        {snapshot?.headline && (
          <Alert type="info" showIcon message={snapshot.headline} description={snapshot.detail || snapshot.summary} />
        )}

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={14}>
            <Card
              className="aba-soft-card"
              title={<Space><RobotOutlined /><span>Team status</span></Space>}
              extra={(
                <Segmented
                  size="small"
                  value={filter}
                  onChange={setFilter}
                  options={[
                    { value: 'all', label: 'All' },
                    { value: 'active', label: 'Active' },
                    { value: 'busy', label: 'Busy' },
                  ]}
                />
              )}
            >
              {filteredAgents.length === 0 ? (
                <Empty description="No agents yet" image={Empty.PRESENTED_IMAGE_SIMPLE}>
                  <Button type="primary" onClick={() => nav('/console')}>Open console</Button>
                </Empty>
              ) : (
                <List
                  dataSource={filteredAgents}
                  renderItem={(a) => {
                    const tasks = agentTaskMap[a.id] || []
                    const openN = tasks.length
                    return (
                      <List.Item
                        actions={[
                          <Button
                            key="dash"
                            type="link"
                            size="small"
                            icon={<FireOutlined />}
                            onClick={() => nav(`/agents/${a.id}/dash`)}
                          >
                            Dashboard
                          </Button>,
                          <Button
                            key="chat"
                            type="link"
                            size="small"
                            icon={<MessageOutlined />}
                            onClick={() => nav(`/agents/${a.id}`)}
                          >
                            Chat
                          </Button>,
                          <Button
                            key="manage"
                            type="link"
                            size="small"
                            icon={<ApartmentOutlined />}
                            onClick={() => nav(`/agents/${a.id}/manage`)}
                          >
                            Settings
                          </Button>,
                        ]}
                      >
                        <List.Item.Meta
                          avatar={(
                            <Badge count={openN} size="small" offset={[-2, 4]} color="#1668dc">
                              <div
                                role="button"
                                tabIndex={0}
                                onClick={() => nav(`/agents/${a.id}/dash`)}
                                onKeyDown={(e) => e.key === 'Enter' && nav(`/agents/${a.id}/dash`)}
                                style={{
                                  width: 40,
                                  height: 40,
                                  borderRadius: 10,
                                  background: 'linear-gradient(135deg,#1d4ed8,#3b82f6)',
                                  color: '#fff',
                                  display: 'flex',
                                  alignItems: 'center',
                                  justifyContent: 'center',
                                  fontWeight: 700,
                                  cursor: 'pointer',
                                }}
                              >
                                {(a.name || '?').slice(0, 1).toUpperCase()}
                              </div>
                            </Badge>
                          )}
                          title={(
                            <Space wrap size={[6, 4]}>
                              <Text
                                strong
                                style={{ cursor: 'pointer' }}
                                onClick={() => nav(`/agents/${a.id}/dash`)}
                              >
                                {a.name}
                              </Text>
                              <Tag color={statusColor(a.status)}>{a.status || 'unknown'}</Tag>
                              {a.hierarchy_role && <Tag>{a.hierarchy_role}</Tag>}
                              {a.template_type && <Tag color="blue">{a.template_type}</Tag>}
                            </Space>
                          )}
                          description={(
                            <div>
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                {openN
                                  ? `${openN} open task${openN === 1 ? '' : 's'}`
                                  : 'Idle — no open board tasks'}
                                {a.model ? ` · model ${a.model}` : ''}
                              </Text>
                              {tasks.slice(0, 3).map((t) => (
                                <div key={t.id} style={{ marginTop: 4 }}>
                                  <Tag color={taskStatusColor(t._status || t.status)} style={{ marginRight: 6 }}>
                                    {t._status || t.status}
                                  </Tag>
                                  <Text style={{ fontSize: 12 }}>
                                    #{t.id} {t.title || t.description || 'Task'}
                                  </Text>
                                </div>
                              ))}
                              {openN > 0 && (
                                <Progress
                                  percent={Math.min(100, openN * 20)}
                                  showInfo={false}
                                  size="small"
                                  style={{ marginTop: 6, maxWidth: 220 }}
                                  strokeColor="#1668dc"
                                />
                              )}
                            </div>
                          )}
                        />
                      </List.Item>
                    )
                  }}
                />
              )}
            </Card>
          </Col>

          <Col xs={24} lg={10}>
            <Card
              className="aba-soft-card"
              title={<Space><ThunderboltOutlined /><span>Live activity</span></Space>}
              extra={<Text type="secondary" style={{ fontSize: 12 }}>Auto-refresh 12s</Text>}
              styles={{ body: { maxHeight: 520, overflowY: 'auto' } }}
            >
              {events.length === 0 ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="No recent ops events — chat an agent or run a task"
                />
              ) : (
                <List
                  size="small"
                  dataSource={events.slice(0, 40)}
                  renderItem={(ev, i) => (
                    <List.Item key={ev.id || i}>
                      <List.Item.Meta
                        title={(
                          <Space wrap size={[4, 4]}>
                            <Tag color={eventKindColor(ev.kind || ev.status)}>{ev.kind || 'event'}</Tag>
                            <Text strong style={{ fontSize: 13 }}>
                              {ev.title || ev.event || 'Update'}
                            </Text>
                          </Space>
                        )}
                        description={(
                          <div>
                            <Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }} ellipsis={{ rows: 2 }}>
                              {ev.detail || ev.message || ev.status || ''}
                            </Paragraph>
                            <Text type="secondary" style={{ fontSize: 11 }}>
                              {ev.agent_name || (ev.agent_id ? `Agent #${ev.agent_id}` : '')}
                              {ev.task_id ? ` · task #${ev.task_id}` : ''}
                              {ev.created_at
                                ? ` · ${new Date(ev.created_at).toLocaleString()}`
                                : ''}
                            </Text>
                          </div>
                        )}
                      />
                    </List.Item>
                  )}
                />
              )}
            </Card>

            <Card
              className="aba-soft-card"
              style={{ marginTop: 16 }}
              title={<Space><PlayCircleOutlined /><span>Open tasks</span></Space>}
              extra={(
                <Button type="link" size="small" onClick={() => nav('/tasks')}>
                  Board
                </Button>
              )}
              styles={{ body: { maxHeight: 280, overflowY: 'auto' } }}
            >
              {openTasks.length === 0 ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No open tasks" />
              ) : (
                <List
                  size="small"
                  dataSource={openTasks.slice(0, 20)}
                  renderItem={(t) => (
                    <List.Item>
                      <Space direction="vertical" size={0} style={{ width: '100%' }}>
                        <Space wrap>
                          <Tag color={taskStatusColor(t._status || t.status)}>
                            {t._status || t.status}
                          </Tag>
                          {(t.labels || '').includes('post-chat') && <Tag color="gold">post-chat</Tag>}
                          {(t.labels || '').includes('auto-chain') && <Tag color="purple">chain</Tag>}
                        </Space>
                        <Text style={{ fontSize: 13 }}>
                          #{t.id} {t.title || 'Untitled'}
                        </Text>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {t.agent_name || (t.agent_id ? `Agent #${t.agent_id}` : 'Unassigned')}
                          {t.priority ? ` · ${t.priority}` : ''}
                        </Text>
                      </Space>
                    </List.Item>
                  )}
                />
              )}
            </Card>
          </Col>
        </Row>

        <Card className="aba-soft-card" size="small">
          <Space wrap>
            <Text type="secondary">Tip:</Text>
            <Text type="secondary">
              Agents create products with <Text code>create_product</Text> / special offers with{' '}
              <Text code>set_product_offer</Text>. Custom metadata via{' '}
              <Text code>set_agent_custom_field</Text>. After skills run, chat shows a full “What I just did” summary.
            </Text>
          </Space>
        </Card>
      </Space>
    </PageShell>
  )
}
