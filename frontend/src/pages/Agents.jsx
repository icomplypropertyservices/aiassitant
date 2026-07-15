import React, { useEffect, useRef, useState } from 'react'
import {
  Row, Col, Card, Button, Tag, Timeline, Modal, Form, Input, Select, Switch, Space,
  message, Empty, Popconfirm, Typography, Badge,
} from 'antd'
import {
  PlusOutlined, MessageOutlined, EditOutlined, PauseCircleOutlined,
  PlayCircleOutlined, DeleteOutlined, MailOutlined, PhoneOutlined, BulbOutlined,
  CheckCircleOutlined, InfoCircleOutlined, ThunderboltOutlined, RightOutlined,
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import { api, getToken, getWsBase } from '../api'
import ModelSelect from '../components/ModelSelect'
import { modelLabel } from '../models'

const ICONS = {
  thinking: <BulbOutlined style={{ color: '#faad14' }} />,
  action: <ThunderboltOutlined style={{ color: '#1668dc' }} />,
  email: <MailOutlined style={{ color: '#52c41a' }} />,
  sms: <MessageOutlined style={{ color: '#52c41a' }} />,
  call: <PhoneOutlined style={{ color: '#52c41a' }} />,
  done: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  info: <InfoCircleOutlined style={{ color: '#8c8c8c' }} />,
}

export default function Agents() {
  const nav = useNavigate()
  const loc = useLocation()
  const [agents, setAgents] = useState([])
  const [templates, setTemplates] = useState([])
  const [search, setSearch] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [form] = Form.useForm()
  const selectedTemplate = Form.useWatch('template_id', form)
  const watchIsLead = Form.useWatch('is_lead', form)
  const wsRef = useRef(null)

  const load = () => api('/agents/').then(setAgents).catch(e => message.error(e.message))

  useEffect(() => {
    load()
    api('/templates/').then(t => {
      setTemplates(t)
      if (loc.state?.templateId) {
        setCreateOpen(true)
        form.setFieldsValue({ template_id: loc.state.templateId })
      }
    }).catch(() => {})
    const ws = new WebSocket(`${getWsBase()}/agents/ws?token=${getToken()}`)
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data)
      if (m.event === 'activity') {
        setAgents(prev => prev.map(a => a.id === m.agent_id
          ? { ...a, activity: [...(a.activity || []).slice(-7), m.entry] } : a))
      }
      if (m.event === 'task_done') load()
    }
    wsRef.current = ws
    return () => ws.close()
  }, [])

  const createAgent = async (values) => {
    const tpl = templates.find(t => t.id === values.template_id)
    const config = {}
    ;(tpl?.unique_fields || []).forEach(f => { config[f.name] = values[`field_${f.name}`] || '' })
    try {
      const isLead = values.is_lead || tpl?.type === 'lead'
      const a = await api('/agents/', {
        method: 'POST',
        body: {
          name: values.name,
          template_type: tpl?.type || 'custom',
          personality: values.personality,
          model: values.model,
          idle_mode: values.never_idle ? 'never_idle' : 'allow_idle',
          config,
          is_lead: !!isLead,
          hierarchy_role: isLead ? 'lead' : (values.hierarchy_role || 'member'),
          parent_id: values.parent_id || null,
        },
      })
      message.success('Agent created — opening live workspace')
      setCreateOpen(false)
      form.resetFields()
      nav(`/agents/${a.id}`)
    } catch (e) {
      message.error(e.message)
    }
  }

  const action = async (id, act, e) => {
    e?.stopPropagation?.()
    try {
      await api(`/agents/${id}/${act}`, { method: 'POST' })
      load()
    } catch (err) {
      message.error(err.message)
    }
  }

  const filtered = agents.filter(a => a.name.toLowerCase().includes(search.toLowerCase()))
  const tpl = templates.find(t => t.id === selectedTemplate)

  return (
    <div>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }} wrap>
        <Space wrap>
          <Input.Search
            placeholder="Search agents"
            style={{ width: 260 }}
            allowClear
            onChange={e => setSearch(e.target.value)}
          />
          <Button onClick={() => nav('/hierarchy')}>Hierarchy</Button>
          <Button onClick={() => nav('/tasks')}>Tasks board</Button>
        </Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          Create New Agent
        </Button>
      </Space>

      {filtered.length === 0 && (
        <Empty description="No agents yet — create one from a template">
          <Button type="primary" onClick={() => setCreateOpen(true)}>Create agent</Button>
        </Empty>
      )}

      <Row gutter={[16, 16]}>
        {filtered.map(a => (
          <Col xs={24} lg={12} xl={8} key={a.id}>
            <Card
              hoverable
              onClick={() => nav(`/agents/${a.id}`)}
              title={
                <Space wrap>
                  {a.name}
                  <Tag>{a.template_type}</Tag>
                  <Tag color={a.status === 'active' ? 'green' : 'orange'}>{a.status}</Tag>
                  {(a.is_lead || a.hierarchy_role === 'lead') && <Tag color="gold">Lead</Tag>}
                  {a.parent_name && <Tag>→ {a.parent_name}</Tag>}
                </Space>
              }
              extra={
                <Space>
                  <Badge count={a.stats?.open || 0} size="small" offset={[0, 0]}>
                    <Tag color="blue">{modelLabel(a.model)}</Tag>
                  </Badge>
                  <RightOutlined style={{ color: '#bbb' }} />
                </Space>
              }
              actions={[
                <span key="chat" onClick={e => { e.stopPropagation(); nav(`/agents/${a.id}`) }}>
                  <MessageOutlined /> Live chat
                </span>,
                a.status === 'active'
                  ? <PauseCircleOutlined key="pause" onClick={e => action(a.id, 'pause', e)} />
                  : <PlayCircleOutlined key="resume" onClick={e => action(a.id, 'resume', e)} />,
                <Popconfirm
                  key="del"
                  title="Delete this agent?"
                  onConfirm={async (e) => {
                    e?.stopPropagation?.()
                    await api(`/agents/${a.id}`, { method: 'DELETE' })
                    load()
                  }}
                  onClick={e => e.stopPropagation()}
                >
                  <DeleteOutlined onClick={e => e.stopPropagation()} />
                </Popconfirm>,
              ]}
            >
              <Space style={{ marginBottom: 8 }} wrap>
                <Tag color={a.idle_mode === 'never_idle' ? 'purple' : 'default'}>
                  {a.idle_mode === 'never_idle' ? 'Never be idle' : 'Allowed to idle'}
                </Tag>
                <Typography.Text type="secondary">
                  {a.stats?.completed || 0}/{a.stats?.tasks || 0} done · {a.stats?.open || 0} open
                </Typography.Text>
              </Space>
              <Typography.Paragraph type="secondary" ellipsis style={{ marginBottom: 8, fontSize: 12 }}>
                Click to open live chat, tasks & activity
              </Typography.Paragraph>
              <div style={{ height: 140, overflowY: 'auto', background: '#fafafa', borderRadius: 6, padding: '8px 8px 0' }}>
                <Timeline
                  items={(a.activity || []).slice(-5).map(entry => ({
                    dot: ICONS[entry.type] || ICONS.info,
                    children: <span style={{ fontSize: 11 }}>{entry.message}</span>,
                  }))}
                />
                {(!a.activity || a.activity.length === 0) && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>No activity yet</Typography.Text>
                )}
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      <Modal
        title="Create New Agent"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => form.submit()}
        okText="Create & open"
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={createAgent}
          initialValues={{
            model: 'vps-fast',
            personality: 'Professional, friendly and concise.',
            hierarchy_role: 'member',
            is_lead: false,
          }}
        >
          <Form.Item name="name" label="Agent name" rules={[{ required: true }]}>
            <Input placeholder="e.g. Sales Lead or Lead Chaser" />
          </Form.Item>
          <Form.Item name="template_id" label="Template" rules={[{ required: true }]}>
            <Select
              options={templates.map(t => ({
                value: t.id,
                label: `${t.name} (${t.type})${t.type === 'lead' ? ' ★' : ''}`,
              }))}
              placeholder="Choose a template — pick Lead Agent for hierarchy"
              onChange={(tid) => {
                const t = templates.find(x => x.id === tid)
                if (t?.type === 'lead') form.setFieldsValue({ is_lead: true, hierarchy_role: 'lead' })
              }}
            />
          </Form.Item>
          {(tpl?.unique_fields || []).map(f => (
            <Form.Item key={f.name} name={`field_${f.name}`} label={f.label}>
              <Input placeholder={f.placeholder} />
            </Form.Item>
          ))}
          <Form.Item name="is_lead" label="Lead agent (can have a team)" valuePropName="checked">
            <Switch checkedChildren="Lead" unCheckedChildren="Member" />
          </Form.Item>
          <Form.Item name="hierarchy_role" label="Hierarchy role">
            <Select options={[
              { value: 'lead', label: 'Lead' },
              { value: 'member', label: 'Member' },
              { value: 'specialist', label: 'Specialist' },
            ]} />
          </Form.Item>
          {!watchIsLead && (
            <Form.Item name="parent_id" label="Reports to (lead)" extra="Optional — set later on Hierarchy page">
              <Select
                allowClear
                placeholder="No parent"
                options={agents.filter(a => a.is_lead || a.hierarchy_role === 'lead').map(a => ({
                  value: a.id,
                  label: a.name,
                }))}
              />
            </Form.Item>
          )}
          <Form.Item name="personality" label="Personality"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="model" label="Model"><ModelSelect style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="never_idle" label="Never be idle" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
