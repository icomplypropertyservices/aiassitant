import React, { useEffect, useState } from 'react'
import {
  Row, Col, Card, Statistic, List, Button, Space, Typography, Tag, Spin, Alert, Progress, Empty,
} from 'antd'
import {
  MessageOutlined, ThunderboltOutlined, RobotOutlined,
  PlusOutlined, CheckSquareOutlined, ApartmentOutlined,
  CheckCircleFilled, CheckCircleOutlined, CrownOutlined,
  BankOutlined, TeamOutlined, SafetyCertificateOutlined, UserOutlined,
  CommentOutlined, NodeIndexOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, getUser } from '../api'
import PageHeader from '../components/PageHeader'
import PageShell from '../components/PageShell'
import { LogoLoading } from '../components/BrandLogo'
import SystemNav from '../components/SystemNav'
import CoreTeam from '../components/CoreTeam'
import { goBay, goMarketing } from '../publicPaths'

/**
 * Dashboard — every block lives inside an Ant Design Card within the
 * centered page shell (aba-page-center / aba-page-shell / aba-page-shell-inner).
 * Goal / auto-chain open-task counts come from the tasks board API.
 */
export default function Dashboard() {
  const nav = useNavigate()
  const [data, setData] = useState(null)
  const [agents, setAgents] = useState([])
  const [board, setBoard] = useState(null)
  const [companies, setCompanies] = useState([])
  const [projects, setProjects] = useState([])
  const [keysConfigured, setKeysConfigured] = useState(false)
  const [checklistReady, setChecklistReady] = useState(false)
  const [meetingsCount, setMeetingsCount] = useState(null)
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
      api('/meetings/').catch(() => null),
    ])
      .then(([dash, a, b, cos, projs, k, meetings]) => {
        setData(dash)
        setAgents(Array.isArray(a) ? a : [])
        setBoard(b)
        setCompanies(Array.isArray(cos) ? cos : (cos?.companies || []))
        setProjects(Array.isArray(projs) ? projs : (projs?.projects || []))
        const keyList = Array.isArray(k?.keys) ? k.keys : []
        setKeysConfigured(keyList.some(x => x.configured || x.id))
        setChecklistReady(true)
        if (meetings != null) {
          const list = Array.isArray(meetings)
            ? meetings
            : (Array.isArray(meetings.rooms) ? meetings.rooms
              : Array.isArray(meetings.meetings) ? meetings.meetings
                : Array.isArray(meetings.items) ? meetings.items
                  : [])
          const n = typeof meetings.count === 'number' ? meetings.count : list.length
          setMeetingsCount(n)
        } else {
          setMeetingsCount(null)
        }
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
      <PageShell>
        <Card className="aba-soft-card">
          <LogoLoading tip="Loading home…" minHeight={320} />
        </Card>
      </PageShell>
    )
  }

  if (error && !data) {
    return (
      <PageShell>
        <Card className="aba-soft-card">
          <Alert
            type="error"
            showIcon
            message="Could not load dashboard"
            description={error}
            action={<Button onClick={load}>Retry</Button>}
          />
        </Card>
      </PageShell>
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

  // Open goal / auto-chain tasks (labels from task_chain) when board API is available
  let openGoalChainCount = 0
  if (board?.columns) {
    for (const st of ['todo', 'queued', 'in_progress']) {
      for (const t of board.columns[st] || []) {
        const labels = String(t.labels || '').toLowerCase()
        if (labels.includes('goal') || labels.includes('auto-chain')) openGoalChainCount += 1
      }
    }
  }

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

  const openTasks =
    (board?.counts?.todo || 0) + (board?.counts?.queued || 0) + (board?.counts?.in_progress || 0)

  const quickActions = [
    {
      key: 'agents',
      label: 'Agents',
      icon: <RobotOutlined />,
      type: 'primary',
      onClick: () => nav('/console'),
    },
    {
      key: 'tasks',
      label: 'Tasks',
      icon: <CheckSquareOutlined />,
      onClick: () => nav('/tasks'),
    },
    {
      key: 'business',
      label: 'Business',
      icon: <BankOutlined />,
      onClick: () => nav('/business'),
    },
    {
      key: 'chat',
      label: 'AI Chat',
      icon: <MessageOutlined />,
      onClick: () => nav('/chat'),
    },
  ]

  return (
    <PageShell>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {/* Welcome header — Card */}
        <Card className="aba-soft-card" styles={{ body: { paddingBlock: 16 } }}>
          <PageHeader
            title={`Welcome back${getUser()?.name ? `, ${getUser().name}` : ''}`}
            subtitle="Your workspace overview — companies, agents, tasks and token usage in one place."
            style={{ marginBottom: 0 }}
            extra={
              <Space wrap className="aba-v2-header-extra-desktop">
                <Button type="primary" icon={<PlusOutlined />} onClick={() => nav('/console')}>
                  Create agent
                </Button>
                <Button icon={<MessageOutlined />} onClick={() => nav('/chat')}>
                  AI Chat
                </Button>
              </Space>
            }
          />
          {/* Mobile-first primary actions (2×2 → 4-col from 480px) */}
          <div className="aba-v2-quick-actions" style={{ marginTop: 14 }}>
            {quickActions.map((a) => (
              <Button
                key={a.key}
                type={a.type || 'default'}
                className="aba-v2-quick-actions__btn"
                icon={a.icon}
                onClick={a.onClick}
                block
              >
                <span className="aba-v2-quick-actions__label">{a.label}</span>
              </Button>
            ))}
          </div>
        </Card>

        {error && (
          <Card className="aba-soft-card">
            <Alert
              type="warning"
              showIcon
              closable
              message={error}
              action={<Button size="small" onClick={load}>Retry</Button>}
              onClose={() => setError(null)}
            />
          </Card>
        )}

        {showChecklist && (
          <Card
            className="aba-soft-card"
            title={
              <Space wrap>
                Getting started
                <Tag color="blue">{requiredDone}/4 required</Tag>
                <Progress type="circle" percent={Math.round((requiredDone / 4) * 100)} width={28} />
              </Space>
            }
          >
            <List
              dataSource={checklist}
              renderItem={item => (
                <List.Item
                  className="aba-click-row"
                  onClick={() => { item.action?.() }}
                  actions={
                    item.done
                      ? [
                          <Tag key="ok" color="success">Done</Tag>,
                          <Button key="go" type="link" className="aba-touch-btn" onClick={(e) => { e.stopPropagation(); item.action?.() }}>{item.label}</Button>,
                        ]
                      : [
                          <Button key="go" type="link" className="aba-touch-btn" onClick={(e) => { e.stopPropagation(); item.action?.() }}>{item.label}</Button>,
                          item.extra && (
                            <Button key="ex" type="link" className="aba-touch-btn" onClick={(e) => { e.stopPropagation(); item.extra?.() }}>{item.extraLabel}</Button>
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

        {/* KPI stats — each metric is its own Card */}
        <Row gutter={[16, 16]}>
          <Col xs={12} md={6}>
            <Card className="aba-stat-card aba-soft-card aba-card-clickable" hoverable onClick={() => nav('/console')}>
              <Statistic
                title="Active agents"
                value={agents.length}
                prefix={<RobotOutlined style={{ color: '#7c3aed' }} />}
              />
              <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
                {agents.length >= 15 ? 'Full professional team' : 'Click to open team →'}
              </Typography.Text>
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card className="aba-stat-card aba-soft-card aba-card-clickable" hoverable onClick={() => nav('/chat')}>
              <Statistic
                title="Messages today"
                value={data?.messages_today ?? 0}
                prefix={<MessageOutlined style={{ color: '#1668dc' }} />}
              />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card className="aba-stat-card aba-soft-card aba-card-clickable" hoverable onClick={() => nav('/billing')}>
              <Statistic
                title="Tokens used"
                value={data?.tokens_used ?? 0}
                prefix={<ThunderboltOutlined style={{ color: '#d97706' }} />}
              />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card className="aba-stat-card aba-soft-card aba-card-clickable" hoverable onClick={() => nav('/tasks')}>
              <Statistic
                title="Open tasks"
                value={openTasks}
                prefix={<CheckSquareOutlined style={{ color: '#16a34a' }} />}
              />
            </Card>
          </Col>
        </Row>

        {/* Meetings + goals / auto-chain shortcuts — Cards */}
        <Row gutter={[16, 16]}>
          <Col xs={24} md={board != null ? 12 : 24}>
            <Card
              className="aba-soft-card"
              size="small"
              hoverable
              onClick={() => nav('/meetings')}
            >
              <Space wrap>
                <CommentOutlined style={{ color: '#7c3aed', fontSize: 18 }} />
                <Typography.Text strong>Meetings</Typography.Text>
                {meetingsCount != null && (
                  <Tag color="blue">{meetingsCount}</Tag>
                )}
                <Typography.Text type="secondary">
                  {meetingsCount != null ? 'Open meeting rooms →' : 'Open meetings →'}
                </Typography.Text>
              </Space>
            </Card>
          </Col>
          {board != null && (
            <Col xs={24} md={12}>
              <Card
                className="aba-soft-card"
                size="small"
                hoverable
                onClick={() => nav('/tasks')}
              >
                <Space wrap>
                  <NodeIndexOutlined style={{ color: '#d97706', fontSize: 18 }} />
                  <Typography.Text strong>Goals / auto-chain</Typography.Text>
                  <Tag color="orange">{openGoalChainCount}</Tag>
                  <Typography.Text type="secondary">Open goal tasks →</Typography.Text>
                </Space>
              </Card>
            </Col>
          )}
        </Row>

        {/* Core Team — every user gets a standing agent roster + My Human */}
        <CoreTeam />

        {/* Full system map — click into every area */}
        <Card
          className="aba-soft-card"
          title="Explore the system"
          extra={(
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Tap any card
            </Typography.Text>
          )}
        >
          <SystemNav compact />
        </Card>

        {/* Quick links — still handy as buttons */}
        <Card className="aba-soft-card" size="small" title="Quick links">
          <Space wrap>
            <Button icon={<CheckSquareOutlined />} onClick={() => nav('/tasks')}>Tasks board</Button>
            <Button icon={<ApartmentOutlined />} onClick={() => nav('/workspace')}>Workspace</Button>
            <Button icon={<TeamOutlined />} onClick={() => nav('/humans')}>Users / Team</Button>
            <Button icon={<SafetyCertificateOutlined />} onClick={() => nav('/permissions')}>Permissions</Button>
            <Button icon={<UserOutlined />} onClick={() => nav('/profile')}>Profile</Button>
            <Button onClick={() => nav('/templates')}>Templates</Button>
            <Button onClick={() => nav('/hierarchy')}>Hierarchy</Button>
            <Button onClick={() => nav('/meetings')}>Meetings</Button>
            <Button onClick={() => nav('/ops')}>Live ops</Button>
            <Button onClick={() => nav('/billing')}>Billing</Button>
            <Button onClick={() => nav('/analytics')}>Analytics</Button>
            <Button onClick={() => nav('/training')}>Training</Button>
            <Button onClick={() => nav('/comms')}>Calls · SMS · Email</Button>
            <Button onClick={() => nav('/settings')}>Settings</Button>
            <Button onClick={() => goBay('/browse')}>AgentBay</Button>
            <Button onClick={() => goMarketing('/')}>Website</Button>
          </Space>
        </Card>

        {companies.length > 0 && (
          <Card
            className="aba-soft-card"
            title="Companies"
            extra={<Button type="link" onClick={() => nav('/workspace')}>Workspace</Button>}
          >
            <List
              dataSource={companies.slice(0, 6)}
              renderItem={(c) => (
                <List.Item
                  style={{ cursor: 'pointer' }}
                  onClick={() => nav(`/companies/${c.id}`)}
                  actions={[
                    <Tag key="p">{c.project_count ?? 0} projects</Tag>,
                    <Button
                      key="g"
                      type="link"
                      size="small"
                      onClick={(e) => { e.stopPropagation(); nav(`/companies/${c.id}`) }}
                    >
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

        {/* Agents + pipeline / conversations — Cards */}
        <Row gutter={[16, 16]}>
          <Col xs={24} md={12}>
            <Card
              className="aba-soft-card"
              title="Your agents"
              extra={<Button type="link" onClick={() => nav('/console')}>Console</Button>}
            >
              <List
                dataSource={agents.slice(0, 5)}
                locale={{
                  emptyText: (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description="No agents yet"
                    >
                      <Button type="primary" size="small" onClick={() => nav('/console')}>
                        Create agent
                      </Button>
                    </Empty>
                  ),
                }}
                renderItem={a => (
                  <List.Item
                    className="aba-click-row"
                    style={{ cursor: 'pointer' }}
                    onClick={() => nav(`/console/${a.id}`)}
                    actions={[
                      (a.is_lead || a.hierarchy_role === 'lead') && (
                        <Tag key="l" color="gold" icon={<CrownOutlined />}>Lead</Tag>
                      ),
                      <Tag key="s" color={a.status === 'active' ? 'green' : 'orange'}>{a.status}</Tag>,
                      <Button
                        key="m"
                        type="link"
                        size="small"
                        onClick={(e) => { e.stopPropagation(); nav(`/console/${a.id}/manage`) }}
                      >
                        Manage
                      </Button>,
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
            <Row gutter={[16, 16]}>
              <Col span={24}>
                <Card
                  className="aba-soft-card aba-card-clickable"
                  hoverable
                  title="Task pipeline"
                  extra={<Button type="link" onClick={(e) => { e.stopPropagation(); nav('/tasks') }}>Board</Button>}
                  onClick={() => nav('/tasks')}
                >
                  <Row gutter={[16, 16]} justify="space-around">
                    {['todo', 'queued', 'in_progress', 'review', 'completed'].map(k => (
                      <Col
                        key={k}
                        xs={12}
                        sm={8}
                        md={8}
                        lg={4}
                        style={{ textAlign: 'center', cursor: 'pointer' }}
                        onClick={(e) => { e.stopPropagation(); nav('/tasks') }}
                      >
                        <Statistic
                          title={k.replace(/_/g, ' ')}
                          value={board?.counts?.[k] || 0}
                        />
                      </Col>
                    ))}
                  </Row>
                </Card>
              </Col>
              <Col span={24}>
                <Card className="aba-soft-card" title="Recent conversations">
                  <List
                    dataSource={data?.recent_conversations || []}
                    locale={{
                      emptyText: (
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description="No conversations yet"
                        >
                          <Button type="primary" size="small" onClick={() => nav('/chat')}>
                            AI Chat
                          </Button>
                        </Empty>
                      ),
                    }}
                    renderItem={c => (
                      <List.Item
                        style={{ cursor: 'pointer' }}
                        onClick={() => nav('/chat', { state: { conversation_id: c.id } })}
                      >
                        <List.Item.Meta
                          avatar={<MessageOutlined />}
                          title={c.title}
                        />
                      </List.Item>
                    )}
                  />
                </Card>
              </Col>
            </Row>
          </Col>
        </Row>
      </Space>
    </PageShell>
  )
}
