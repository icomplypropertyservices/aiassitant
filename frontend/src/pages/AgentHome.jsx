import React, { useCallback, useEffect, useState } from 'react'
import {
  Card, Row, Col, Statistic, List, Tag, Space, Typography, Button, Spin, Empty,
  Alert, InputNumber, Input, message, Progress,
} from 'antd'
import {
  RobotOutlined, ThunderboltOutlined, CheckSquareOutlined, ReloadOutlined,
  MessageOutlined, SettingOutlined, PlayCircleOutlined, ApartmentOutlined,
  RocketOutlined, WarningOutlined, DashboardOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import PageShell from '../components/PageShell'
import ModelSelect from '../components/ModelSelect'
import { modelLabel } from '../models'

const { Text, Paragraph } = Typography

function taskStatusColor(s) {
  const v = (s || '').toLowerCase()
  if (v === 'completed') return 'success'
  if (v === 'failed') return 'error'
  if (v === 'in_progress' || v === 'queued') return 'processing'
  if (v === 'review') return 'warning'
  return 'default'
}

/**
 * Per-agent dashboard: stats, model settings, multi-agent workflows, tasks, activity.
 * Route: /agents/:id/dash
 */
export default function AgentHome() {
  const { id } = useParams()
  const nav = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [data, setData] = useState(null)
  const [wfBusy, setWfBusy] = useState(null)
  const [patBusy, setPatBusy] = useState(null)
  const [counts, setCounts] = useState({})
  const [niches, setNiches] = useState({})
  const [modelSaving, setModelSaving] = useState(false)
  const [modelPick, setModelPick] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api(`/agents/${id}/dashboard`)
      .then((d) => {
        setData(d)
        setModelPick(d?.settings?.model || d?.agent?.model || 'quality')
        const init = {}
        for (const w of d?.workflows || d?.all_workflows || []) {
          init[w.id] = w.default_count || 50
        }
        setCounts((prev) => ({ ...init, ...prev }))
      })
      .catch((e) => setError(e?.message || 'Failed to load agent dashboard'))
      .finally(() => setLoading(false))
  }, [id])

  useEffect(() => {
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [load])

  const saveModel = async (value) => {
    if (!value) return
    setModelSaving(true)
    try {
      await api(`/agents/${id}`, {
        method: 'PATCH',
        body: { model: value },
      })
      message.success(`Model set to ${modelLabel(value)}`)
      setModelPick(value)
      load()
    } catch (e) {
      message.error(e.message || 'Could not update model')
    } finally {
      setModelSaving(false)
    }
  }

  const upgradeModel = async () => {
    const rec = data?.settings?.recommended_model || 'quality'
    await saveModel(rec)
  }

  const runWorkflow = async (workflowId) => {
    setWfBusy(workflowId)
    try {
      const body = {
        workflow_id: workflowId,
        agent_id: Number(id),
        count: counts[workflowId] || undefined,
        niche: niches[workflowId] || '',
        priority: 'high',
      }
      const r = await api('/agents/workflows/run', { method: 'POST', body })
      const parentId = r?.parent_task_id || r?.task_id || r?.parent?.id
      const n = (r?.children || r?.steps || []).length
      message.success(
        parentId
          ? `Workflow started — goal #${parentId}${n ? ` with ${n} steps` : ''}`
          : 'Workflow started',
      )
      load()
      nav('/tasks')
    } catch (e) {
      message.error(e.message || 'Workflow failed to start')
    } finally {
      setWfBusy(null)
    }
  }

  const runPattern = async (patternId) => {
    setPatBusy(patternId)
    try {
      const r = await api('/agents/patterns/run', {
        method: 'POST',
        body: { pattern_id: patternId, agent_id: Number(id), priority: 'high' },
      })
      const parentId = r?.parent_task_id || r?.workflow?.parent_task_id
      message.success(
        parentId
          ? `Pattern started as workflow #${parentId}`
          : (r?.message || 'Pattern started'),
      )
      load()
      nav('/tasks')
    } catch (e) {
      message.error(e.message || 'Pattern run failed')
    } finally {
      setPatBusy(null)
    }
  }

  if (loading && !data) {
    return (
      <PageShell title="Agent dashboard" showBack backTo="/agent-dash">
        <div style={{ textAlign: 'center', padding: 64 }}>
          <Spin size="large" tip="Loading agent…" />
        </div>
      </PageShell>
    )
  }

  const agent = data?.agent
  const settings = data?.settings || {}
  const stats = data?.stats || {}
  const workflows = data?.workflows || data?.all_workflows || []
  const patterns = data?.patterns || []
  const tasks = data?.tasks || []
  const activity = data?.activity || []
  const openPct = stats.total
    ? Math.round(((stats.completed || 0) / Math.max(stats.total, 1)) * 100)
    : 0

  return (
    <PageShell
      title={agent?.name || 'Agent'}
      subtitle="Dashboard · model · workflows · tasks"
      showBack
      backTo="/agent-dash"
      extra={(
        <Space wrap>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>Refresh</Button>
          <Button icon={<MessageOutlined />} onClick={() => nav(`/agents/${id}`)}>Chat</Button>
          <Button icon={<SettingOutlined />} onClick={() => nav(`/agents/${id}/manage`)}>
            Full settings
          </Button>
        </Space>
      )}
    >
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {error && (
          <Alert
            type="error"
            showIcon
            message={error}
            action={<Button size="small" onClick={load}>Retry</Button>}
          />
        )}

        {settings.model_upgrade_suggested && (
          <Alert
            type="warning"
            showIcon
            icon={<WarningOutlined />}
            message="This agent is on a weak model and may not finish multi-step work"
            description={(
              <span>
                Current: <Text code>{modelLabel(settings.model)}</Text>
                {' → recommended: '}
                <Text code>{modelLabel(settings.recommended_model)}</Text>
                {' for CRM, emails, and goal chains.'}
              </span>
            )}
            action={(
              <Button type="primary" size="small" onClick={upgradeModel} loading={modelSaving}>
                Upgrade to {modelLabel(settings.recommended_model)}
              </Button>
            )}
          />
        )}

        <Row gutter={[12, 12]}>
          <Col xs={12} sm={8} md={4}>
            <Card className="aba-soft-card" size="small">
              <Statistic title="Open work" value={stats.open || 0} prefix={<ThunderboltOutlined />} />
            </Card>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Card className="aba-soft-card" size="small">
              <Statistic title="In progress" value={stats.in_progress || 0} valueStyle={{ color: '#1668dc' }} />
            </Card>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Card className="aba-soft-card" size="small">
              <Statistic title="Queued" value={stats.queued || 0} />
            </Card>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Card className="aba-soft-card" size="small">
              <Statistic
                title="Completed"
                value={stats.completed || 0}
                valueStyle={{ color: '#16a34a' }}
                prefix={<CheckSquareOutlined />}
              />
            </Card>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Card className="aba-soft-card" size="small">
              <Statistic title="Failed" value={stats.failed || 0} valueStyle={{ color: stats.failed ? '#dc2626' : undefined }} />
            </Card>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Card className="aba-soft-card" size="small">
              <Statistic title="Tokens (recent)" value={stats.tokens_used || 0} />
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={10}>
            <Card
              className="aba-soft-card"
              title={(
                <Space>
                  <DashboardOutlined />
                  <span>Agent settings</span>
                </Space>
              )}
              extra={(
                <Button type="link" size="small" onClick={() => nav(`/agents/${id}/manage`)}>
                  All config
                </Button>
              )}
            >
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>Status</Text>
                  <div>
                    <Tag color={agent?.status === 'active' ? 'success' : 'default'}>
                      {agent?.status || 'unknown'}
                    </Tag>
                    {settings.hierarchy_role && <Tag>{settings.hierarchy_role}</Tag>}
                    {settings.template_type && <Tag color="blue">{settings.template_type}</Tag>}
                    {settings.never_idle && <Tag color="purple">never idle</Tag>}
                  </div>
                </div>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>Permission</Text>
                  <div><Tag>{settings.permission_level || 'operator'}</Tag></div>
                </div>
                <div>
                  <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                    Model (use Quality or better so skills actually run)
                  </Text>
                  <Space wrap>
                    <ModelSelect
                      value={modelPick}
                      onChange={(v) => {
                        setModelPick(v)
                        saveModel(v)
                      }}
                      style={{ minWidth: 200 }}
                      disabled={modelSaving}
                    />
                  </Space>
                </div>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>Escalate</Text>
                  <div>
                    <Text style={{ fontSize: 13 }}>
                      {settings.escalate_when || 'on_failure'} → {settings.escalate_to || 'parent'}
                    </Text>
                  </div>
                </div>
                {stats.total > 0 && (
                  <div>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      Completion (last {stats.total} tasks)
                    </Text>
                    <Progress percent={openPct} size="small" strokeColor="#16a34a" />
                  </div>
                )}
                <Space wrap>
                  <Button
                    type="primary"
                    icon={<MessageOutlined />}
                    onClick={() => nav(`/agents/${id}`)}
                  >
                    Chat
                  </Button>
                  <Button
                    icon={<SettingOutlined />}
                    onClick={() => nav(`/agents/${id}/manage`)}
                  >
                    Skills & config
                  </Button>
                  <Button
                    icon={<ApartmentOutlined />}
                    onClick={() => nav('/business')}
                  >
                    CRM
                  </Button>
                </Space>
              </Space>
            </Card>
          </Col>

          <Col xs={24} lg={14}>
            <Card
              className="aba-soft-card"
              title={(
                <Space>
                  <RocketOutlined />
                  <span>Multi-agent workflows</span>
                </Space>
              )}
              extra={(
                <Text type="secondary" style={{ fontSize: 12 }}>
                  Hand off between agents automatically
                </Text>
              )}
            >
              <Paragraph type="secondary" style={{ marginTop: 0 }}>
                Example: <Text strong>get 50 sales targets → save in CRM</Text>
                {' → '}
                <Text strong>second agent emails, calls, updates pipeline</Text>.
                Autonomy runs each step in order.
              </Paragraph>
              {workflows.length === 0 ? (
                <Empty description="No workflows for this role" />
              ) : (
                <List
                  dataSource={workflows}
                  renderItem={(w) => (
                    <List.Item
                      key={w.id}
                      actions={[
                        <Button
                          key="run"
                          type="primary"
                          size="small"
                          icon={<PlayCircleOutlined />}
                          loading={wfBusy === w.id}
                          onClick={() => runWorkflow(w.id)}
                        >
                          Run
                        </Button>,
                      ]}
                    >
                      <List.Item.Meta
                        title={(
                          <Space wrap>
                            <Text strong>{w.name}</Text>
                            {w.category && <Tag color="geekblue">{w.category}</Tag>}
                          </Space>
                        )}
                        description={(
                          <div>
                            <Paragraph type="secondary" style={{ marginBottom: 8, fontSize: 13 }}>
                              {w.description}
                            </Paragraph>
                            {(w.steps_preview || []).length > 0 && (
                              <div style={{ marginBottom: 8 }}>
                                {(w.steps_preview || []).map((s, i) => (
                                  <Tag key={i} style={{ marginBottom: 4 }}>{i + 1}. {s}</Tag>
                                ))}
                              </div>
                            )}
                            {(w.params || []).some((p) => p.key === 'count' || p.key === 'batch') && (
                              <Space wrap size="middle">
                                <span>
                                  <Text type="secondary" style={{ fontSize: 12, marginRight: 8 }}>
                                    Targets / batch
                                  </Text>
                                  <InputNumber
                                    min={5}
                                    max={100}
                                    value={counts[w.id] ?? w.default_count ?? 50}
                                    onChange={(v) => setCounts((c) => ({ ...c, [w.id]: v }))}
                                  />
                                </span>
                                {(w.params || []).some((p) => p.key === 'niche') && (
                                  <Input
                                    placeholder="Niche / ICP (optional)"
                                    style={{ maxWidth: 260 }}
                                    value={niches[w.id] || ''}
                                    onChange={(e) => setNiches((n) => ({ ...n, [w.id]: e.target.value }))}
                                    allowClear
                                  />
                                )}
                              </Space>
                            )}
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
              title={(
                <Space>
                  <CheckSquareOutlined />
                  <span>Team patterns (lead recipes)</span>
                </Space>
              )}
              extra={(
                <Text type="secondary" style={{ fontSize: 12 }}>
                  create_pattern · run_pattern · checklists
                </Text>
              )}
            >
              <Paragraph type="secondary" style={{ marginTop: 0, fontSize: 13 }}>
                Leads save reusable steps with <Text code>create_pattern</Text>.
                Each step lists <Text strong>what will be checked</Text>.
                After work, <Text code>review_task</Text> approve/reject with what&apos;s wrong.
              </Paragraph>
              {patterns.length === 0 ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="No patterns yet — ask a lead to create_pattern or create_workflow with save_as_pattern"
                />
              ) : (
                <List
                  size="small"
                  dataSource={patterns}
                  renderItem={(p) => (
                    <List.Item
                      actions={[
                        <Button
                          key="run"
                          type="link"
                          size="small"
                          icon={<PlayCircleOutlined />}
                          loading={patBusy === p.id}
                          onClick={() => runPattern(p.id)}
                        >
                          Run
                        </Button>,
                      ]}
                    >
                      <List.Item.Meta
                        title={(
                          <Space wrap>
                            <Text strong>{p.name}</Text>
                            <Tag>{p.step_count || 0} steps</Tag>
                            {p.category && <Tag color="purple">{p.category}</Tag>}
                          </Space>
                        )}
                        description={(
                          <div>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              {p.description || 'Work pattern'}
                            </Text>
                            {(p.steps_preview || []).length > 0 && (
                              <div style={{ marginTop: 4 }}>
                                {(p.steps_preview || []).map((s, i) => (
                                  <Tag key={i} style={{ marginBottom: 2 }}>{s}</Tag>
                                ))}
                              </div>
                            )}
                            {(p.checklist || []).length > 0 && (
                              <div style={{ marginTop: 4 }}>
                                <Text type="secondary" style={{ fontSize: 11 }}>Checks: </Text>
                                {(p.checklist || []).slice(0, 4).map((c, i) => (
                                  <Tag key={i} color="orange" style={{ fontSize: 11 }}>{c}</Tag>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      />
                    </List.Item>
                  )}
                />
              )}
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <Card
              className="aba-soft-card"
              title={<Space><CheckSquareOutlined /><span>Recent tasks</span></Space>}
              extra={<Button type="link" size="small" onClick={() => nav('/tasks')}>Board</Button>}
              styles={{ body: { maxHeight: 360, overflowY: 'auto' } }}
            >
              {tasks.length === 0 ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No tasks yet — run a workflow" />
              ) : (
                <List
                  size="small"
                  dataSource={tasks}
                  renderItem={(t) => (
                    <List.Item>
                      <Space direction="vertical" size={0} style={{ width: '100%' }}>
                        <Space wrap>
                          <Tag color={taskStatusColor(t.status)}>{t.status}</Tag>
                          {(t.labels || '').includes('auto-chain') && <Tag color="purple">chain</Tag>}
                          {(t.labels || '').includes('post-chat') && <Tag color="gold">post-chat</Tag>}
                          {(t.labels || '').includes('needs-review') && <Tag color="orange">needs review</Tag>}
                          {(t.labels || '').includes('has-feedback') && <Tag color="red">fix feedback</Tag>}
                        </Space>
                        <Text style={{ fontSize: 13 }}>#{t.id} {t.title || 'Untitled'}</Text>
                      </Space>
                    </List.Item>
                  )}
                />
              )}
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card
              className="aba-soft-card"
              title={<Space><ThunderboltOutlined /><span>Live activity</span></Space>}
              styles={{ body: { maxHeight: 360, overflowY: 'auto' } }}
            >
              {activity.length === 0 ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No activity yet" />
              ) : (
                <List
                  size="small"
                  dataSource={activity}
                  renderItem={(ev) => (
                    <List.Item>
                      <List.Item.Meta
                        title={(
                          <Space>
                            <Tag>{ev.type || 'info'}</Tag>
                            <Text style={{ fontSize: 13 }}>{(ev.message || '').slice(0, 120)}</Text>
                          </Space>
                        )}
                        description={
                          ev.created_at
                            ? <Text type="secondary" style={{ fontSize: 11 }}>{new Date(ev.created_at).toLocaleString()}</Text>
                            : null
                        }
                      />
                    </List.Item>
                  )}
                />
              )}
            </Card>
          </Col>
        </Row>

        <Card className="aba-soft-card" size="small">
          <Space wrap>
            <RobotOutlined />
            <Text type="secondary">
              Tip: Chat the orchestrator with “Get 50 sales targets and save in CRM, then email and call them”
              — auto-chain uses the same multi-agent sales workflow. Prefer model{' '}
              <Text code>Quality</Text> or higher on sales and outreach agents.
            </Text>
          </Space>
        </Card>
      </Space>
    </PageShell>
  )
}
