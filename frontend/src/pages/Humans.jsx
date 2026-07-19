import React, { useEffect, useState, useRef } from 'react'
import {
  Card, Table, Button, Space, Modal, Form, Input, Select, Tag, message, Popconfirm,
  Typography, InputNumber, Alert, Row, Col, Statistic, Avatar, List, Empty, Badge, Divider,
} from 'antd'
import {
  UserOutlined, PlusOutlined, SendOutlined, ReloadOutlined,
  SafetyCertificateOutlined, TeamOutlined, BankOutlined, MessageOutlined,
  CrownOutlined, ShopOutlined, RobotOutlined, SwapOutlined,
} from '@ant-design/icons'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/PageHeader'
import PageShell from '../components/PageShell'
import InfoDrawer from '../components/InfoDrawer'

const { Text, Paragraph } = Typography
const { TextArea } = Input

const PERM_COLOR = { viewer: 'default', operator: 'blue', lead: 'purple', admin: 'gold' }

export default function Humans() {
  const nav = useNavigate()
  const [humans, setHumans] = useState([])
  const [myHuman, setMyHuman] = useState(null)
  const [subs, setSubs] = useState([])
  const [subsMeta, setSubsMeta] = useState(null)
  const [loading, setLoading] = useState(true)
  const [companies, setCompanies] = useState([])
  const [projects, setProjects] = useState([])
  const [agents, setAgents] = useState([])
  const [open, setOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(null)
  const [assignOpen, setAssignOpen] = useState(null)
  const [msgHuman, setMsgHuman] = useState(null)
  const [messages, setMessages] = useState([])
  const [msgText, setMsgText] = useState('')
  const [msgLoading, setMsgLoading] = useState(false)
  const [delegateOpen, setDelegateOpen] = useState(null)
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [assignForm] = Form.useForm()
  const [delegateForm] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const msgEndRef = useRef(null)

  const load = async () => {
    setLoading(true)
    try {
      const [h, co, pr, ag, sc] = await Promise.all([
        api('/humans/'),
        api('/org/companies').catch(() => []),
        api('/org/projects').catch(() => []),
        api('/agents/').catch(() => []),
        api('/humans/subcontractors').catch(() => api('/marketplace/subcontractors').catch(() => null)),
      ])
      setHumans(h.humans || [])
      setMyHuman(h.my_human || (h.humans || []).find((x) => x.is_my_human) || null)
      setCompanies(Array.isArray(co) ? co : co.companies || [])
      setProjects(Array.isArray(pr) ? pr : pr.projects || [])
      setAgents(Array.isArray(ag) ? ag : [])
      if (sc) {
        setSubs(sc.subcontractors || [])
        setSubsMeta(sc)
      }
    } catch (e) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const openMessages = async (h) => {
    setMsgHuman(h)
    setMsgLoading(true)
    setMsgText('')
    try {
      const r = await api(`/humans/${h.id}/messages`)
      setMessages(r.messages || [])
      setTimeout(() => msgEndRef.current?.scrollIntoView?.({ behavior: 'smooth' }), 100)
    } catch (e) {
      message.error(e.message)
      setMessages([])
    } finally {
      setMsgLoading(false)
    }
  }

  const sendMessage = async () => {
    if (!msgHuman || !msgText.trim()) return
    setMsgLoading(true)
    try {
      const r = await api(`/humans/${msgHuman.id}/messages`, {
        method: 'POST',
        body: { content: msgText.trim() },
      })
      setMessages(r.messages || [])
      setMsgText('')
      load()
      setTimeout(() => msgEndRef.current?.scrollIntoView?.({ behavior: 'smooth' }), 50)
    } catch (e) {
      message.error(e.message)
    } finally {
      setMsgLoading(false)
    }
  }

  const save = async (values) => {
    setSaving(true)
    try {
      await api('/humans/', { method: 'POST', body: values })
      message.success('Team member added')
      setOpen(false)
      form.resetFields()
      load()
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const saveEdit = async (values) => {
    if (!editOpen) return
    setSaving(true)
    try {
      await api(`/humans/${editOpen.id}`, { method: 'PUT', body: values })
      message.success('Updated')
      setEditOpen(null)
      editForm.resetFields()
      load()
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const assign = async (values) => {
    setSaving(true)
    try {
      await api(`/humans/${assignOpen.id}/assign`, { method: 'POST', body: values })
      message.success(`Work assigned to ${assignOpen.name}`)
      setAssignOpen(null)
      assignForm.resetFields()
      load()
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const delegate = async (values) => {
    if (!delegateOpen) return
    setSaving(true)
    try {
      await api(`/humans/${delegateOpen.id}/delegate`, { method: 'POST', body: values })
      message.success('Delegated — message boxes updated')
      setDelegateOpen(null)
      delegateForm.resetFields()
      load()
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const makeMyHuman = async (id) => {
    try {
      await api(`/humans/my/set/${id}`, { method: 'POST' })
      message.success('My Human updated')
      load()
    } catch (e) {
      message.error(e.message)
    }
  }

  const remove = async (id) => {
    try {
      await api(`/humans/${id}`, { method: 'DELETE' })
      message.success('Removed')
      load()
    } catch (e) {
      message.error(e.message)
    }
  }

  const openEdit = (r) => {
    setEditOpen(r)
    editForm.setFieldsValue({
      name: r.name,
      email: r.email || '',
      phone: r.phone || '',
      role_title: r.role_title || '',
      skills: r.skills || '',
      permission_level: r.permission_level || 'operator',
      escalate_when: r.escalate_when || 'on_blocked',
      escalate_reason: r.escalate_reason || '',
      escalate_to: r.escalate_to || 'orchestrator',
      company_id: r.company_id || undefined,
      project_id: r.project_id || undefined,
      capacity: r.capacity || 5,
      status: r.status || 'active',
      notes: r.notes || '',
    })
  }

  const active = humans.filter((h) => h.status === 'active').length
  const totalOpen = humans.reduce((s, h) => s + (h.open_tasks || 0), 0)
  const totalCap = humans.reduce((s, h) => s + (h.capacity || 0), 0)

  const humanFormFields = (
    <>
      <Form.Item name="name" label="Name" rules={[{ required: true }]}>
        <Input placeholder="Jane Smith" prefix={<UserOutlined />} />
      </Form.Item>
      <Form.Item name="email" label="Email">
        <Input placeholder="jane@company.com" type="email" />
      </Form.Item>
      <Form.Item name="phone" label="Phone (E.164 for SMS)">
        <Input placeholder="+15551234567" />
      </Form.Item>
      <Form.Item name="role_title" label="Role / title">
        <Input placeholder="Sales manager" />
      </Form.Item>
      <Form.Item name="skills" label="Skills">
        <Input placeholder="negotiation, CRM, onboarding" />
      </Form.Item>
      <Form.Item name="permission_level" label="Permission level" rules={[{ required: true }]}>
        <Select options={[
          { value: 'viewer', label: 'Viewer — read only' },
          { value: 'operator', label: 'Operator — execute work' },
          { value: 'lead', label: 'Lead — delegate & escalate' },
          { value: 'admin', label: 'Admin — full control' },
        ]} />
      </Form.Item>
      <Form.Item name="escalate_when" label="When to escalate" rules={[{ required: true }]}>
        <Select options={[
          { value: 'never', label: 'Never auto-escalate' },
          { value: 'on_failure', label: 'On failure' },
          { value: 'on_blocked', label: 'When blocked' },
          { value: 'high_priority', label: 'High / urgent priority' },
          { value: 'sla_breach', label: 'SLA / stuck too long' },
          { value: 'always_review', label: 'Always review' },
          { value: 'custom', label: 'Custom (use reason)' },
        ]} />
      </Form.Item>
      <Form.Item name="escalate_reason" label="Escalation reason / rule">
        <TextArea rows={2} placeholder="e.g. Escalate if customer asks for legal review" />
      </Form.Item>
      <Form.Item name="escalate_to" label="Escalate to">
        <Select options={[
          { value: 'orchestrator', label: 'Main orchestrator' },
          { value: 'parent', label: 'Reporting lead' },
          { value: 'human', label: 'Another human' },
          { value: 'owner', label: 'Workspace owner' },
        ]} />
      </Form.Item>
      <Form.Item name="company_id" label="Company">
        <Select
          allowClear
          options={companies.map((c) => ({ value: c.id, label: c.name }))}
          placeholder="Optional"
        />
      </Form.Item>
      <Form.Item name="project_id" label="Project">
        <Select allowClear options={projects.map((p) => ({ value: p.id, label: p.name }))} placeholder="Optional" />
      </Form.Item>
      <Form.Item name="capacity" label="Capacity (open tasks)">
        <InputNumber min={1} max={50} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item name="status" label="Status">
        <Select options={[
          { value: 'active', label: 'Active' },
          { value: 'away', label: 'Away' },
          { value: 'offline', label: 'Offline' },
        ]} />
      </Form.Item>
      <Form.Item name="notes" label="Notes">
        <TextArea rows={2} />
      </Form.Item>
    </>
  )

  const columns = [
    {
      title: 'Person',
      dataIndex: 'name',
      fixed: 'left',
      width: 220,
      render: (n, r) => (
        <Space>
          <Avatar style={{ background: r.is_my_human ? '#d97706' : '#1668dc' }} size="small">
            {(n || '?')[0].toUpperCase()}
          </Avatar>
          <div>
            <strong>{n}</strong>
            {r.is_my_human && <Tag color="gold" style={{ marginLeft: 6 }}>My Human</Tag>}
            <div><Text type="secondary" style={{ fontSize: 12 }}>{r.email || '—'}</Text></div>
          </div>
        </Space>
      ),
    },
    { title: 'Title', dataIndex: 'role_title', width: 140, render: (v) => v || '—' },
    {
      title: 'Permission',
      dataIndex: 'permission_level',
      width: 110,
      render: (v) => <Tag color={PERM_COLOR[v] || 'blue'}>{v || 'operator'}</Tag>,
    },
    {
      title: 'Inbox',
      width: 90,
      render: (_, r) => (
        <Badge count={r.unread_messages || 0} size="small">
          <Button
            size="small"
            icon={<MessageOutlined />}
            onClick={(e) => { e.stopPropagation(); openMessages(r) }}
          >
            Chat
          </Button>
        </Badge>
      ),
    },
    {
      title: 'Company',
      width: 140,
      render: (_, r) => (
        r.company_id ? (
          <Link to={`/companies/${r.company_id}`} onClick={(e) => e.stopPropagation()}>
            <Tag icon={<BankOutlined />}>{r.company_name || 'Company'}</Tag>
          </Link>
        ) : <Text type="secondary">Workspace</Text>
      ),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      width: 90,
      render: (s) => (
        <Tag color={s === 'active' ? 'green' : s === 'away' ? 'orange' : 'default'}>{s}</Tag>
      ),
    },
    {
      title: 'Load',
      width: 100,
      render: (_, r) => (
        <Text>{r.open_tasks || 0} / {r.capacity || 5}</Text>
      ),
    },
    {
      title: 'Actions',
      fixed: 'right',
      width: 280,
      render: (_, r) => (
        <Space wrap size={4} onClick={(e) => e.stopPropagation()}>
          <Button size="small" type="primary" icon={<SendOutlined />} onClick={() => {
            setAssignOpen(r)
            assignForm.resetFields()
          }}>
            Assign
          </Button>
          <Button size="small" icon={<SwapOutlined />} onClick={() => {
            setDelegateOpen(r)
            delegateForm.resetFields()
          }}>
            Delegate
          </Button>
          <Button size="small" icon={<MessageOutlined />} onClick={() => openMessages(r)}>
            Message
          </Button>
          {!r.is_my_human && (
            <Button size="small" icon={<CrownOutlined />} onClick={() => makeMyHuman(r.id)}>
              Set My Human
            </Button>
          )}
          <Button size="small" onClick={() => openEdit(r)}>Edit</Button>
          {!r.is_my_human && (
            <Popconfirm title="Remove this person from the team?" onConfirm={() => remove(r.id)}>
              <Button size="small" danger>Remove</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <PageShell>
      <PageHeader
        title={(
          <span>
            <TeamOutlined style={{ marginRight: 8 }} />
            Users / Team
          </span>
        )}
        subtitle="My Human, message boxes, agents, and AgentBay subcontractors"
        extra={(
          <Space wrap>
            <Button icon={<SafetyCertificateOutlined />} onClick={() => nav('/permissions')}>
              Permissions
            </Button>
            <Button icon={<ShopOutlined />} onClick={() => { window.location.href = '/bay/browse' }}>
              Hire on AgentBay
            </Button>
            <Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
              Add person
            </Button>
          </Space>
        )}
      />

      <Row gutter={[12, 12]} justify="center">
        <Col xs={12} sm={6}>
          <Card size="small" className="aba-stat-card">
            <Statistic title="Team members" value={humans.length} prefix={<TeamOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" className="aba-stat-card">
            <Statistic title="Active" value={active} valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" className="aba-stat-card">
            <Statistic title="Open tasks" value={totalOpen} suffix={`/ ${totalCap || '—'}`} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" className="aba-stat-card">
            <Statistic title="Subcontractors" value={subs.length} prefix={<ShopOutlined />} />
          </Card>
        </Col>
      </Row>

      {/* My Human hero card */}
      <Card
        className="aba-soft-card"
        loading={loading && !myHuman}
        title={(
          <Space>
            <CrownOutlined style={{ color: '#d97706' }} />
            <span>My Human</span>
            <Tag color="gold">Primary</Tag>
          </Space>
        )}
        extra={myHuman && (
          <Space wrap>
            <Button type="primary" icon={<MessageOutlined />} onClick={() => openMessages(myHuman)}>
              Message box
              {myHuman.unread_messages > 0 && (
                <Badge count={myHuman.unread_messages} size="small" style={{ marginLeft: 6 }} />
              )}
            </Button>
            <Button icon={<SendOutlined />} onClick={() => { setAssignOpen(myHuman); assignForm.resetFields() }}>
              Assign work
            </Button>
            <Button icon={<SwapOutlined />} onClick={() => { setDelegateOpen(myHuman); delegateForm.resetFields() }}>
              Delegate with agents
            </Button>
          </Space>
        )}
      >
        {myHuman ? (
          <Row gutter={[16, 12]} align="middle">
            <Col xs={24} md={14}>
              <Space align="start" size={12}>
                <Avatar size={56} style={{ background: '#d97706', fontSize: 22 }}>
                  {(myHuman.name || '?')[0].toUpperCase()}
                </Avatar>
                <div>
                  <Typography.Title level={4} style={{ margin: 0 }}>{myHuman.name}</Typography.Title>
                  <Text type="secondary">{myHuman.role_title || 'Primary operator'}</Text>
                  <div style={{ marginTop: 6 }}>
                    <Text>{myHuman.email || 'No email yet'}</Text>
                    {myHuman.phone ? <Text type="secondary"> · {myHuman.phone}</Text> : null}
                  </div>
                  <Paragraph type="secondary" style={{ margin: '8px 0 0', maxWidth: 520 }}>
                    Agents assign human work here by default. My Human can delegate tasks to other
                    teammates and AI Business Assistant agents, with every note in the message box.
                  </Paragraph>
                </div>
              </Space>
            </Col>
            <Col xs={24} md={10}>
              <Row gutter={[8, 8]}>
                <Col span={8}><Statistic title="Open" value={myHuman.open_tasks || 0} /></Col>
                <Col span={8}><Statistic title="Capacity" value={myHuman.capacity || 0} /></Col>
                <Col span={8}>
                  <Statistic title="Inbox" value={myHuman.unread_messages || 0} />
                </Col>
              </Row>
            </Col>
          </Row>
        ) : (
          <Empty description="Creating My Human…">
            <Button type="primary" onClick={() => api('/humans/my/ensure', { method: 'POST' }).then(load)}>
              Ensure My Human
            </Button>
          </Empty>
        )}
      </Card>

      {/* AgentBay subcontractors */}
      <Card
        className="aba-soft-card"
        title={(
          <Space>
            <ShopOutlined />
            <span>AgentBay subcontractors</span>
            <Tag>{subs.length}</Tag>
          </Space>
        )}
        extra={(
          <Button type="link" onClick={() => { window.location.href = '/bay/browse' }}>
            Browse marketplace →
          </Button>
        )}
      >
        {subsMeta && subsMeta.available === false && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message="Marketplace link"
            description={subsMeta.hint || 'Hire skills and agents on AgentBay — paid orders appear here as subcontractors.'}
          />
        )}
        {subs.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="No hired subcontractors yet — buy a skill or agent on AgentBay"
          >
            <Button type="primary" icon={<ShopOutlined />} onClick={() => { window.location.href = '/bay/browse' }}>
              Open AgentBay
            </Button>
          </Empty>
        ) : (
          <List
            dataSource={subs}
            renderItem={(item) => (
              <List.Item
                className="aba-click-row"
                actions={[
                  <Button
                    key="open"
                    type="link"
                    onClick={() => { window.location.href = item.bay_url || '/bay' }}
                  >
                    Order #{item.order_id}
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  avatar={<Avatar icon={<RobotOutlined />} style={{ background: '#1668dc' }} />}
                  title={(
                    <Space wrap>
                      <span>{item.title}</span>
                      <Tag color="blue">{item.kind || 'skill'}</Tag>
                      <Tag color="green">{item.payment_status || item.status}</Tag>
                    </Space>
                  )}
                  description={(
                    <>
                      Seller: {item.seller?.name || '—'}
                      {item.total != null && ` · $${Number(item.total).toFixed(2)} ${item.currency || 'USD'}`}
                      {item.description ? ` — ${item.description.slice(0, 120)}` : ''}
                    </>
                  )}
                />
              </List.Item>
            )}
          />
        )}
      </Card>

      <Card className="aba-soft-card" size="small">
        <Alert
          type="info"
          showIcon
          style={{ background: 'transparent', border: 'none', padding: 0 }}
          message="How humans work with agents"
          description={
            <>
              <strong>My Human</strong> is required on every account. Agents default human assignments there.
              Use the <strong>message box</strong> for coordination, <strong>Assign</strong> for new work, and
              <strong> Delegate</strong> so My Human can hand tasks to other people or AI agents.
              AgentBay hires show as <strong>subcontractors</strong> above.
            </>
          }
        />
      </Card>

      <Card
        className="aba-soft-card"
        title="Team members"
        extra={
          <Button type="link" icon={<PlusOutlined />} onClick={() => setOpen(true)} style={{ paddingInline: 0 }}>
            Add person
          </Button>
        }
        styles={{ body: { paddingTop: 12, overflowX: 'auto' } }}
      >
        <Table
          rowKey="id"
          loading={loading}
          dataSource={humans}
          columns={columns}
          scroll={{ x: 1200 }}
          pagination={{ pageSize: 12, showSizeChanger: true, responsive: true }}
          locale={{ emptyText: 'No people yet — My Human will appear after refresh' }}
          onRow={(record) => ({
            onClick: () => openMessages(record),
            className: 'aba-click-row',
            style: { cursor: 'pointer' },
          })}
        />
      </Card>

      {/* Message box drawer */}
      <InfoDrawer
        open={!!msgHuman}
        onClose={() => setMsgHuman(null)}
        title={msgHuman ? `Message box · ${msgHuman.name}` : 'Messages'}
        subtitle={msgHuman?.is_my_human ? 'My Human · primary operator' : msgHuman?.role_title}
        footer={(
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            <TextArea
              value={msgText}
              onChange={(e) => setMsgText(e.target.value)}
              placeholder="Write a message… (Enter to send, Shift+Enter for newline)"
              autoSize={{ minRows: 2, maxRows: 4 }}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault()
                  sendMessage()
                }
              }}
            />
            <Button type="primary" block size="large" icon={<SendOutlined />} loading={msgLoading} onClick={sendMessage}>
              Send message
            </Button>
          </Space>
        )}
      >
        {msgLoading && messages.length === 0 ? (
          <Empty description="Loading…" />
        ) : messages.length === 0 ? (
          <Empty description="No messages yet — send the first one" />
        ) : (
          <List
            dataSource={messages}
            renderItem={(m) => {
              const mine = m.sender_role === 'owner'
              const who = m.sender_role === 'agent'
                ? (m.sender_agent_name || 'Agent')
                : m.sender_role === 'human'
                  ? (m.related_human_name || msgHuman?.name || 'Human')
                  : m.sender_role === 'system'
                    ? 'System'
                    : 'You'
              return (
                <List.Item style={{ border: 'none', padding: '8px 0', justifyContent: mine ? 'flex-end' : 'flex-start' }}>
                  <Card
                    size="small"
                    style={{
                      maxWidth: '92%',
                      background: mine ? '#e8f1fc' : '#f8fafc',
                      borderRadius: 12,
                    }}
                  >
                    <Space size={6} wrap>
                      <Tag>{who}</Tag>
                      {m.kind && m.kind !== 'message' && <Tag color="purple">{m.kind}</Tag>}
                      {m.task_id && <Tag color="blue">task #{m.task_id}</Tag>}
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {m.created_at ? new Date(m.created_at).toLocaleString() : ''}
                      </Text>
                    </Space>
                    <div style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>{m.content}</div>
                  </Card>
                </List.Item>
              )
            }}
          />
        )}
        <div ref={msgEndRef} />
      </InfoDrawer>

      <Modal title="Add person to team" open={open} onCancel={() => setOpen(false)} footer={null} destroyOnClose width={520} centered>
        <Form form={form} layout="vertical" onFinish={save} initialValues={{
          status: 'active', capacity: 5, permission_level: 'operator',
          escalate_when: 'on_blocked', escalate_to: 'orchestrator',
        }}>
          {humanFormFields}
          <Button type="primary" htmlType="submit" block loading={saving}>Add person</Button>
        </Form>
      </Modal>

      <Modal title="Edit person" open={!!editOpen} onCancel={() => setEditOpen(null)} footer={null} destroyOnClose width={520} centered>
        <Form form={editForm} layout="vertical" onFinish={saveEdit}>
          {humanFormFields}
          <Button type="primary" htmlType="submit" block loading={saving}>Save</Button>
        </Form>
      </Modal>

      <Modal
        title={assignOpen ? `Assign work → ${assignOpen.name}` : 'Assign'}
        open={!!assignOpen}
        onCancel={() => setAssignOpen(null)}
        footer={null}
        destroyOnClose
        width={480}
        centered
      >
        <Form form={assignForm} layout="vertical" onFinish={assign}>
          <Form.Item name="title" label="Title" rules={[{ required: true }]}>
            <Input placeholder="Call back ACME about renewal" />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <TextArea rows={3} />
          </Form.Item>
          <Form.Item name="message" label="Message box note">
            <TextArea rows={2} placeholder="Also posted to their message box" />
          </Form.Item>
          <Form.Item name="priority" label="Priority" initialValue="medium">
            <Select options={[
              { value: 'low', label: 'Low' },
              { value: 'medium', label: 'Medium' },
              { value: 'high', label: 'High' },
              { value: 'urgent', label: 'Urgent' },
            ]} />
          </Form.Item>
          <Form.Item name="agent_id" label="Assist with agent (optional)">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={agents.map((a) => ({ value: a.id, label: a.name }))}
              placeholder="Optional AI assist"
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={saving} icon={<SendOutlined />}>
            Assign
          </Button>
        </Form>
      </Modal>

      <Modal
        title={delegateOpen ? `Delegate from ${delegateOpen.name}` : 'Delegate'}
        open={!!delegateOpen}
        onCancel={() => setDelegateOpen(null)}
        footer={null}
        destroyOnClose
        width={520}
        centered
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="My Human ↔ agents"
          description="Create a task for another human and/or an AI agent. Both message boxes get the delegation note."
        />
        <Form form={delegateForm} layout="vertical" onFinish={delegate}>
          <Form.Item name="title" label="Title" rules={[{ required: true }]}>
            <Input placeholder="Review Q3 forecast with Finance agent" />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <TextArea rows={3} />
          </Form.Item>
          <Form.Item name="to_human_id" label="To human">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={humans
                .filter((h) => h.id !== delegateOpen?.id)
                .map((h) => ({
                  value: h.id,
                  label: `${h.name}${h.is_my_human ? ' (My Human)' : ''}`,
                }))}
              placeholder="Optional teammate"
            />
          </Form.Item>
          <Form.Item name="to_agent_id" label="To AI agent">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={agents.map((a) => ({ value: a.id, label: a.name }))}
              placeholder="Optional agent"
            />
          </Form.Item>
          <Form.Item name="message" label="Message">
            <TextArea rows={2} placeholder="Context for the message box" />
          </Form.Item>
          <Form.Item name="priority" label="Priority" initialValue="medium">
            <Select options={[
              { value: 'low', label: 'Low' },
              { value: 'medium', label: 'Medium' },
              { value: 'high', label: 'High' },
              { value: 'urgent', label: 'Urgent' },
            ]} />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={saving} icon={<SwapOutlined />}>
            Delegate
          </Button>
        </Form>
      </Modal>
    </PageShell>
  )
}
