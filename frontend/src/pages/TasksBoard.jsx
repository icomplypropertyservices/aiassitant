import React, { useEffect, useRef, useState } from 'react'
import {
  Card, Tag, Button, Space, Typography, Modal, Form, Input, Select, Switch,
  message, Empty, Badge, Dropdown, Spin,
} from 'antd'
import {
  PlusOutlined, ReloadOutlined, ThunderboltOutlined, MoreOutlined,
  RobotOutlined, ProjectOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, connectAuthedWs } from '../api'

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

export default function TasksBoard() {
  const nav = useNavigate()
  const [board, setBoard] = useState(null)
  const [agents, setAgents] = useState([])
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [detail, setDetail] = useState(null)
  const [projectFilter, setProjectFilter] = useState(undefined)
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
        setAgents(a)
        setProjects(p)
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
        // Project-only task: no agent → todo, run_now false
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

  if (loading && !board) {
    return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>
  }

  const columns = board?.columns || {}
  const counts = board?.counts || {}
  const filterTask = (task) => {
    if (!projectFilter) return true
    return task.project_id === projectFilter || task.project_name === projects.find(p => p.id === projectFilter)?.name
  }

  return (
    <div>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }} wrap>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>Tasks workflow</Typography.Title>
          <Typography.Text type="secondary">
            Separate board for all agent &amp; project work · {board?.total || 0} tasks
          </Typography.Text>
        </div>
        <Space wrap>
          <Select
            allowClear
            placeholder="Filter by project"
            style={{ minWidth: 180 }}
            value={projectFilter}
            onChange={setProjectFilter}
            options={projects.map(p => ({ value: p.id, label: p.name }))}
          />
          <Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>New task</Button>
        </Space>
      </Space>

      <div style={{ display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 12, minHeight: 480 }}>
        {COLUMNS.map(col => (
          <div key={col.key} style={{ minWidth: 260, maxWidth: 300, flex: '0 0 260px' }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              marginBottom: 8, padding: '4px 8px', borderLeft: `3px solid ${col.color}`,
            }}>
              <Typography.Text strong>{col.title}</Typography.Text>
              <Badge
                count={(columns[col.key] || []).filter(filterTask).length || 0}
                style={{ background: col.color }}
              />
            </div>
            <div style={{
              background: '#f0f2f5', borderRadius: 10, padding: 8,
              minHeight: 400, maxHeight: 'calc(100vh - 240px)', overflowY: 'auto',
            }}>
              {(columns[col.key] || []).filter(filterTask).length === 0 && (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Empty" />
              )}
              {(columns[col.key] || []).filter(filterTask).map(task => (
                <Card
                  key={task.id}
                  size="small"
                  hoverable
                  style={{ marginBottom: 8, borderRadius: 8 }}
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
                  </Space>
                </Card>
              ))}
            </div>
          </div>
        ))}
      </div>

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
        {detail && (
          <>
            <Space wrap style={{ marginBottom: 12 }}>
              <Tag>{detail.status}</Tag>
              <Tag color={PRIORITY_COLOR[detail.priority]}>{detail.priority}</Tag>
              {detail.agent_name && <Tag color="geekblue">{detail.agent_name}</Tag>}
              {detail.project_name && <Tag>{detail.project_name}</Tag>}
            </Space>
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
        )}
      </Modal>
    </div>
  )
}
