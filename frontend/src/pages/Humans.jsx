import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Space, Modal, Form, Input, Select, Tag, message, Popconfirm, Typography, InputNumber, Alert,
} from 'antd'
import { UserOutlined, PlusOutlined, SendOutlined, ReloadOutlined } from '@ant-design/icons'
import { api } from '../api'

const { Title, Text } = Typography
const { TextArea } = Input

export default function Humans() {
  const [humans, setHumans] = useState([])
  const [loading, setLoading] = useState(true)
  const [companies, setCompanies] = useState([])
  const [projects, setProjects] = useState([])
  const [agents, setAgents] = useState([])
  const [open, setOpen] = useState(false)
  const [assignOpen, setAssignOpen] = useState(null)
  const [form] = Form.useForm()
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
      message.success('Human teammate added')
      setOpen(false)
      form.resetFields()
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

  const columns = [
    {
      title: 'Name',
      dataIndex: 'name',
      render: (n, r) => (
        <Space>
          <UserOutlined />
          <div>
            <strong>{n}</strong>
            <div><Text type="secondary">{r.email || '—'}</Text></div>
          </div>
        </Space>
      ),
    },
    { title: 'Role', dataIndex: 'role_title', render: (v) => v || '—' },
    {
      title: 'Permission',
      dataIndex: 'permission_level',
      render: (v) => <Tag color="blue">{v || 'operator'}</Tag>,
    },
    {
      title: 'Escalate when',
      dataIndex: 'escalate_when',
      render: (v, r) => (
        <div>
          <Tag color="orange">{v || 'on_blocked'}</Tag>
          {r.escalate_reason && <div><Text type="secondary" style={{ fontSize: 11 }}>{r.escalate_reason}</Text></div>}
        </div>
      ),
    },
    { title: 'Skills', dataIndex: 'skills', ellipsis: true, render: (v) => v || '—' },
    {
      title: 'Scope',
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          {r.company_name && <Tag>{r.company_name}</Tag>}
          {r.project_name && <Tag color="blue">{r.project_name}</Tag>}
        </Space>
      ),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      render: (s) => <Tag color={s === 'active' ? 'green' : s === 'away' ? 'orange' : 'default'}>{s}</Tag>,
    },
    {
      title: 'Load',
      render: (_, r) => (
        <span>{r.open_tasks || 0} / {r.capacity || 5} open</span>
      ),
    },
    {
      title: 'Actions',
      render: (_, r) => (
        <Space>
          <Button size="small" type="primary" icon={<SendOutlined />} onClick={() => { setAssignOpen(r); assignForm.resetFields() }}>
            Assign work
          </Button>
          <Popconfirm title="Remove this human?" onConfirm={() => remove(r.id)}>
            <Button size="small" danger>Remove</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }} wrap>
        <div>
          <Title level={3} style={{ margin: 0 }}><UserOutlined /> Humans</Title>
          <Text type="secondary">Add teammates and allocate work from agents or yourself</Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>Add human</Button>
        </Space>
      </Space>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="Agents can assign work to humans using the assign_human skill"
        description="When an orchestrator or lead runs a plan, it can allocate tasks to people here. Track open load vs capacity."
      />

      <Card>
        <Table
          rowKey="id"
          loading={loading}
          dataSource={humans}
          columns={columns}
          pagination={{ pageSize: 12 }}
          locale={{ emptyText: 'No humans yet — add your first teammate' }}
        />
      </Card>

      <Modal
        title="Add human teammate"
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={save} initialValues={{
          status: 'active', capacity: 5, permission_level: 'operator',
          escalate_when: 'on_blocked', escalate_to: 'orchestrator',
        }}>
          <Form.Item name="name" label="Name" rules={[{ required: true }]}>
            <Input placeholder="Jane Smith" />
          </Form.Item>
          <Form.Item name="email" label="Email">
            <Input placeholder="jane@company.com" />
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
            <Select allowClear options={companies.map((c) => ({ value: c.id, label: c.name }))} placeholder="Optional" />
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
          <Button type="primary" htmlType="submit" loading={saving} block>Save human</Button>
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
            <Select allowClear options={agents.map((a) => ({ value: a.id, label: a.name }))} placeholder="Who delegated" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving} block icon={<SendOutlined />}>
            Allocate work
          </Button>
        </Form>
      </Modal>
    </div>
  )
}
