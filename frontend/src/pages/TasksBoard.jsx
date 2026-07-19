import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Card, Tag, Button, Space, Typography, Modal, Form, Input, Select, Switch,
  message, Empty, Badge, Dropdown, Spin, Tooltip,
} from 'antd'
import {
  PlusOutlined, ReloadOutlined, ThunderboltOutlined, MoreOutlined,
  RobotOutlined, ProjectOutlined, CommentOutlined, LinkOutlined,
  FlagOutlined, NodeIndexOutlined, ApartmentOutlined, CheckSquareOutlined,
  FilterOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, connectAuthedWs } from '../api'
import PageHeader from '../components/PageHeader'
import PageShell from '../components/PageShell'

const COLUMNS = [
  { key: 'todo', title: 'To do', color: '#8c8c8c' },
  { key: 'queued', title: 'Queued', color: '#1677ff' },
  { key: 'in_progress', title: 'In progress', color: '#faad14' },
  { key: 'review', title: 'Review', color: '#722ed1' },
  { key: 'completed', title: 'Completed', color: '#52c41a' },
  { key: 'failed', title: 'Failed', color: '#ff4d4f' },
]

const PRIORITY_COLOR = {
  low: 'default', medium: 'blue', high: 'orange', urgent: 'red',
}

/** Parse comma-separated or array labels from task.labels */
function parseLabels(labels) {
  if (!labels) return []
  if (Array.isArray(labels)) return labels.map(String).map(s => s.trim()).filter(Boolean)
  return String(labels).split(',').map(s => s.trim()).filter(Boolean)
}

/**
 * Chain / goal meta for display.
 * Backend: parent labels "goal,auto-chain,monitor"; children "auto-chain,step,N".
 * Keeps auto-chain prompt → task → delegate → monitor → complete visible on the board.
 */
function chainMeta(task) {
  if (!task) {
    return {
      labels: [], isGoal: false, isAutoChain: false, isStep: false,
      isMonitor: false, stepN: null, parentId: null, meetingId: null, inChain: false,
    }
  }
  const labels = parseLabels(task.labels)
  const lower = labels.map(l => l.toLowerCase())
  const hasExact = (name) => lower.some(l => l === name)
  const isGoal = hasExact('goal') || /^(goal\s*:)/i.test(task.title || '')
  const isAutoChain = hasExact('auto-chain') || hasExact('autochain')
  const isMonitor = hasExact('monitor')
  const numeric = labels.find(l => /^\d+$/.test(String(l).trim()))
  const stepLabel = lower.find(l => /^step[-_\s]?\d+$/i.test(l) || l === 'step' || l === 'plan-step')
  let stepN = null
  if (numeric) stepN = String(numeric)
  else if (stepLabel) {
    const m = String(stepLabel).match(/(\d+)/)
    if (m) stepN = m[1]
  }
  const isStep = !!(stepLabel || numeric || task.parent_task_id) && !isGoal
  const parentId = task.parent_task_id || null
  const meetingId = task.meeting_id || null
  const inChain = !!(isGoal || isAutoChain || isStep || parentId)
  return {
    labels,
    isGoal,
    isAutoChain,
    isMonitor: isMonitor && isGoal,
    isStep,
    stepN,
    parentId,
    meetingId,
    inChain,
  }
}

function ChainTags({ task, size = 'default' }) {
  const m = chainMeta(task)
  if (!m.inChain && !m.meetingId) return null
  const style = size === 'small' ? { fontSize: 11, lineHeight: '18px', marginInlineEnd: 0 } : undefined
  return (
    <span className="tasks-board-chain-tags" role="group" aria-label="Goal chain tags">
      {m.isGoal && (
        <Tag icon={<FlagOutlined />} color="gold" style={style}>Goal</Tag>
      )}
      {m.isMonitor && (
        <Tag color="magenta" style={style}>Monitor</Tag>
      )}
      {m.isAutoChain && (
        <Tag icon={<NodeIndexOutlined />} color="cyan" style={style}>Auto-chain</Tag>
      )}
      {m.isStep && (
        <Tag color="processing" style={style}>
          {m.stepN ? `Step ${m.stepN}` : 'Step'}
        </Tag>
      )}
      {m.parentId && (
        <Tooltip title={`Child of goal/parent task #${m.parentId}`}>
          <Tag icon={<ApartmentOutlined />} color="blue" style={style}>
            Parent #{m.parentId}
          </Tag>
        </Tooltip>
      )}
      {m.meetingId && (
        <Tag icon={<CommentOutlined />} color="purple" style={style}>
          Room #{m.meetingId}
        </Tag>
      )}
    </span>
  )
}

