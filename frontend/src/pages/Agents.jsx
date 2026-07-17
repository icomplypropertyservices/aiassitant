import React, { useEffect, useRef, useState } from 'react'
import {
  Row, Col, Card, Button, Tag, Timeline, Modal, Form, Input, Select, Switch, Space,
  message, Empty, Popconfirm, Typography, Badge,
} from 'antd'
import {
  PlusOutlined, MessageOutlined, EditOutlined, PauseCircleOutlined,
  PlayCircleOutlined, DeleteOutlined, MailOutlined, PhoneOutlined, BulbOutlined,
  CheckCircleOutlined, InfoCircleOutlined, ThunderboltOutlined, RightOutlined,
  CrownOutlined,
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import { api, getToken, getWsBase } from '../api'
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
  // API already sorts orchestrator first; keep stable
  const tpl = templates.find(t => t.id === selectedTemplate)
  const orch = agents.find(a => isOrchestrator(a))

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
          <Button onClick={() => nav('/workspace')}>Workspace</Button>
          <Button onClick={() => nav('/tasks')}>Tasks board</Button>
        </Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          Create New Agent
        </Button>
      </Space>

      <OrchestratorBanner orchestrator={orch} onChanged={load} compact />

      <Space style={{ marginBottom: 12 }} wrap>
        <Button
          type="dashed"
          icon={<CrownOutlined />}
          onClick={async () => {
            try {
              const d = await api('/agents/ensure-designer', { method: 'POST' })
              message.success('Master Designer ready')
              nav(`/agents/${d.id}`)
            } catch (e) { message.error(e.message) }
          }}
        >
          Master Designer
        </Button>
        <Button
          onClick={async () => {
            try {
              const r = await api('/agents/designer/polish-review')
              if (r.acceptable) message.success(r.verdict)
              else message.warning(r.verdict)
              Modal.info({
                title: 'Master Designer — polish review',
                width: 560,
                content: (
                  <div>
                    <Typography.Paragraph>{r.verdict}</Typography.Paragraph>
                    {(r.gates || []).map((g) => (
                      <div key={g.id} style={{ marginBottom: 6 }}>
                        <Tag color={g.status === 'pass' ? 'success' : 'error'}>{g.status}</Tag>
                        {g.label}
                      </div>
                    ))}
                  </div>
                ),
              })
            } catch (e) { message.error(e.message) }
          }}
        >
          Run polish review
        </Button>
      </Space>

      {filtered.length === 0 && (
        <Empty description="No agents yet — create one, then open chat to talk">
          <Button type="primary" onClick={() => setCreateOpen(true)}>Create agent</Button>
        </Empty>
      )}

      <Row gutter={[16, 16]}>
        {filtered.filter(a => a.id !== orch?.id).map(a => (
          <Col xs={24} sm={12} lg={8} key={a.id}>
            <Card
              className="aba-soft-card"
              title={
                <Space wrap>
                  {a.name}
                  <Tag>{a.template_type}</Tag>
                  <Tag color={a.status === 'active' ? 'green' : 'orange'}>{a.status}</Tag>
                  {isLead(a) && !isOrchestrator(a) && <Tag color="gold">Lead</Tag>}
                  {a.permission_level && <Tag color="blue">{a.permission_level}</Tag>}
                </Space>
              }
              extra={<Tag color="blue">{modelLabel(a.model)}</Tag>}
            >
              <Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ minHeight: 40 }}>
                {a.personality || 'Your AI teammate'}
              </Typography.Paragraph>
              <Space style={{ marginBottom: 12 }} wrap>
                <Tag color={a.idle_mode === 'never_idle' ? 'purple' : 'default'}>
                  {a.idle_mode === 'never_idle' ? 'Self-running' : 'Idle ok'}
                </Tag>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {a.stats?.open || 0} open · {a.stats?.completed || 0} done
                </Typography.Text>
              </Space>
              <Button
                type="primary"
                size="large"
                block
                className="aba-agent-card-talk"
                icon={<MessageOutlined />}
                onClick={() => nav(`/agents/${a.id}`)}
              >
                Talk to {a.name.split(' ')[0]}
              </Button>
              <Space style={{ marginTop: 8, width: '100%', justifyContent: 'space-between' }}>
                <Button type="link" size="small" onClick={() => nav(`/agents/${a.id}/manage`)}>
                  Workspace
                </Button>
                <Space>
                  {a.status === 'active'
                    ? <Button type="text" size="small" icon={<PauseCircleOutlined />} onClick={(e) => action(a.id, 'pause', e)} />
                    : <Button type="text" size="small" icon={<PlayCircleOutlined />} onClick={(e) => action(a.id, 'resume', e)} />}
                  <Popconfirm
                    title="Delete this agent?"
                    onConfirm={async () => {
                      await api(`/agents/${a.id}`, { method: 'DELETE' })
                      load()
                    }}
                  >
                    <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              </Space>
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
