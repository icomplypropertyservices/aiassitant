import React, { useEffect, useState } from 'react'
import {
  Row, Col, Card, Statistic, List, Button, Space, Typography, Tag, Spin, Alert, Progress,
} from 'antd'
import {
  MessageOutlined, ThunderboltOutlined, RobotOutlined,
  PlusOutlined, CheckSquareOutlined, ApartmentOutlined,
  CheckCircleFilled, CheckCircleOutlined, CrownOutlined,
  BankOutlined, TeamOutlined, SafetyCertificateOutlined, UserOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, getUser } from '../api'
import PageHeader from '../components/PageHeader'

export default function Dashboard() {
  const nav = useNavigate()
  const [data, setData] = useState(null)
  const [agents, setAgents] = useState([])
  const [board, setBoard] = useState(null)
  const [companies, setCompanies] = useState([])
  const [projects, setProjects] = useState([])
  const [keysConfigured, setKeysConfigured] = useState(false)
  const [checklistReady, setChecklistReady] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = () => {
    setLoading(true)
    setError(null)
    Promise.all([
      api('/dashboard/'),
      api('/agents/').catch(() => []),
      api('/agents/tasks/board').catch(() => null),
      api('/org/companies').catch(() => []),
      api('/org/projects').catch(() => []),
      api('/keys').catch(() => ({ keys: [] })),
    ])
      .then(([dash, a, b, cos, projs, k]) => {
        setData(dash)
        setAgents(a || [])
        setBoard(b)
        setCompanies(cos || [])
        setProjects(projs || [])
        const keyList = k?.keys || []
        setKeysConfigured(keyList.some(x => x.configured || x.id))
        setChecklistReady(true)
      })
      .catch(e => {
        setError(e.message || 'Failed to load dashboard')
        setData(null)
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  if (loading && !data) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" tip="Loading dashboard…" />
      </div>
    )
  }

  if (error && !data) {
    return (
      <Alert
        type="error"
        showIcon
        message="Could not load dashboard"
        description={error}
        action={<Button onClick={load}>Retry</Button>}
      />
    )
  }

  const hasCompany = companies.length > 0
  const hasProject = projects.length > 0
  const hasLead = agents.some(a => a.is_lead || a.hierarchy_role === 'lead')
  const hasChat = (data?.recent_conversations || []).length > 0 || agents.length > 0
  const requiredDone = [hasCompany, hasProject, hasLead, hasChat].filter(Boolean).length
  const showChecklist = checklistReady && requiredDone < 4
  const firstAgent = agents[0]
  const firstLead = agents.find(a => a.is_lead || a.hierarchy_role === 'lead')

  const checklist = [
    {
      key: 'company',
      title: 'Create a company',
      done: hasCompany,
      action: () => nav('/workspace'),
      label: 'Open Workspace',
    },
    {
      key: 'project',
      title: 'Create a project',
      done: hasProject,
      action: () => nav('/workspace'),
      label: 'Open Workspace',
    },
    {
      key: 'lead',
      title: 'Create a lead agent',
      done: hasLead,
      action: () => nav(firstLead ? `/agents/${firstLead.id}` : '/agents'),
      label: hasLead ? 'Open lead' : 'Create agents',
      extra: () => nav('/hierarchy'),
      extraLabel: 'Or open Hierarchy',
    },
    {
      key: 'chat',
      title: 'Start a chat',
      done: hasChat,
      action: () => nav(firstAgent ? `/agents/${firstAgent.id}` : '/chat'),
      label: firstAgent ? 'Chat with agent' : 'AI Chat',
    },
    {
      key: 'keys',
      title: 'Add API keys (optional)',
      done: keysConfigured,
      optional: true,
      action: () => nav('/settings'),
      label: 'Settings vault',
    },
  ]

  return (
    <div>
      {error && (
        <Alert type="warning" showIcon closable message={error} style={{ marginBottom: 16 }} onClose={() => setError(null)} />
      )}
      <PageHeader
        title={`Welcome back${getUser()?.name ? `, ${getUser().name}` : ''}`}
        subtitle="Your workspace overview — companies, agents, tasks and token usage in one place."
        extra={
          <Space wrap>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => nav('/console')}>Create agent</Button>
            <Button icon={<MessageOutlined />} onClick={() => nav('/chat')}>AI Chat</Button>
          </Space>
        }
      />

      {showChecklist && (
        <Card
          className="aba-soft-card"
          title={
            <Space>
              Getting started
              <Tag color="blue">{requiredDone}/4 required</Tag>
              <Progress type="circle" percent={Math.round((requiredDone / 4) * 100)} width={28} />
            </Space>
          }
          style={{ marginBottom: 16 }}
        >
          <List
            dataSource={checklist}
            renderItem={item => (
              <List.Item
                actions={
                  item.done
                    ? [<Tag key="ok" color="success">Done</Tag>]
                    : [
                        <Button key="go" type="link" onClick={item.action}>{item.label}</Button>,
                        item.extra && (
                          <Button key="ex" type="link" onClick={item.extra}>{item.extraLabel}</Button>
                        ),
                      ].filter(Boolean)
                }
              >
                <List.Item.Meta
                  avatar={
                    item.done
                      ? <CheckCircleFilled style={{ color: '#52c41a', fontSize: 18 }} />
                      : <CheckCircleOutlined style={{ color: '#bfbfbf', fontSize: 18 }} />
                  }
                  title={
                    <Space>
                      <span style={{ opacity: item.done ? 0.65 : 1 }}>{item.title}</span>
                      {item.optional && <Tag>Optional</Tag>}
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        </Card>
      )}

      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Card className="aba-stat-card" hoverable onClick={() => nav('/console')}>
            <Statistic title="Active agents" value={agents.length} prefix={<RobotOutlined style={{ color: '#7c3aed' }} />} />
            <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>
              {agents.length >= 15 ? 'Full professional team' : 'Click to open team →'}
            </div>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card className="aba-stat-card"><Statistic title="Messages today" value={data?.messages_today ?? 0} prefix={<MessageOutlined style={{ color: '#1668dc' }} />} /></Card>
        </Col>
        <Col xs={12} md={6}>
          <Card className="aba-stat-card"><Statistic title="Tokens used" value={data?.tokens_used ?? 0} prefix={<ThunderboltOutlined style={{ color: '#d97706' }} />} /></Card>
        </Col>
        <Col xs={12} md={6}>
          <Card className="aba-stat-card">
            <Statistic
              title="Open tasks"
              value={(board?.counts?.todo || 0) + (board?.counts?.queued || 0) + (board?.counts?.in_progress || 0)}
              prefix={<CheckSquareOutlined style={{ color: '#16a34a' }} />}
            />
          </Card>
        </Col>
      </Row>

      <Space wrap style={{ margin: '16px 0' }}>
        <Button icon={<CheckSquareOutlined />} onClick={() => nav('/tasks')}>Tasks board</Button>
        <Button icon={<ApartmentOutlined />} onClick={() => nav('/workspace')}>Workspace</Button>
        <Button icon={<TeamOutlined />} onClick={() => nav('/humans')}>Users / Team</Button>
        <Button icon={<SafetyCertificateOutlined />} onClick={() => nav('/permissions')}>Permissions</Button>
        <Button icon={<UserOutlined />} onClick={() => nav('/profile')}>Profile</Button>
        <Button onClick={() => nav('/templates')}>Templates</Button>
        <Button onClick={() => nav('/hierarchy')}>Hierarchy</Button>
      </Space>

      {companies.length > 0 && (
        <Card
          title="Companies"
          extra={<Button type="link" onClick={() => nav('/workspace')}>Workspace</Button>}
          style={{ marginBottom: 16 }}
        >
          <List
            dataSource={companies.slice(0, 6)}
            renderItem={(c) => (
              <List.Item
                style={{ cursor: 'pointer' }}
                onClick={() => nav(`/companies/${c.id}`)}
                actions={[
                  <Tag key="p">{c.project_count ?? 0} projects</Tag>,
                  <Button key="g" type="link" size="small" onClick={(e) => { e.stopPropagation(); nav(`/companies/${c.id}`) }}>
                    P&amp;L / profile
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  avatar={<BankOutlined style={{ fontSize: 18, color: '#1668dc' }} />}
                  title={c.name}
                  description={c.industry || 'Open company profile for AI cost, pipeline & profit'}
                />
              </List.Item>
            )}
          />
        </Card>
      )}

      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Card
            title="Your agents"
            extra={<Button type="link" onClick={() => nav('/console')}>Console</Button>}
            style={{ marginBottom: 16 }}
          >
            <List
              dataSource={agents.slice(0, 5)}
              locale={{ emptyText: 'No agents yet' }}
              renderItem={a => (
                <List.Item
                  style={{ cursor: 'pointer' }}
                  onClick={() => nav(`/agents/${a.id}`)}
                  actions={[
                    (a.is_lead || a.hierarchy_role === 'lead') && <Tag key="l" color="gold" icon={<CrownOutlined />}>Lead</Tag>,
                    <Tag key="s" color={a.status === 'active' ? 'green' : 'orange'}>{a.status}</Tag>,
                  ].filter(Boolean)}
                >
                  <List.Item.Meta
                    avatar={<RobotOutlined style={{ fontSize: 20, color: '#1668dc' }} />}
                    title={a.name}
                    description={`${a.template_type} · ${a.stats?.open || 0} open tasks — click for live chat`}
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card title="Task pipeline" extra={<Button type="link" onClick={() => nav('/tasks')}>Board</Button>}>
            <Space wrap size="large">
              {['todo', 'queued', 'in_progress', 'review', 'completed'].map(k => (
                <Statistic key={k} title={k.replace('_', ' ')} value={board?.counts?.[k] || 0} />
              ))}
            </Space>
          </Card>
          <Card title="Recent conversations" style={{ marginTop: 16 }}>
            <List
              dataSource={data?.recent_conversations || []}
              locale={{ emptyText: 'No conversations yet' }}
              renderItem={c => (
                <List.Item style={{ cursor: 'pointer' }} onClick={() => nav('/chat', { state: { conversation_id: c.id } })}>
                  <MessageOutlined style={{ marginRight: 8 }} /> {c.title}
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
