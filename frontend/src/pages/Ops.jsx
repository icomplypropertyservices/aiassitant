import React, { useEffect, useMemo, useState } from 'react'
import {
  Card, Row, Col, Typography, Tag, Timeline, Statistic, Space, Button, Empty, Spin, Table, Form, Input, message,
  Switch, InputNumber,
} from 'antd'
import {
  RobotOutlined, UserOutlined, ThunderboltOutlined, ReloadOutlined, ClusterOutlined,
  CheckCircleOutlined, LoadingOutlined, CloseCircleOutlined, PlayCircleOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, connectAuthedWs } from '../api'
import PageHeader from '../components/PageHeader'
import PageShell from '../components/PageShell'

const { Text, Paragraph } = Typography
const { TextArea } = Input


const STATUS_ICON = {
  running: <LoadingOutlined />,
  done: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  failed: <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
}

const STATUS_TAG = {
  done: 'success',
  running: 'processing',
  failed: 'error',
}

export default function Ops() {
  const nav = useNavigate()
  const [snap, setSnap] = useState(null)
  const [loading, setLoading] = useState(true)
  const [planForm] = Form.useForm()
  const [publishing, setPublishing] = useState(false)
  const [autonomy, setAutonomy] = useState(null)
  const [escalations, setEscalations] = useState([])
  const [ticking, setTicking] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [r, a, esc] = await Promise.all([
        api('/ops/visual'),
        api('/ops/autonomy').catch(() => null),
        api('/ops/escalations').catch(() => ({ escalations: [] })),
      ])
      setSnap(r)
      setAutonomy(a)
      setEscalations(esc.escalations || [])
    } catch (e) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  const saveAutonomy = async (patch) => {
    try {
      const r = await api('/ops/autonomy', { method: 'PUT', body: patch })
      setAutonomy((prev) => ({ ...prev, ...r }))
      message.success('Autonomy settings saved')
    } catch (e) {
      message.error(e.message)
    }
  }

  const runTick = async () => {
    setTicking(true)
    try {
      const r = await api('/ops/autonomy/tick', { method: 'POST' })
      message.success(r.result?.reason === 'autonomy_disabled'
        ? 'Autonomy is off — enable the switch to self-run'
        : `Cycle: started ${r.result?.tasks_started || 0}, escalated ${r.result?.escalated || 0}`)
      load()
    } catch (e) {
      message.error(e.message)
    } finally {
      setTicking(false)
    }
  }

  useEffect(() => {
    load()
    let ws
    try {
      ws = connectAuthedWs('/ops/ws')
      ws.onmessage = (ev) => {
        try {
          const m = JSON.parse(ev.data)
          if (m.type === 'auth_ok') return
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
    return {
      orch,
      leads: agents.filter((a) => a.role === 'lead'),
      members: agents.filter((a) => !['orchestrator', 'lead'].includes(a.role)),
      rest: agents.filter((a) => a.role !== 'orchestrator'),
    }
  }, [agents])

  const eventColumns = useMemo(() => [
    {
      title: '',
      key: 'icon',
      width: 36,
      render: (_, e) => STATUS_ICON[e.status] || <ThunderboltOutlined />,
    },
    {
      title: 'Event',
      dataIndex: 'title',
      ellipsis: true,
      render: (title, e) => (
        <div>
          <Text strong style={{ fontSize: 13 }}>{title || '—'}</Text>
          {e.detail ? (
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>{e.detail}</Text>
            </div>
          ) : null}
        </div>
      ),
    },
    {
      title: 'Kind',
      dataIndex: 'kind',
      width: 100,
      render: (k) => (k ? <Tag>{k}</Tag> : '—'),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      width: 100,
      render: (s) => (
        <Tag color={STATUS_TAG[s] || 'default'}>{s || '—'}</Tag>
      ),
    },
  ], [])

  const escalationColumns = useMemo(() => [
    {
      title: 'Reason',
      dataIndex: 'reason_code',
      width: 120,
      render: (code) => <Tag color="orange">{code || 'escalate'}</Tag>,
    },
    {
      title: 'Route',
      key: 'route',
      ellipsis: true,
      render: (_, e) => (
        <Text style={{ fontSize: 13 }}>
          {e.from_agent || e.from_human || '?'} → {e.to_agent || e.to_human || 'owner'}
        </Text>
      ),
    },
    {
      title: 'Detail',
      dataIndex: 'reason_text',
      ellipsis: true,
      render: (t) => t || '—',
    },
  ], [])

  const agentRosterColumns = useMemo(() => [
    {
      title: 'Agent',
      dataIndex: 'name',
      render: (name, a) => (
        <Button type="link" style={{ padding: 0, height: 'auto' }} onClick={() => nav(`/agents/${a.id}`)}>
          <RobotOutlined /> {name}
        </Button>
      ),
    },
    {
      title: 'Role',
      dataIndex: 'role',
      width: 120,
      render: (r) => <Tag color={r === 'orchestrator' ? 'gold' : r === 'lead' ? 'blue' : 'default'}>{r || '—'}</Tag>,
    },
    {
      title: 'Status',
      dataIndex: 'status',
      width: 100,
      render: (s) => <Tag color={s === 'active' ? 'green' : 'orange'}>{s || '—'}</Tag>,
    },
    {
      title: 'Reports to',
      dataIndex: 'parent_id',
      width: 100,
      render: (pid) => (pid ? `#${pid}` : '—'),
    },
  ], [nav])

  const humanRosterColumns = useMemo(() => [
    {
      title: 'Human',
      dataIndex: 'name',
      render: (name) => (
        <Button type="link" style={{ padding: 0, height: 'auto' }} onClick={() => nav('/humans')}>
          <UserOutlined /> {name}
        </Button>
      ),
    },
    {
      title: 'Title',
      dataIndex: 'role_title',
      render: (t) => t || 'teammate',
    },
    {
      title: 'Status',
      dataIndex: 'status',
      width: 100,
      render: (s) => <Tag color={s === 'active' ? 'green' : 'default'}>{s || '—'}</Tag>,
    },
  ], [nav])

  if (loading && !snap) {
    return (
      <PageShell>
        <Card className="aba-soft-card">
          <div style={{ textAlign: 'center', padding: 64 }}>
            <Spin size="large" tip="Loading ops visual…" />
          </div>
        </Card>
      </PageShell>
    )
  }

  return (
    <PageShell>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Card className="aba-soft-card" styles={{ body: { paddingBlock: 16 } }}>
          <PageHeader
            title={<><ThunderboltOutlined /> Live operations</>}
            subtitle="Real-time plans, agent actions, human work, and app usage"
            style={{ marginBottom: 0 }}
            extra={<Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button>}
          />
        </Card>

        <Card
          className="aba-soft-card"
          style={{ border: '1px solid #91caff', background: '#f0f5ff' }}
          title={<><PlayCircleOutlined /> System autonomy — runs itself</>}
          styles={{ header: { textAlign: 'center', background: 'transparent' } }}
        >
          <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap align="start">
            <div style={{ flex: 1, minWidth: 240 }}>
              <Paragraph type="secondary" style={{ marginBottom: 0, maxWidth: 560, textAlign: 'center', marginInline: 'auto' }}>
                When enabled, the workspace processes queued tasks, feeds never-idle agents, and escalates
                work according to each agent/human permission and “when to escalate” policy.
              </Paragraph>
              {autonomy?.last_autonomy_summary && (
                <Text type="secondary" style={{ fontSize: 12, display: 'block', textAlign: 'center', marginTop: 8 }}>
                  Last: {autonomy.last_autonomy_run ? new Date(autonomy.last_autonomy_run).toLocaleString() : '—'}
                  {' · '}{autonomy.last_autonomy_summary}
                </Text>
              )}
            </div>
            <Space wrap style={{ justifyContent: 'center' }}>
              <span>Self-run</span>
              <Switch
                checked={!!autonomy?.autonomy_enabled}
                onChange={(v) => saveAutonomy({ autonomy_enabled: v })}
              />
              <span>Stuck after</span>
              <InputNumber
                min={5}
                max={1440}
                value={autonomy?.task_stuck_minutes || 30}
                onChange={(v) => v && saveAutonomy({ task_stuck_minutes: v })}
                addonAfter="min"
                style={{ width: 120 }}
              />
              <Button type="primary" icon={<ThunderboltOutlined />} loading={ticking} onClick={runTick}>
                Run cycle now
              </Button>
            </Space>
          </Space>
        </Card>

        <Row gutter={[16, 16]}>
          <Col xs={12} md={6}>
            <Card className="aba-stat-card aba-soft-card" size="small">
              <Statistic title="Agents active" value={counts.agents_active || 0} suffix={`/ ${counts.agents || 0}`} prefix={<RobotOutlined />} />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card className="aba-stat-card aba-soft-card" size="small">
              <Statistic title="Humans active" value={counts.humans_active || 0} suffix={`/ ${counts.humans || 0}`} prefix={<UserOutlined />} />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card className="aba-stat-card aba-soft-card" size="small">
              <Statistic title="Open tasks" value={counts.open_tasks || 0} />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card className="aba-stat-card aba-soft-card" size="small">
              <Statistic title="Recent events" value={counts.events_recent || 0} prefix={<ThunderboltOutlined />} />
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={14}>
            <Card
              className="aba-soft-card"
              title={<><ClusterOutlined /> Organisation map</>}
              styles={{ header: { textAlign: 'center' } }}
              style={{ marginBottom: 16, minHeight: 320 }}
            >
            {!agents.length && !humans.length ? (
              <Empty description="No agents or humans yet" />
            ) : (
              <div>
                {layout.orch.length > 0 && (
                  <Card type="inner" size="small" title="Orchestrators" style={{ marginBottom: 12 }}>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
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
                  </Card>
                )}
                <Card type="inner" size="small" title="Leads & specialists" style={{ marginBottom: 12 }}>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
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
                    {!agents.filter((a) => a.role !== 'orchestrator').length && (
                      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No leads or specialists" />
                    )}
                  </div>
                </Card>
                <Card type="inner" size="small" title="Humans">
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
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
                    {!humans.length && (
                      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No humans yet — add them under Humans" />
                    )}
                  </div>
                </Card>
              </div>
            )}
          </Card>

          <Card
            className="aba-soft-card"
            title="Active plans"
            styles={{ header: { textAlign: 'center' } }}
          >
            {!plans.length ? (
              <Empty description="No running plans — agents can announce plans via skills or publish below" />
            ) : (
              plans.map((p) => (
                <Card
                  key={p.plan_id}
                  type="inner"
                  size="small"
                  className="aba-soft-card"
                  style={{ marginBottom: 12 }}
                  title={p.title}
                  styles={{ header: { textAlign: 'center' } }}
                >
                  <Space style={{ marginBottom: 8, width: '100%', justifyContent: 'center' }}>
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
          <Card
            className="aba-soft-card"
            title="Publish plan"
            styles={{ header: { textAlign: 'center' } }}
            style={{ marginBottom: 16 }}
          >
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

          <Card
            className="aba-soft-card"
            title="Event stream"
            styles={{
              header: { textAlign: 'center' },
              body: { paddingTop: 8, maxHeight: 420, overflowY: 'auto', overflowX: 'auto' },
            }}
            style={{ marginBottom: 16 }}
          >
            <Table
              size="small"
              rowKey={(r, i) => r.id || `evt-${i}`}
              pagination={false}
              dataSource={events}
              columns={eventColumns}
              scroll={{ x: 360 }}
              onRow={(record) => ({
                className: 'aba-click-row',
                style: { cursor: 'pointer' },
                onClick: () => {
                  if (record?.agent_id) nav(`/console/${record.agent_id}`)
                  else if (record?.payload?.agent_id) nav(`/console/${record.payload.agent_id}`)
                },
              })}
              locale={{
                emptyText: (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No events yet" />
                ),
              }}
            />
          </Card>

          <Card
            className="aba-soft-card"
            title="Escalations"
            styles={{
              header: { textAlign: 'center' },
              body: { paddingTop: 8, maxHeight: 320, overflowY: 'auto', overflowX: 'auto' },
            }}
          >
            <Table
              size="small"
              rowKey={(r, i) => r.id || `esc-${i}`}
              pagination={false}
              dataSource={escalations}
              columns={escalationColumns}
              scroll={{ x: 360 }}
              locale={{
                emptyText: (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No escalations yet" />
                ),
              }}
            />
          </Card>
        </Col>
      </Row>

        {/* Roster tables — agents & humans as Card-wrapped Tables */}
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={14}>
            <Card
              className="aba-soft-card"
              title={<><RobotOutlined /> Agent roster</>}
              styles={{ header: { textAlign: 'center' }, body: { paddingTop: 8, overflowX: 'auto' } }}
            >
              <Table
                size="small"
                rowKey="id"
                pagination={agents.length > 12 ? { pageSize: 12 } : false}
                dataSource={agents}
                columns={agentRosterColumns}
                scroll={{ x: 480 }}
                locale={{
                  emptyText: (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No agents yet" />
                  ),
                }}
                onRow={(a) => ({
                  onClick: () => nav(`/agents/${a.id}`),
                  style: { cursor: 'pointer' },
                })}
              />
            </Card>
          </Col>
          <Col xs={24} lg={10}>
            <Card
              className="aba-soft-card"
              title={<><UserOutlined /> Human roster</>}
              styles={{ header: { textAlign: 'center' }, body: { paddingTop: 8, overflowX: 'auto' } }}
            >
              <Table
                size="small"
                rowKey="id"
                pagination={humans.length > 12 ? { pageSize: 12 } : false}
                dataSource={humans}
                columns={humanRosterColumns}
                scroll={{ x: 320 }}
                locale={{
                  emptyText: (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description="No humans yet — add them under Humans"
                    />
                  ),
                }}
                onRow={() => ({
                  onClick: () => nav('/humans'),
                  style: { cursor: 'pointer' },
                })}
              />
            </Card>
          </Col>
        </Row>
      </Space>
    </PageShell>
  )
}
