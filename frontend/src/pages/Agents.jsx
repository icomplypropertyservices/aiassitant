import React, { useEffect, useRef, useState } from 'react'
import {
  Row, Col, Card, Button, Tag, Timeline, Modal, Form, Input, Select, Switch, Space,
  message, Empty, Popconfirm, Typography, Badge, Dropdown,
} from 'antd'
import {
  PlusOutlined, MessageOutlined, EditOutlined, PauseCircleOutlined,
  PlayCircleOutlined, DeleteOutlined, MailOutlined, PhoneOutlined, BulbOutlined,
  CheckCircleOutlined, InfoCircleOutlined, ThunderboltOutlined, RightOutlined,
  CrownOutlined, DownOutlined,
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import { api, connectAuthedWs } from '../api'
import ModelSelect from '../components/ModelSelect'
import OrchestratorBanner from '../components/OrchestratorBanner'
import { modelLabel } from '../models'
import { isOrchestrator, isLead } from '../agents/roles'

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
  const [companies, setCompanies] = useState([])
  const [projects, setProjects] = useState([])
  const [search, setSearch] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [form] = Form.useForm()
  const selectedTemplate = Form.useWatch('template_id', form)
  const watchIsLead = Form.useWatch('is_lead', form)
  const watchCompany = Form.useWatch('company_id', form)
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
    api('/org/companies').then(setCompanies).catch(() => setCompanies([]))
    api('/org/projects').then(setProjects).catch(() => setProjects([]))
    const ws = connectAuthedWs('/agents/ws')
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data)
      if (m.type === 'auth_ok') return
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
      const isOrch = tpl?.type === 'orchestrator' || values.hierarchy_role === 'orchestrator'
      const asLead = isOrch || values.is_lead || tpl?.type === 'lead'
      const a = await api('/agents/', {
        method: 'POST',
        body: {
          name: values.name,
          template_type: tpl?.type || 'custom',
          personality: values.personality,
          model: values.model,
          idle_mode: values.never_idle ? 'never_idle' : 'allow_idle',
          config,
          is_lead: !!asLead,
          hierarchy_role: isOrch ? 'orchestrator' : (asLead ? 'lead' : (values.hierarchy_role || 'member')),
          parent_id: isOrch ? null : (values.parent_id || null),
          company_id: values.company_id || null,
          project_id: values.project_id || null,
        },
      })
      message.success('Agent created — opening chat')
      setCreateOpen(false)
      form.resetFields()
      nav(`/console/${a.id}`)
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
  // API already sorts orchestrator first; keep stable
  const tpl = templates.find(t => t.id === selectedTemplate)
  const orch = agents.find(a => isOrchestrator(a))

  const openSpawn = (templateId) => {
    setCreateOpen(true)
    if (templateId) {
      const t = templates.find((x) => x.id === templateId)
      const next = { template_id: templateId }
      if (t?.type === 'orchestrator') {
        next.is_lead = true
        next.hierarchy_role = 'orchestrator'
        next.name = form.getFieldValue('name') || 'Main AI Orchestrator'
      } else if (t?.type === 'lead') {
        next.is_lead = true
        next.hierarchy_role = 'lead'
      }
      form.setFieldsValue(next)
    } else {
      form.setFieldsValue({ template_id: undefined })
    }
  }

  const spawnMenuItems = [
    {
      key: 'custom',
      icon: <PlusOutlined />,
      label: 'Custom agent…',
      onClick: () => openSpawn(null),
    },
    ...(templates.length
      ? [
          { type: 'divider' },
          {
            type: 'group',
            label: 'From template',
            children: templates.map((t) => ({
              key: `tpl-${t.id}`,
              label: `${t.type === 'orchestrator' ? '👑 ' : t.type === 'lead' ? '★ ' : ''}${t.name}`,
              onClick: () => openSpawn(t.id),
            })),
          },
        ]
      : []),
    { type: 'divider' },
    {
      key: 'designer',
      icon: <CrownOutlined />,
      label: 'Open Master Designer',
      onClick: async () => {
        try {
          const d = await api('/agents/ensure-designer', { method: 'POST' })
          message.success('Master Designer ready')
          nav(`/console/${d.id}`)
        } catch (e) {
          message.error(e.message)
        }
      },
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
          <div>
            <Typography.Title level={3} style={{ margin: 0 }}>
              Console <Tag color="blue">{agents.length}</Tag>
            </Typography.Title>
            <Typography.Text type="secondary">
              Your agents in one place — open any chat, manage roles, keep work organised.
            </Typography.Text>
          </div>
          <Space wrap>
            <Button onClick={() => nav('/hierarchy')}>Hierarchy</Button>
            <Button onClick={() => nav('/workspace')}>Workspace</Button>
            <Dropdown menu={{ items: spawnMenuItems }} trigger={['click']}>
              <Button type="primary" icon={<PlusOutlined />}>
                Spawn agent <DownOutlined />
              </Button>
            </Dropdown>
          </Space>
        </Space>
      </div>

      <Space style={{ marginBottom: 12 }} wrap>
        <Input.Search
          placeholder="Search agents…"
          style={{ width: 260 }}
          allowClear
          onChange={e => setSearch(e.target.value)}
        />
        <Button onClick={() => nav('/tasks')}>Tasks board</Button>
        <Button type="link" href="/bay/browse">
          Browse AgentBay →
        </Button>
      </Space>

      <OrchestratorBanner orchestrator={orch} onChanged={load} compact />

      {filtered.length === 0 && (
        <Empty description="No agents yet — spawn one from the dropdown, then open chat">
          <Dropdown menu={{ items: spawnMenuItems }} trigger={['click']}>
            <Button type="primary" icon={<PlusOutlined />}>
              Spawn agent <DownOutlined />
            </Button>
          </Dropdown>
        </Empty>
      )}

      <Row gutter={[16, 16]}>
        {filtered.filter(a => a.id !== orch?.id).map(a => (
          <Col xs={24} sm={12} lg={8} xl={6} key={a.id}>
            <Card
              className="aba-agent-card"
              hoverable
              styles={{ body: { padding: 14 } }}
              onClick={() => nav(`/console/${a.id}`)}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 15, lineHeight: 1.2 }}>{a.name}</div>
                  <Space size={4} style={{ marginTop: 4 }}>
                    <Tag style={{ margin: 0 }}>{a.template_type}</Tag>
                    {isLead(a) && !isOrchestrator(a) && <Tag color="gold" style={{ margin: 0 }}>Lead</Tag>}
                    {isOrchestrator(a) && <Tag color="purple" style={{ margin: 0 }}>Orchestrator</Tag>}
                  </Space>
                </div>
                <Tag color={a.status === 'active' ? 'success' : 'warning'} style={{ margin: 0 }}>{a.status}</Tag>
              </div>

              <div style={{ margin: '8px 0 10px', fontSize: 12, color: '#666', minHeight: 32 }}>
                {a.personality || 'Your AI teammate'}
              </div>

              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
                <Tag color={a.idle_mode === 'never_idle' ? 'purple' : 'default'} style={{ margin: 0 }}>
                  {a.idle_mode === 'never_idle' ? 'Self-running' : 'Idle allowed'}
                </Tag>
                <Tag color="blue" style={{ margin: 0 }}>{modelLabel(a.model)}</Tag>
                {a.permission_level && <Tag style={{ margin: 0 }}>{a.permission_level}</Tag>}
              </div>

              <Button
                type="primary"
                size="large"
                block
                className="aba-agent-card-talk"
                icon={<MessageOutlined />}
                onClick={(e) => { e.stopPropagation(); nav(`/console/${a.id}`) }}
              >
                Talk to {a.name.split(' ')[0]}
              </Button>

              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, alignItems: 'center' }}>
                <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); nav(`/console/${a.id}/manage`) }}>
                  Workspace
                </Button>
                <Space size={2}>
                  {a.status === 'active'
                    ? <Button type="text" size="small" icon={<PauseCircleOutlined />} onClick={(e) => action(a.id, 'pause', e)} />
                    : <Button type="text" size="small" icon={<PlayCircleOutlined />} onClick={(e) => action(a.id, 'resume', e)} />}
                  <Popconfirm
                    title="Delete this agent?"
                    onConfirm={async (e) => {
                      e?.stopPropagation?.()
                      await api(`/agents/${a.id}`, { method: 'DELETE' })
                      load()
                    }}
                  >
                    <Button type="text" size="small" danger icon={<DeleteOutlined />} onClick={e => e.stopPropagation()} />
                  </Popconfirm>
                </Space>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      <Modal
        title="Spawn agent"
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
                label: `${t.type === 'orchestrator' ? '👑 ' : ''}${t.name} (${t.type})${t.type === 'lead' ? ' ★' : ''}`,
              }))}
              placeholder="Choose a template — Main AI Orchestrator sits at the top"
              onChange={(tid) => {
                const t = templates.find(x => x.id === tid)
                if (t?.type === 'orchestrator') {
                  form.setFieldsValue({
                    is_lead: true,
                    hierarchy_role: 'orchestrator',
                    name: form.getFieldValue('name') || 'Main AI Orchestrator',
                  })
                } else if (t?.type === 'lead') {
                  form.setFieldsValue({ is_lead: true, hierarchy_role: 'lead' })
                }
              }}
            />
          </Form.Item>
          {(tpl?.unique_fields || []).map(f => (
            <Form.Item key={f.name} name={`field_${f.name}`} label={f.label}>
              <Input placeholder={f.placeholder} />
            </Form.Item>
          ))}
          <Form.Item name="company_id" label="Company (optional)">
            <Select
              allowClear
              placeholder="Assign to a company"
              options={companies.map(c => ({ value: c.id, label: c.name }))}
              onChange={() => form.setFieldsValue({ project_id: undefined })}
            />
          </Form.Item>
          <Form.Item name="project_id" label="Project (optional)">
            <Select
              allowClear
              placeholder="Assign to a project"
              options={projects
                .filter(p => !watchCompany || p.company_id === watchCompany)
                .map(p => ({ value: p.id, label: p.name }))}
            />
          </Form.Item>
          <Form.Item name="is_lead" label="Lead agent (can have a team)" valuePropName="checked">
            <Switch checkedChildren="Lead" unCheckedChildren="Member" />
          </Form.Item>
          <Form.Item name="hierarchy_role" label="Hierarchy role">
            <Select options={[
              { value: 'orchestrator', label: 'Main AI Orchestrator (top)' },
              { value: 'lead', label: 'Lead' },
              { value: 'member', label: 'Member' },
              { value: 'specialist', label: 'Specialist' },
            ]} />
          </Form.Item>
          {!watchIsLead && (
            <Form.Item name="parent_id" label="Reports to (lead)" extra="Optional — defaults under Main Orchestrator">
              <Select
                allowClear
                placeholder="No parent (or Main Orchestrator)"
                options={agents.filter(a => isLead(a)).map(a => ({
                  value: a.id,
                  label: `${a.name}${isOrchestrator(a) ? ' ★' : ''}`,
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
