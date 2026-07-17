import React, { useEffect, useMemo, useState } from 'react'
import {
  Card, Row, Col, Typography, Tag, Timeline, Statistic, Space, Button, Empty, Spin, List, Form, Input, message,
} from 'antd'
import {
  RobotOutlined, UserOutlined, ThunderboltOutlined, ReloadOutlined, ClusterOutlined,
  CheckCircleOutlined, LoadingOutlined, CloseCircleOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, getToken, getWsBase } from '../api'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

export default function Ops() {
  const nav = useNavigate()
  const [snap, setSnap] = useState(null)
  const [loading, setLoading] = useState(true)
  const [planForm] = Form.useForm()
  const [publishing, setPublishing] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const r = await api('/ops/visual')
      setSnap(r)
    } catch (e) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    let ws
    try {
      ws = new WebSocket(`${getWsBase()}/ops/ws?token=${getToken()}`)
      ws.onmessage = (ev) => {
        try {
          const m = JSON.parse(ev.data)
          if (m.event === 'snapshot') setSnap(m.snapshot)
          if (m.event === 'ops') {
            setSnap((prev) => {
              if (!prev) return prev
              const events = [m.entry, ...(prev.events || []).filter((e) => e.id !== m.entry.id)].slice(0, 50)
              return { ...prev, events }
            })
          }
        } catch { /* ignore */ }
      }
    } catch { /* ignore */ }
    return () => { try { ws?.close() } catch { /* ignore */ } }
  }, [])

  const publishPlan = async (values) => {
    setPublishing(true)
    try {
      const steps = (values.steps || '')
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean)
      await api('/ops/plan', { method: 'POST', body: { title: values.title, steps } })
      message.success('Plan published to live banner')
      planForm.resetFields()
      load()
    } catch (e) {
      message.error(e.message)
    } finally {
      setPublishing(false)
    }
  }

  const agents = snap?.nodes?.agents || []
  const humans = snap?.nodes?.humans || []
  const events = snap?.events || []
  const plans = snap?.active_plans || []
  const counts = snap?.counts || {}

  // Simple hierarchy layout: orchestrators top, then leads, then rest
  const layout = useMemo(() => {
    const orch = agents.filter((a) => a.role === 'orchestrator')
    const leads = agents.filter((a) => a.role === 'lead' || a.role === 'orchestrator' === false && !a.parent_id)
    const rest = agents.filter((a) => a.role !== 'orchestrator')
    return { orch, leads: agents.filter((a) => a.role === 'lead'), members: agents.filter((a) => !['orchestrator', 'lead'].includes(a.role)), rest }
  }, [agents])

  if (loading && !snap) {
    return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" tip="Loading ops visual…" /></div>
  }

  return (
    <div>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }} wrap>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            <ThunderboltOutlined /> Live operations
          </Title>
          <Text type="secondary">Real-time plans, agent actions, human work, and app usage</Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button>
      </Space>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}><Card><Statistic title="Agents active" value={counts.agents_active || 0} suffix={`/ ${counts.agents || 0}`} prefix={<RobotOutlined />} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="Humans active" value={counts.humans_active || 0} suffix={`/ ${counts.humans || 0}`} prefix={<UserOutlined />} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="Open tasks" value={counts.open_tasks || 0} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="Recent events" value={counts.events_recent || 0} prefix={<ThunderboltOutlined />} /></Card></Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card
            title={<><ClusterOutlined /> Organisation map</>}
            style={{ marginBottom: 16, minHeight: 320 }}
          >
            {!agents.length && !humans.length ? (
              <Empty description="No agents or humans yet" />
            ) : (
              <div>
                {layout.orch.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <Text type="secondary">Orchestrators</Text>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
                      {layout.orch.map((a) => (
                        <Card
                          key={a.id}
                          size="small"
                          hoverable
                          onClick={() => nav(`/agents/${a.id}`)}
                          style={{
                            minWidth: 140,
                            border: '2px solid #faad14',
                            background: '#fffbe6',
                          }}
                        >
                          <RobotOutlined style={{ color: '#d48806' }} /> <strong>{a.name}</strong>
                          <div><Tag color={a.status === 'active' ? 'green' : 'default'}>{a.status}</Tag></div>
                        </Card>
                      ))}
                    </div>
                  </div>
                )}
                <div style={{ marginBottom: 16 }}>
                  <Text type="secondary">Leads & specialists</Text>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
                    {agents.filter((a) => a.role !== 'orchestrator').map((a) => (
                      <Card
                        key={a.id}
                        size="small"
                        hoverable
                        onClick={() => nav(`/agents/${a.id}`)}
                        style={{
                          minWidth: 130,
                          borderLeft: `4px solid ${a.role === 'lead' ? '#1668dc' : '#8c8c8c'}`,
                        }}
                      >
                        <RobotOutlined /> {a.name}
                        <div>
                          <Tag>{a.role}</Tag>
                          <Tag color={a.status === 'active' ? 'green' : 'orange'}>{a.status}</Tag>
                        </div>
                        {a.parent_id && <Text type="secondary" style={{ fontSize: 11 }}>reports → #{a.parent_id}</Text>}
                      </Card>
                    ))}
                  </div>
                </div>
                <div>
                  <Text type="secondary">Humans</Text>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
                    {humans.map((h) => (
                      <Card
                        key={h.id}
                        size="small"
                        hoverable
                        onClick={() => nav('/humans')}
                        style={{ minWidth: 130, borderLeft: '4px solid #52c41a' }}
                      >
                        <UserOutlined /> {h.name}
                        <div><Tag color="green">{h.role_title || 'teammate'}</Tag></div>
                        <Tag>{h.status}</Tag>
                      </Card>
                    ))}
                    {!humans.length && <Text type="secondary">No humans yet — add them under Humans</Text>}
                  </div>
                </div>
              </div>
            )}
          </Card>

          <Card title="Active plans">
            {!plans.length ? (
              <Empty description="No running plans — agents can announce plans via skills or publish below" />
            ) : (
              plans.map((p) => (
                <Card key={p.plan_id} type="inner" size="small" style={{ marginBottom: 12 }} title={p.title}>
                  <Space style={{ marginBottom: 8 }}>
                    <Tag color="processing">{p.running} running</Tag>
                    <Tag color="success">{p.done} done</Tag>
                  </Space>
                  <Timeline
                    items={(p.steps || []).slice(0, 12).map((s) => ({
                      color: s.status === 'done' ? 'green' : s.status === 'failed' ? 'red' : s.status === 'running' ? 'blue' : 'gray',
                      children: (
                        <span>
                          <strong>{s.title}</strong> {s.detail}
                        </span>
                      ),
                    }))}
                  />
                </Card>
              ))
            )}
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card title="Publish plan" style={{ marginBottom: 16 }}>
            <Form form={planForm} layout="vertical" onFinish={publishPlan}>
              <Form.Item name="title" label="Plan title" rules={[{ required: true }]}>
                <Input placeholder="e.g. Launch campaign for Project X" />
              </Form.Item>
              <Form.Item name="steps" label="Steps (one per line)" rules={[{ required: true }]}>
                <TextArea rows={4} placeholder={'Research audience\nDraft posts\nAssign human review\nPublish to socials'} />
              </Form.Item>
              <Button type="primary" htmlType="submit" loading={publishing} block icon={<ClusterOutlined />}>
                Broadcast plan
              </Button>
            </Form>
          </Card>

          <Card title="Event stream">
            <List
              size="small"
              dataSource={events}
              locale={{ emptyText: 'No events yet' }}
              renderItem={(e) => (
                <List.Item>
                  <List.Item.Meta
                    avatar={
                      e.status === 'running' ? <LoadingOutlined /> :
                      e.status === 'done' ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> :
                      e.status === 'failed' ? <CloseCircleOutlined style={{ color: '#ff4d4f' }} /> :
                      <ThunderboltOutlined />
                    }
                    title={
                      <Space wrap>
                        <span>{e.title}</span>
                        <Tag>{e.kind}</Tag>
                        <Tag color={e.status === 'done' ? 'success' : e.status === 'running' ? 'processing' : 'default'}>{e.status}</Tag>
                      </Space>
                    }
                    description={e.detail}
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