export default function TasksBoard() {
  const nav = useNavigate()
  const [board, setBoard] = useState(null)
  const [agents, setAgents] = useState([])
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [detail, setDetail] = useState(null)
  const [projectFilter, setProjectFilter] = useState(undefined)
  const [chainOnly, setChainOnly] = useState(false)
  const [discussingId, setDiscussingId] = useState(null)
  const [form] = Form.useForm()
  const agentId = Form.useWatch('agent_id', form)
  const wsRef = useRef(null)

  const load = () => {
    setLoading(true)
    Promise.all([
      api('/agents/tasks/board'),
      api('/agents/').catch(() => []),
      api('/org/projects').catch(() => []),
    ])
      .then(([b, a, p]) => {
        setBoard(b)
        setAgents(Array.isArray(a) ? a : [])
        setProjects(Array.isArray(p) ? p : (p?.projects || []))
      })
      .catch(e => message.error(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    const ws = connectAuthedWs('/agents/ws')
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data)
      if (m.type === 'auth_ok') return
      if (m.event === 'task_done' || m.event === 'task_updated') load()
    }
    wsRef.current = ws
    return () => ws.close()
  }, [])

  const move = async (task, status) => {
    try {
      await api(`/agents/tasks/${task.id}`, { method: 'PATCH', body: { status } })
      load()
    } catch (e) {
      message.error(e.message)
    }
  }

  const create = async (v) => {
    try {
      if (!v.agent_id && !v.project_id) {
        message.error('Pick an agent or a project')
        return
      }
      if (!v.agent_id) {
        await api('/org/tasks', {
          method: 'POST',
          body: {
            project_id: v.project_id,
            title: v.title,
            description: v.description,
            agent_id: null,
            status: 'todo',
          },
        })
      } else {
        await api(`/agents/${v.agent_id}/tasks`, {
          method: 'POST',
          body: {
            title: v.title,
            description: v.description,
            project_id: v.project_id || null,
            priority: v.priority || 'medium',
            run_now: v.agent_id ? !!v.run_now : false,
          },
        })
      }
      message.success('Task created')
      setCreateOpen(false)
      form.resetFields()
      load()
    } catch (e) {
      message.error(e.message)
    }
  }

  const run = async (task) => {
    try {
      await api(`/agents/tasks/${task.id}/run`, { method: 'POST' })
      message.success('Agent started')
      load()
    } catch (e) {
      message.error(e.message)
    }
  }

  const discussInRoom = async (task) => {
    if (!task?.id) return
    const existingId = task.meeting_id
    if (existingId) {
      setDetail(null)
      nav(`/meetings/${existingId}`)
      return
    }
    setDiscussingId(task.id)
    try {
      const body = {
        title: task.title || 'Task discussion',
        task_id: task.id,
      }
      if (task.agent_id) {
        body.agent_ids = [task.agent_id]
      }
      const room = await api('/meetings', { method: 'POST', body })
      const roomId = room?.id ?? room?.meeting_id
      if (!roomId) throw new Error('Meeting room created but no id returned')
      message.success('Meeting room created')
      setDetail(null)
      nav(`/meetings/${roomId}`)
    } catch (e) {
      message.error(e.message)
    } finally {
      setDiscussingId(null)
    }
  }

  const discussLabel = (task) => (task?.meeting_id ? 'Open room' : 'Discuss in room')

  const allTasks = useMemo(() => {
    const cols = board?.columns || {}
    return COLUMNS.flatMap(c => cols[c.key] || [])
  }, [board])

  const chainStats = useMemo(() => {
    let goals = 0
    let autoChains = 0
    let steps = 0
    let monitors = 0
    allTasks.forEach((t) => {
      const m = chainMeta(t)
      if (m.isGoal) goals += 1
      if (m.isAutoChain) autoChains += 1
      if (m.isStep) steps += 1
      if (m.isMonitor) monitors += 1
    })
    return { goals, autoChains, steps, monitors }
  }, [allTasks])

  const filterTask = (task) => {
    if (projectFilter) {
      const pname = projects.find(p => p.id === projectFilter)?.name
      if (!(task.project_id === projectFilter || task.project_name === pname)) return false
    }
    if (chainOnly && !chainMeta(task).inChain) return false
    return true
  }

  if (loading && !board) {
    return (
      <PageShell wide>
        <Card className="aba-soft-card">
          <div style={{ textAlign: 'center', padding: '64px 24px' }}>
            <Spin size="large" tip="Loading tasks board…" />
          </div>
        </Card>
      </PageShell>
    )
  }

  const columns = board?.columns || {}

  return (
    <PageShell wide className="tasks-board-page">
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {/* Header card — stats + filters */}
        <Card className="aba-soft-card" styles={{ body: { paddingBlock: 16 } }}>
          <PageHeader
            style={{ marginBottom: 12 }}
            title={(
              <span>
                <CheckSquareOutlined style={{ marginRight: 8 }} />
                Tasks workflow
              </span>
            )}
            subtitle={`Agent & project work board · ${board?.total || 0} tasks · goals, auto-chain steps, and rooms in one place`}
            extra={(
              <Space wrap>
                <Select
                  allowClear
                  placeholder="Filter by project"
                  style={{ minWidth: 180 }}
                  value={projectFilter}
                  onChange={setProjectFilter}
                  options={projects.map(p => ({ value: p.id, label: p.name }))}
                />
                <Button
                  icon={<FilterOutlined />}
                  type={chainOnly ? 'primary' : 'default'}
                  ghost={chainOnly}
                  onClick={() => setChainOnly(v => !v)}
                >
                  {chainOnly ? 'Chain only' : 'All tasks'}
                </Button>
                <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
                  Refresh
                </Button>
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
                  New task
                </Button>
              </Space>
            )}
          />
          <Space wrap size={[8, 8]} className="tasks-board-header-stats">
            <Tag icon={<FlagOutlined />} color="gold">
              Goals {chainStats.goals}
            </Tag>
            <Tag color="magenta">
              Monitor {chainStats.monitors}
            </Tag>
            <Tag icon={<NodeIndexOutlined />} color="cyan">
              Auto-chain {chainStats.autoChains}
            </Tag>
            <Tag color="processing">
              Steps {chainStats.steps}
            </Tag>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Column Cards · Goal · Monitor · Auto-chain · Step · Parent # · Room
            </Typography.Text>
          </Space>
        </Card>

        {/* Kanban: each status column is an Ant Design Card */}
        <div className="aba-box tasks-board-container" style={{ marginBottom: 0 }}>
          <div className="tasks-board-columns">
            {COLUMNS.map(col => {
              const colTasks = (columns[col.key] || []).filter(filterTask)
              return (
                <Card
                  key={col.key}
                  size="small"
                  className="tasks-board-column-card aba-soft-card"
                  title={(
                    <span className="tasks-board-col-title">
                      <span
                        className="tasks-board-col-dot"
                        style={{ background: col.color }}
                        aria-hidden
                      />
                      <span>{col.title}</span>
                      <Badge
                        count={colTasks.length || 0}
                        showZero
                        style={{ background: col.color }}
                      />
                    </span>
                  )}
                  styles={{
                    header: {
                      borderBottom: `2px solid ${col.color}`,
                      minHeight: 44,
                      textAlign: 'center',
                    },
                  }}
                >
                  {colTasks.length === 0 && (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Empty" />
                  )}
                  {colTasks.map(task => {
                    const meta = chainMeta(task)
                    return (
                      <Card
                        key={task.id}
                        size="small"
                        hoverable
                        className={[
                          'tasks-board-task-card',
                          meta.isGoal ? 'is-goal' : '',
                          meta.isStep ? 'is-step' : '',
                          meta.inChain ? 'is-chain' : '',
                        ].filter(Boolean).join(' ')}
                        onClick={() => setDetail(task)}
                      >
                        <Space direction="vertical" size={4} style={{ width: '100%' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                            <Typography.Text strong ellipsis style={{ flex: 1 }}>
                              {task.title}
                            </Typography.Text>
                            <Dropdown
                              menu={{
                                items: [
                                  ...COLUMNS.filter(c => c.key !== task.status).map(c => ({
                                    key: c.key,
                                    label: `Move to ${c.title}`,
                                    onClick: ({ domEvent }) => {
                                      domEvent.stopPropagation()
                                      move(task, c.key)
                                    },
                                  })),
                                  task.agent_id && {
                                    key: 'run',
                                    label: 'Run with agent',
                                    icon: <ThunderboltOutlined />,
                                    onClick: ({ domEvent }) => {
                                      domEvent.stopPropagation()
                                      run(task)
                                    },
                                  },
                                  task.agent_id && {
                                    key: 'agent',
                                    label: 'Open agent',
                                    icon: <RobotOutlined />,
                                    onClick: ({ domEvent }) => {
                                      domEvent.stopPropagation()
                                      nav(`/agents/${task.agent_id}`)
                                    },
                                  },
                                  {
                                    key: 'discuss',
                                    label: discussLabel(task),
                                    icon: <CommentOutlined />,
                                    onClick: ({ domEvent }) => {
                                      domEvent.stopPropagation()
                                      discussInRoom(task)
                                    },
                                  },
                                ].filter(Boolean),
                              }}
                              trigger={['click']}
                            >
                              <Button
                                type="text"
                                size="small"
                                icon={<MoreOutlined />}
                                onClick={e => e.stopPropagation()}
                              />
                            </Dropdown>
                          </div>
                          <Typography.Paragraph
                            type="secondary"
                            ellipsis={{ rows: 2 }}
                            style={{ margin: 0, fontSize: 12 }}
                          >
                            {task.description}
                          </Typography.Paragraph>
                          <Space wrap size={[4, 4]}>
                            <ChainTags task={task} size="small" />
                            <Tag color={PRIORITY_COLOR[task.priority] || 'default'}>{task.priority}</Tag>
                            {task.agent_name && (
                              <Tag icon={<RobotOutlined />} color="geekblue">{task.agent_name}</Tag>
                            )}
                            {task.project_name && (
                              <Tag icon={<ProjectOutlined />}>{task.project_name}</Tag>
                            )}
                            {task.tokens_used > 0 && (
                              <Tag color="purple">{task.tokens_used} tok</Tag>
                            )}
                          </Space>
                          <Button
                            type="link"
                            size="small"
                            icon={<CommentOutlined />}
                            loading={discussingId === task.id}
                            style={{ padding: 0, height: 'auto' }}
                            onClick={(e) => {
                              e.stopPropagation()
                              discussInRoom(task)
                            }}
                          >
                            {discussLabel(task)}
                          </Button>
                        </Space>
                      </Card>
                    )
                  })}
                </Card>
              )
            })}
          </div>
        </div>
      </Space>

      <Modal title="New task" open={createOpen} onCancel={() => setCreateOpen(false)} footer={null} destroyOnClose>
        <Form
          form={form}
          layout="vertical"
          onFinish={create}
          initialValues={{ priority: 'medium', run_now: true }}
        >
          <Form.Item name="title" label="Title"><Input placeholder="Short title" /></Form.Item>
          <Form.Item name="description" label="Description" rules={[{ required: true }]}>
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item
            name="agent_id"
            label="Assign agent"
            extra={!agentId ? 'Optional if a project is selected — task stays To do until run' : undefined}
          >
            <Select
              allowClear
              options={agents.map(a => ({
                value: a.id,
                label: `${a.name} (${a.status})`,
              }))}
              placeholder="Select agent (optional with project)"
            />
          </Form.Item>
          <Form.Item
            name="project_id"
            label="Project"
            rules={[
              {
                validator: async (_, value) => {
                  if (!value && !form.getFieldValue('agent_id')) {
                    throw new Error('Pick an agent or a project')
                  }
                },
              },
            ]}
            extra="Required when no agent is assigned"
          >
            <Select allowClear options={projects.map(p => ({ value: p.id, label: p.name }))} />
          </Form.Item>
          <Form.Item name="priority" label="Priority">
            <Select options={[
              { value: 'low', label: 'Low' },
              { value: 'medium', label: 'Medium' },
              { value: 'high', label: 'High' },
              { value: 'urgent', label: 'Urgent' },
            ]} />
          </Form.Item>
          <Form.Item
            name="run_now"
            label="Run immediately with agent"
            valuePropName="checked"
            extra={!agentId ? 'Disabled until an agent is assigned' : undefined}
          >
            <Switch disabled={!agentId} />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>Create task</Button>
        </Form>
      </Modal>

      <Modal
        open={!!detail}
        title={detail?.title}
        onCancel={() => setDetail(null)}
        width={700}
        footer={[
          <Button key="c" onClick={() => setDetail(null)}>Close</Button>,
          detail && (
            <Button
              key="d"
              icon={<CommentOutlined />}
              loading={discussingId === detail.id}
              onClick={() => discussInRoom(detail)}
            >
              {discussLabel(detail)}
            </Button>
          ),
          detail?.agent_id && (
            <Button key="a" onClick={() => nav(`/agents/${detail.agent_id}`)}>Open agent chat</Button>
          ),
          detail?.agent_id && detail?.status !== 'completed' && (
            <Button key="r" type="primary" icon={<ThunderboltOutlined />} onClick={() => { run(detail); setDetail(null) }}>
              Run
            </Button>
          ),
        ]}
      >
        {detail && (() => {
          const meta = chainMeta(detail)
          return (
            <>
              <Space wrap style={{ marginBottom: 12 }}>
                <Tag>{detail.status}</Tag>
                <Tag color={PRIORITY_COLOR[detail.priority]}>{detail.priority}</Tag>
                <ChainTags task={detail} />
                {detail.agent_name && <Tag color="geekblue" icon={<RobotOutlined />}>{detail.agent_name}</Tag>}
                {detail.project_name && <Tag icon={<ProjectOutlined />}>{detail.project_name}</Tag>}
              </Space>
              {(meta.inChain || meta.meetingId || meta.labels.length > 0) && (
                <Card
                  size="small"
                  className="tasks-board-chain-detail-card"
                  style={{ marginBottom: 12 }}
                  styles={{ header: { textAlign: 'center' } }}
                  title={(
                    <Space size={6}>
                      <NodeIndexOutlined />
                      <span>Goal chain</span>
                    </Space>
                  )}
                >
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    {meta.parentId && (
                      <Typography.Text>
                        <ApartmentOutlined style={{ marginRight: 6 }} />
                        Parent task <Typography.Text code>#{meta.parentId}</Typography.Text>
                        <Typography.Text type="secondary"> · part of goal / auto-chain</Typography.Text>
                      </Typography.Text>
                    )}
                    {meta.isGoal && (
                      <Typography.Text>
                        <FlagOutlined style={{ marginRight: 6 }} />
                        Goal task — monitors child auto-chain steps
                        {meta.isMonitor ? ' · labeled monitor' : ''}
                      </Typography.Text>
                    )}
                    {meta.isAutoChain && !meta.isGoal && (
                      <Typography.Text>
                        <NodeIndexOutlined style={{ marginRight: 6 }} />
                        Auto-chain step{meta.stepN ? ` ${meta.stepN}` : ''}
                      </Typography.Text>
                    )}
                    {meta.isStep && !meta.isAutoChain && (
                      <Typography.Text type="secondary">
                        Child step{meta.stepN ? ` ${meta.stepN}` : ''} in a task chain
                      </Typography.Text>
                    )}
                    {meta.meetingId && (
                      <Typography.Text>
                        <LinkOutlined style={{ marginRight: 6 }} />
                        Linked room{' '}
                        <Button
                          type="link"
                          size="small"
                          style={{ padding: 0, height: 'auto' }}
                          onClick={() => nav(`/meetings/${meta.meetingId}`)}
                        >
                          #{meta.meetingId}
                        </Button>
                      </Typography.Text>
                    )}
                    {meta.labels.length > 0 && (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        Labels: {meta.labels.join(', ')}
                      </Typography.Text>
                    )}
                  </Space>
                </Card>
              )}
              <Typography.Paragraph>{detail.description}</Typography.Paragraph>
              <Space style={{ marginBottom: 12 }} wrap>
                {COLUMNS.filter(c => c.key !== detail.status).map(c => (
                  <Button key={c.key} size="small" onClick={() => { move(detail, c.key); setDetail(null) }}>
                    → {c.title}
                  </Button>
                ))}
              </Space>
              {detail.result ? (
                <>
                  <Typography.Title level={5}>Result</Typography.Title>
                  <div style={{ background: '#f6f8fa', padding: 12, borderRadius: 8, whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>
                    {detail.result}
                  </div>
                </>
              ) : (
                <Typography.Text type="secondary">No deliverable yet — run the task with an agent.</Typography.Text>
              )}
            </>
          )
        })()}
      </Modal>
    </PageShell>
  )
}
