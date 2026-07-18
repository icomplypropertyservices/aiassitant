import React, { useEffect, useState } from 'react'
import {
  Card, Row, Col, Typography, Tag, Space, Button, Spin, Descriptions, Timeline, Table, Form, Input,
  Select, message, Modal, InputNumber, Divider, Empty, Popconfirm,
} from 'antd'
import {
  ArrowLeftOutlined, UserOutlined, MailOutlined, PhoneOutlined, GlobalOutlined,
  PlusOutlined, EditOutlined, ReloadOutlined, DollarOutlined, FunnelPlotOutlined,
  CalendarOutlined, ClockCircleOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

const STATUS_COLOR = {
  active: 'green', inactive: 'default', churned: 'red',
  open: 'processing', won: 'success', lost: 'error',
}

export default function CustomerDetail() {
  const { id } = useParams()
  const nav = useNavigate()
  const [c, setC] = useState(null)
  const [loading, setLoading] = useState(true)
  const [editOpen, setEditOpen] = useState(false)
  const [noteOpen, setNoteOpen] = useState(false)
  const [dealOpen, setDealOpen] = useState(false)
  const [diaryOpen, setDiaryOpen] = useState(false)
  const [pipelines, setPipelines] = useState([])
  const [humans, setHumans] = useState([])
  const [agents, setAgents] = useState([])
  const [editForm] = Form.useForm()
  const [noteForm] = Form.useForm()
  const [dealForm] = Form.useForm()
  const [diaryForm] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [cust, pipes, hum, ag] = await Promise.all([
        api(`/business/customers/${id}`),
        api('/business/pipelines').catch(() => ({ pipelines: [] })),
        api('/humans/').catch(() => ({ humans: [] })),
        api('/agents/').catch(() => []),
      ])
      setC(cust)
      setPipelines(pipes.pipelines || [])
      setHumans(hum.humans || [])
      setAgents(Array.isArray(ag) ? ag : [])
    } catch (e) {
      message.error(e.message)
      nav('/business?tab=customers')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [id])

  const saveEdit = async (values) => {
    setSaving(true)
    try {
      const updated = await api(`/business/customers/${id}`, { method: 'PUT', body: values })
      setC((prev) => ({ ...prev, ...updated }))
      message.success('Customer updated')
      setEditOpen(false)
      load()
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const addNote = async (values) => {
    setSaving(true)
    try {
      await api(`/business/customers/${id}/activities`, {
        method: 'POST',
        body: { kind: values.kind || 'note', title: values.title, body: values.body },
      })
      message.success('Activity logged')
      setNoteOpen(false)
      noteForm.resetFields()
      load()
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const createDeal = async (values) => {
    setSaving(true)
    try {
      await api('/business/deals', {
        method: 'POST',
        body: { ...values, customer_id: Number(id) },
      })
      message.success('Deal created')
      setDealOpen(false)
      dealForm.resetFields()
      load()
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    try {
      await api(`/business/customers/${id}`, { method: 'DELETE' })
      message.success('Customer deleted')
      nav('/business?tab=customers')
    } catch (e) {
      message.error(e.message)
    }
  }

  if (loading || !c) {
    return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>
  }

  return (
    <div>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }} wrap>
        <Space wrap>
          <Button icon={<ArrowLeftOutlined />} onClick={() => nav('/business?tab=customers')}>
            All customers
          </Button>
          <Title level={3} style={{ margin: 0 }}>
            <UserOutlined /> {c.name}
          </Title>
          <Tag color={STATUS_COLOR[c.status]}>{c.status}</Tag>
          {(c.tags || []).map((t) => <Tag key={t}>{t}</Tag>)}
        </Space>
        <Space wrap>
          <Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button>
          <Button icon={<EditOutlined />} onClick={() => {
            editForm.setFieldsValue({
              ...c,
              tags: c.tags_raw || (c.tags || []).join(', '),
            })
            setEditOpen(true)
          }}>
            Edit
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setNoteOpen(true)}>Log activity</Button>
          <Button icon={<FunnelPlotOutlined />} onClick={() => setDealOpen(true)}>Add deal</Button>
          <Button icon={<CalendarOutlined />} onClick={() => setDiaryOpen(true)}>Arrange diary / meeting</Button>
          <Popconfirm title="Delete this customer and their deals?" onConfirm={remove}>
            <Button danger>Delete</Button>
          </Popconfirm>
        </Space>
      </Space>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={10}>
          <Card title="Contact & account" style={{ marginBottom: 16 }}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="Account">{c.account_name || '—'}</Descriptions.Item>
              <Descriptions.Item label="Email">
                {c.email ? <a href={`mailto:${c.email}`}><MailOutlined /> {c.email}</a> : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="Phone">
                {c.phone ? <><PhoneOutlined /> {c.phone}</> : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="Job title">{c.job_title || '—'}</Descriptions.Item>
              <Descriptions.Item label="Industry">{c.industry || '—'}</Descriptions.Item>
              <Descriptions.Item label="Website">
                {c.website ? <a href={c.website.startsWith('http') ? c.website : `https://${c.website}`} target="_blank" rel="noreferrer"><GlobalOutlined /> {c.website}</a> : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="Location">
                {[c.city, c.country].filter(Boolean).join(', ') || '—'}
              </Descriptions.Item>
              <Descriptions.Item label="Address">{c.address || '—'}</Descriptions.Item>
              <Descriptions.Item label="Source">{c.source || '—'}</Descriptions.Item>
              <Descriptions.Item label="Owner (human)">{c.owner_human_name || '—'}</Descriptions.Item>
              <Descriptions.Item label="Owner (agent)">{c.owner_agent_name || '—'}</Descriptions.Item>
              <Descriptions.Item label="Annual value">
                <DollarOutlined /> ${Number(c.annual_value || 0).toLocaleString()}
              </Descriptions.Item>
              <Descriptions.Item label="Pipeline value">
                ${Number(c.pipeline_value || 0).toLocaleString()}
              </Descriptions.Item>
              <Descriptions.Item label="Last contacted">
                {c.last_contacted_at ? new Date(c.last_contacted_at).toLocaleString() : '—'}
              </Descriptions.Item>
            </Descriptions>
            {c.notes && (
              <>
                <Divider />
                <Text type="secondary">Notes</Text>
                <Paragraph style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>{c.notes}</Paragraph>
              </>
            )}
          </Card>

          <Card title={`Deals (${(c.deals || []).length})`}>
            <Table
              size="small"
              rowKey="id"
              pagination={false}
              dataSource={c.deals || []}
              locale={{ emptyText: 'No deals yet' }}
              columns={[
                { title: 'Deal', dataIndex: 'title' },
                {
                  title: 'Stage',
                  render: (_, r) => <Tag color={r.stage_color}>{r.stage_name}</Tag>,
                },
                {
                  title: 'Value',
                  dataIndex: 'value',
                  render: (v, r) => `${r.currency || 'USD'} ${Number(v || 0).toLocaleString()}`,
                },
                {
                  title: 'Status',
                  dataIndex: 'status',
                  render: (s) => <Tag color={STATUS_COLOR[s]}>{s}</Tag>,
                },
              ]}
            />
            <Button type="dashed" block style={{ marginTop: 12 }} icon={<PlusOutlined />} onClick={() => setDealOpen(true)}>
              New deal
            </Button>
          </Card>
        </Col>

        <Col xs={24} lg={14}>
          <Card title="Activity timeline" extra={<Button size="small" onClick={() => setNoteOpen(true)}>Add note</Button>}>
            {!(c.activities || []).length ? (
              <Empty description="No activity yet — log a call, email, or note" />
            ) : (
              <Timeline
                items={(c.activities || []).map((a) => ({
                  color:
                    a.kind === 'deal' ? 'green' :
                    a.kind === 'stage' ? 'blue' :
                    a.kind === 'call' ? 'orange' :
                    a.kind === 'email' ? 'purple' : 'gray',
                  children: (
                    <div>
                      <Space wrap>
                        <Tag>{a.kind}</Tag>
                        <strong>{a.title}</strong>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {a.created_at ? new Date(a.created_at).toLocaleString() : ''}
                        </Text>
                      </Space>
                      {a.body && (
                        <div style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>{a.body}</div>
                      )}
                    </div>
                  ),
                }))}
              />
            )}
          </Card>

          {(c.tasks || []).length > 0 && (
            <Card title="Linked tasks" style={{ marginTop: 16 }}>
              <Table
                size="small"
                rowKey="id"
                pagination={false}
                dataSource={c.tasks}
                columns={[
                  { title: 'Title', dataIndex: 'title' },
                  { title: 'Status', dataIndex: 'status', render: (s) => <Tag>{s}</Tag> },
                  { title: 'Priority', dataIndex: 'priority' },
                ]}
              />
            </Card>
          )}

          <Card title="Diary / Appointments" style={{ marginTop: 16 }} extra={<Button size="small" icon={<CalendarOutlined />} onClick={() => setDiaryOpen(true)}>Arrange</Button>}>
            {!(c.diary || []).length ? (
              <Empty description="No diary entries — schedule a meeting or call" />
            ) : (
              <Timeline
                items={(c.diary || []).map((d) => ({
                  color: d.status === 'completed' ? 'green' : d.status === 'cancelled' ? 'red' : 'blue',
                  dot: <ClockCircleOutlined />,
                  children: (
                    <div>
                      <Space wrap>
                        <strong>{d.title}</strong>
                        <Tag color={d.status === 'scheduled' ? 'blue' : d.status === 'completed' ? 'success' : 'default'}>{d.status}</Tag>
                        {d.start_at && <Text type="secondary">{new Date(d.start_at).toLocaleString()}</Text>}
                      </Space>
                      {d.location && <div style={{ fontSize: 12, color: '#666' }}>📍 {d.location}</div>}
                      {d.notes && <div style={{ whiteSpace: 'pre-wrap', marginTop: 2, fontSize: 12 }}>{d.notes}</div>}
                    </div>
                  ),
                }))}
              />
            )}
          </Card>
        </Col>
      </Row>

      {/* Edit */}
      <Modal title="Edit customer" open={editOpen} onCancel={() => setEditOpen(false)} footer={null} width={640} destroyOnClose>
        <Form form={editForm} layout="vertical" onFinish={saveEdit}>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="name" label="Name" rules={[{ required: true }]}><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="account_name" label="Account"><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="email" label="Email"><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="phone" label="Phone"><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="job_title" label="Job title"><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="industry" label="Industry"><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="status" label="Status">
              <Select options={[
                { value: 'active', label: 'Active' },
                { value: 'inactive', label: 'Inactive' },
                { value: 'churned', label: 'Churned' },
              ]} />
            </Form.Item></Col>
            <Col span={12}><Form.Item name="source" label="Source"><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="owner_human_id" label="Owner (human)">
              <Select allowClear options={humans.map((h) => ({ value: h.id, label: h.name }))} />
            </Form.Item></Col>
            <Col span={12}><Form.Item name="owner_agent_id" label="Owner (agent)">
              <Select allowClear options={agents.map((a) => ({ value: a.id, label: a.name }))} />
            </Form.Item></Col>
            <Col span={12}><Form.Item name="city" label="City"><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="country" label="Country"><Input /></Form.Item></Col>
            <Col span={24}><Form.Item name="address" label="Address"><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="website" label="Website"><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="annual_value" label="Annual value"><InputNumber style={{ width: '100%' }} min={0} /></Form.Item></Col>
            <Col span={24}><Form.Item name="tags" label="Tags"><Input placeholder="comma,separated" /></Form.Item></Col>
            <Col span={24}><Form.Item name="notes" label="Notes"><TextArea rows={3} /></Form.Item></Col>
          </Row>
          <Button type="primary" htmlType="submit" loading={saving} block>Save changes</Button>
        </Form>
      </Modal>

      {/* Activity */}
      <Modal title="Log activity" open={noteOpen} onCancel={() => setNoteOpen(false)} footer={null} destroyOnClose>
        <Form form={noteForm} layout="vertical" onFinish={addNote} initialValues={{ kind: 'note' }}>
          <Form.Item name="kind" label="Type">
            <Select options={[
              { value: 'note', label: 'Note' },
              { value: 'call', label: 'Call' },
              { value: 'email', label: 'Email' },
              { value: 'meeting', label: 'Meeting' },
            ]} />
          </Form.Item>
          <Form.Item name="title" label="Title">
            <Input placeholder="Optional title" />
          </Form.Item>
          <Form.Item name="body" label="Details" rules={[{ required: true }]}>
            <TextArea rows={4} placeholder="What happened…" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving} block>Save activity</Button>
        </Form>
      </Modal>

      {/* Deal */}
      <Modal title={`New deal for ${c.name}`} open={dealOpen} onCancel={() => setDealOpen(false)} footer={null} destroyOnClose>
        <Form
          form={dealForm}
          layout="vertical"
          onFinish={createDeal}
          initialValues={{
            title: `${c.account_name || c.name} opportunity`,
            priority: 'medium',
            currency: 'USD',
            value: 0,
            pipeline_id: pipelines.find((p) => p.is_default)?.id || pipelines[0]?.id,
          }}
        >
          <Form.Item name="title" label="Title" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="pipeline_id" label="Pipeline">
            <Select options={pipelines.map((p) => ({ value: p.id, label: p.name }))} />
          </Form.Item>
          <Form.Item name="value" label="Value">
            <InputNumber style={{ width: '100%' }} min={0} />
          </Form.Item>
          <Form.Item name="priority" label="Priority">
            <Select options={[
              { value: 'low', label: 'Low' },
              { value: 'medium', label: 'Medium' },
              { value: 'high', label: 'High' },
              { value: 'urgent', label: 'Urgent' },
            ]} />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <TextArea rows={2} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving} block>Create deal</Button>
        </Form>
      </Modal>

      {/* Diary / Meeting */}
      <Modal title={`Arrange diary for ${c.name}`} open={diaryOpen} onCancel={() => setDiaryOpen(false)} footer={null} destroyOnClose>
        <Form
          form={diaryForm}
          layout="vertical"
          onFinish={async (values) => {
            setSaving(true)
            try {
              await api(`/business/diary`, {
                method: 'POST',
                body: {
                  customer_id: Number(id),
                  title: values.title,
                  start_at: values.start_at || null,
                  end_at: values.end_at || null,
                  location: values.location || '',
                  notes: values.notes || '',
                  owner_human_id: values.owner_human_id || null,
                  owner_agent_id: values.owner_agent_id || null,
                },
              })
              message.success('Diary entry scheduled')
              setDiaryOpen(false)
              diaryForm.resetFields()
              load()
            } catch (e) {
              message.error(e.message)
            } finally {
              setSaving(false)
            }
          }}
          initialValues={{ title: `Meeting / call with ${c.name}`, status: 'scheduled' }}
        >
          <Form.Item name="title" label="Title" rules={[{ required: true }]}>
            <Input placeholder="Follow-up call, site visit, quarterly review…" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="start_at" label="Start (local ISO or datetime)">
                <Input placeholder="2026-07-20T14:00" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="end_at" label="End">
                <Input placeholder="2026-07-20T14:30" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="location" label="Location / link">
            <Input placeholder="Zoom / Office / Phone" />
          </Form.Item>
          <Form.Item name="notes" label="Notes / agenda">
            <TextArea rows={2} placeholder="Key topics or prep notes" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="owner_human_id" label="Owner (human)">
                <Select allowClear options={humans.map((h) => ({ value: h.id, label: h.name }))} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="owner_agent_id" label="Owner (agent)">
                <Select allowClear options={agents.map((a) => ({ value: a.id, label: a.name }))} />
              </Form.Item>
            </Col>
          </Row>
          <Button type="primary" htmlType="submit" loading={saving} block>Schedule in diary</Button>
        </Form>
      </Modal>
    </div>
  )
}
