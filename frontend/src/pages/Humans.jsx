import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Space, Modal, Form, Input, Select, Tag, message, Popconfirm,
  Typography, InputNumber, Alert, Row, Col, Statistic, Avatar,
} from 'antd'
import {
  UserOutlined, PlusOutlined, SendOutlined, ReloadOutlined,
  SafetyCertificateOutlined, TeamOutlined, BankOutlined,
} from '@ant-design/icons'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'

const { Title, Text } = Typography
const { TextArea } = Input

const PERM_COLOR = { viewer: 'default', operator: 'blue', lead: 'purple', admin: 'gold' }

export default function Humans() {
  const nav = useNavigate()
  const [humans, setHumans] = useState([])
  const [loading, setLoading] = useState(true)
  const [companies, setCompanies] = useState([])
  const [projects, setProjects] = useState([])
  const [agents, setAgents] = useState([])
  const [open, setOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(null)
  const [assignOpen, setAssignOpen] = useState(null)
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [assignForm] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [h, co, pr, ag] = await Promise.all([
        api('/humans/'),
        api('/org/companies').catch(() => []),
        api('/org/projects').catch(() => []),
        api('/agents/').catch(() => []),
      ])
      setHumans(h.humans || [])
      setCompanies(Array.isArray(co) ? co : co.companies || [])
      setProjects(Array.isArray(pr) ? pr : pr.projects || [])
      setAgents(Array.isArray(ag) ? ag : [])
    } catch (e) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

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
          placeholder="Optional — scopes this person to a company"
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
      width: 200,
      render: (n, r) => (
        <Space>
          <Avatar style={{ background: '#1668dc' }} size="small">
            {(n || '?')[0].toUpperCase()}
          </Avatar>
          <div>
            <strong>{n}</strong>
            <div><Text type="secondary" style={{ fontSize: 12 }}>{r.email || '—'}</Text></div>
          </div>
        </Space>
      ),
    },
    { title: 'Title', dataIndex: 'role_title', width: 120, render: (v) => v || '—' },
    {
      title: 'Permission',
      dataIndex: 'permission_level',
      width: 110,
      render: (v) => <Tag color={PERM_COLOR[v] || 'blue'}>{v || 'operator'}</Tag>,
    },
    {
      title: 'Escalate',
      dataIndex: 'escalate_when',
      width: 130,
      render: (v, r) => (
        <div>
          <Tag color="orange">{v || 'on_blocked'}</Tag>
          {r.escalate_reason && (
            <div><Text type="secondary" style={{ fontSize: 11 }}>{r.escalate_reason}</Text></div>
          )}
        </div>
      ),
    },
    { title: 'Skills', dataIndex: 'skills', ellipsis: true, width: 140, render: (v) => v || '—' },
    {
      title: 'Company',
      width: 140,
      render: (_, r) => (
        r.company_id ? (
          <Link to={`/companies/${r.company_id}`}>
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
        <Text>
          {r.open_tasks || 0} / {r.capacity || 5}
        </Text>
      ),
    },
    {
      title: 'Actions',
      fixed: 'right',
      width: 220,
      render: (_, r) => (
        <Space wrap size={4}>
          <Button size="small" type="primary" icon={<SendOutlined />} onClick={() => {
            setAssignOpen(r)
            assignForm.resetFields()
          }}>
            Assign
          </Button>
          <Button size="small" onClick={() => openEdit(r)}>Edit</Button>
          <Popconfirm title="Remove this person from the team?" onConfirm={() => remove(r.id)}>
            <Button size="small" danger>Remove</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ maxWidth: '100%', overflowX: 'hidden' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }} wrap>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            <TeamOutlined /> Users / Team
          </Title>
          <Text type="secondary">
            Add human teammates, set permissions, and allocate work from agents
          </Text>
        </div>
        <Space wrap>
          <Button icon={<SafetyCertificateOutlined />} onClick={() => nav('/permissions')}>
            Permissions matrix
          </Button>
          <Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
            Add person
          </Button>
        </Space>
      </Space>

      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="Team members" value={humans.length} prefix={<TeamOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="Active" value={active} valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="Open tasks" value={totalOpen} suffix={`/ ${totalCap || '—'}`} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="Companies" value={companies.length} prefix={<BankOutlined />} />
          </Card>
        </Col>
      </Row>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="Humans in the org chart"
        description={
          <>
            Add real people your agents can assign work to. Set permission levels here or on the{' '}
            <Link to="/permissions">Permissions</Link> page. Scope someone to a company so they show on that company’s profile.
          </>
        }
      />

      <Card>
        <Table
          rowKey="id"
          loading={loading}
          dataSource={humans}
          columns={columns}
          scroll={{ x: 1100 }}
          pagination={{ pageSize: 12, showSizeChanger: true }}
          locale={{ emptyText: 'No people yet — add your first teammate with “Add person”' }}
        />
      </Card>

      <Modal
        title="Add person to team"
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        destroyOnClose
        width={520}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={save}
          initialValues={{
            status: 'active',
            capacity: 5,
            permission_level: 'operator',
            escalate_when: 'on_blocked',
            escalate_to: 'orchestrator',
          }}
        >
          {humanFormFields}
          <Button type="primary" htmlType="submit" loading={saving} block icon={<PlusOutlined />}>
            Save person
          </Button>
        </Form>
      </Modal>

      <Modal
        title={editOpen ? `Edit ${editOpen.name}` : 'Edit'}
        open={!!editOpen}
        onCancel={() => setEditOpen(null)}
        footer={null}
        destroyOnClose
        width={520}
      >
        <Form form={editForm} layout="vertical" onFinish={saveEdit}>
          {humanFormFields}
          <Button type="primary" htmlType="submit" loading={saving} block>
            Update person
          </Button>
        </Form>
      </Modal>

      <Modal
        title={assignOpen ? `Assign work → ${assignOpen.name}` : 'Assign'}
        open={!!assignOpen}
        onCancel={() => setAssignOpen(null)}
        footer={null}
        destroyOnClose
      >
        <Form form={assignForm} layout="vertical" onFinish={assign}>
          <Form.Item name="title" label="Title" rules={[{ required: true }]}>
            <Input placeholder="Follow up with Acme proposal" />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <TextArea rows={3} placeholder="Details, links, deadline…" />
          </Form.Item>
          <Form.Item name="priority" label="Priority" initialValue="medium">
            <Select options={[
              { value: 'low', label: 'Low' },
              { value: 'medium', label: 'Medium' },
              { value: 'high', label: 'High' },
              { value: 'urgent', label: 'Urgent' },
            ]} />
          </Form.Item>
          <Form.Item name="agent_id" label="From agent (optional)">
            <Select
              allowClear
              options={agents.map((a) => ({ value: a.id, label: a.name }))}
              placeholder="Who delegated"
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving} block icon={<SendOutlined />}>
            Allocate work
          </Button>
        </Form>
      </Modal>
    </div>
  )
}
