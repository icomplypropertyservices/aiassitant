import React, { useEffect, useState } from 'react'
import {
  Card, Row, Col, Button, Modal, Form, Input, Select, Tag, Space, Typography,
  List, Empty, message, Popconfirm, Collapse, Badge, Switch, Alert,
} from 'antd'
import {
  PlusOutlined, BankOutlined, ProjectOutlined, CheckSquareOutlined, DeleteOutlined,
  ThunderboltOutlined, RobotOutlined, CrownOutlined, ApartmentOutlined,
  LineChartOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import OrchestratorBanner from '../components/OrchestratorBanner'
import PageHeader from '../components/PageHeader'
import { isOrchestrator } from '../agents/roles'
import PageShell from '../components/PageShell'


const STATUS_COLOR = {
  active: 'green',
  paused: 'orange',
  done: 'default',
  todo: 'default',
  queued: 'blue',
  in_progress: 'gold',
  review: 'purple',
  completed: 'success',
  failed: 'error',
}

export default function Workspace() {
  const nav = useNavigate()
  const [tree, setTree] = useState(null)
  const [agents, setAgents] = useState([])
  const [templates, setTemplates] = useState({ companies: [], projects: [], tasks: [] })
  const [companyOpen, setCompanyOpen] = useState(false)
  const [projectOpen, setProjectOpen] = useState(null) // company id
  const [taskOpen, setTaskOpen] = useState(null) // project
  const [allocOpen, setAllocOpen] = useState(null) // project
  const [allocIds, setAllocIds] = useState([])
  const [runningId, setRunningId] = useState(null)
  const [selectedCompanyTpl, setSelectedCompanyTpl] = useState(null)
  const [companyForm] = Form.useForm()
  const [projectForm] = Form.useForm()
  const [taskForm] = Form.useForm()

  const load = () => {
    api('/org/tree').then(setTree).catch(e => message.error(e.message))
    api('/agents/')
      .then((list) => setAgents(Array.isArray(list) ? list : []))
      .catch(() => setAgents([]))
  }
  useEffect(() => {
    load()
    api('/org/templates')
      .then((t) => setTemplates({
        companies: Array.isArray(t?.companies) ? t.companies : [],
        projects: Array.isArray(t?.projects) ? t.projects : [],
        tasks: Array.isArray(t?.tasks) ? t.tasks : [],
      }))
      .catch(() => {})
  }, [])

  const createCompany = async (v) => {
    try {
      const body = {
        name: v.name || '',
        industry: v.industry || '',
        notes: v.notes || '',
        template_id: v.template_id || null,
        create_suggested_projects: v.create_suggested_projects !== false,
      }
      const r = await api('/org/companies', { method: 'POST', body })
      const bits = []
      if (r.created_projects?.length) bits.push(`${r.created_projects.length} projects`)
      if (r.created_tasks?.length) bits.push(`${r.created_tasks.length} starter tasks`)
      message.success(`Created${bits.length ? ` · ${bits.join(' · ')}` : ''}`)
      setCompanyOpen(false)
      setSelectedCompanyTpl(null)
      companyForm.resetFields()
      load()
    } catch (e) { message.error(e.message) }
  }

  const createProject = async (v) => {
    try {
      const r = await api('/org/projects', {
        method: 'POST',
        body: {
          name: v.name || '',
          description: v.description || '',
          status: v.status || 'active',
          template_id: v.template_id || null,
          company_id: projectOpen,
        },
      })
      const n = r.created_tasks?.length || 0
      message.success(n ? `Project created · ${n} starter tasks` : 'Project created')
      setProjectOpen(null)
      projectForm.resetFields()
      load()
    } catch (e) { message.error(e.message) }
  }

  const createTask = async (v) => {
    try {
      await api('/org/tasks', {
        method: 'POST',
        body: {
          title: v.title || '',
          description: v.description || '',
          project_id: taskOpen.id,
          agent_id: v.agent_id || null,
          template_id: v.template_id || null,
        },
      })
      message.success('Task added')
      setTaskOpen(null)
      taskForm.resetFields()
      load()
    } catch (e) { message.error(e.message) }
  }

  const openAlloc = (p) => {
    setAllocOpen(p)
    setAllocIds(p.agent_ids || (p.agents || []).map(a => a.id) || [])
  }

  const saveAlloc = async () => {
    try {
      const r = await api(`/org/projects/${allocOpen.id}/agents`, {
        method: 'PUT',
        body: { agent_ids: allocIds },
      })
      message.success(r.message || 'Agents allocated')
      setAllocOpen(null)
      load()
    } catch (e) {
      message.error(e.message)
    }
  }

  const setTaskStatus = async (id, status) => {
    try {
      await api(`/org/tasks/${id}`, { method: 'PATCH', body: { status } })
      load()
    } catch (e) { message.error(e.message) }
  }

  const runTask = async (t) => {
    if (!t.agent_id) {
      message.warning('Assign an agent before running')
      return
    }
    setRunningId(t.id)
    try {
      await api(`/org/tasks/${t.id}/run`, {
        method: 'POST',
        body: { agent_id: t.agent_id },
      })
      message.success('Task run started')
      load()
    } catch (e) {
      message.error(e.message)
    } finally {
      setRunningId(null)
    }
  }

  const companies = tree?.companies || []
  const limits = tree?.limits || {}
  const projectAgents = (p) => p.agents || []
  const agentsForProject = (p) => {
    // Prefer agents allocated to project; fall back to company agents + global
    const allocated = agents.filter(a => a.project_id === p.id)
    if (allocated.length) return allocated
    return agents.filter(a => !a.project_id || a.company_id === p.company_id || isOrchestrator(a))
  }

  return (
    <PageShell>
      <PageHeader
        title="Workspace"
        subtitle={(
          <span>
            Companies or Personal → projects → agents &amp; tasks
            {tree?.subscriber && (
              <>
                {' '}· Plan <Tag color="blue">{tree.subscriber.plan}</Tag>
                {limits.companies != null && (
                  <Tag>
                    {tree.counts?.companies || 0}/{limits.companies} workspaces · {tree.counts?.projects || 0}/{limits.projects} projects
                  </Tag>
                )}
              </>
            )}
          </span>
        )}
        extra={(
          <>
            <Button icon={<ApartmentOutlined />} onClick={() => nav('/hierarchy')}>Hierarchy</Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => {
                setCompanyOpen(true)
                setSelectedCompanyTpl((templates.companies || []).find((t) => t.id === 'personal') || null)
                companyForm.setFieldsValue({
                  template_id: 'personal',
                  name: 'Personal',
                  industry: 'Personal',
                  notes: 'Your life, goals, and personal ops — not a registered business.',
                  create_suggested_projects: true,
                })
              }}
            >
              New company / Personal
            </Button>
          </>
        )}
      />

      <OrchestratorBanner
        orchestrator={tree?.orchestrator}
        onChanged={load}
      />

      {companies.length === 0 ? (
        <Card className="aba-soft-card">
          <Empty description="No companies yet — create one (use a template for a head start)">
            <Button type="primary" onClick={() => setCompanyOpen(true)}>Create company</Button>
          </Empty>
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {companies.map(c => (
            <Col xs={24} key={c.id}>
              <Card
                className="aba-soft-card"
                title={
                  <Space wrap>
                    <BankOutlined />
                    <Button
                      type="link"
                      style={{ padding: 0, height: 'auto', fontWeight: 600, fontSize: 16 }}
                      onClick={() => nav(`/companies/${c.id}`)}
                    >
                      {c.name}
                    </Button>
                    {c.industry && <Tag>{c.industry}</Tag>}
                  </Space>
                }
                extra={
                  <Space wrap>
                    <Tag>{c.project_count} projects</Tag>
                    <Tag>{c.agent_count || 0} agents</Tag>
                    <Tag>{c.task_count} tasks</Tag>
                    <Button
                      size="small"
                      type="primary"
                      ghost
                      icon={<LineChartOutlined />}
                      onClick={() => nav(`/companies/${c.id}`)}
                    >
                      Profile &amp; P&amp;L
                    </Button>
                    <Button size="small" icon={<PlusOutlined />} onClick={() => setProjectOpen(c.id)}>
                      Project
                    </Button>
                    <Popconfirm title="Delete company and all projects/tasks?" onConfirm={async () => {
                      try {
                        await api(`/org/companies/${c.id}`, { method: 'DELETE' })
                        load()
                      } catch (e) { message.error(e.message) }
                    }}>
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </Space>
                }
              >
                {c.notes && (
                  <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
                    {c.notes}
                  </Typography.Paragraph>
                )}
                {(c.projects || []).length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No projects in this company">
                    <Button size="small" type="primary" onClick={() => setProjectOpen(c.id)}>
                      Add project
                    </Button>
                  </Empty>
                ) : (
                  <Card size="small" type="inner" title="Projects">
                    <Collapse
                      items={(c.projects || []).map(p => ({
                        key: p.id,
                        label: (
                          <Space wrap>
                            <ProjectOutlined />
                            <strong>{p.name}</strong>
                            <Tag color={STATUS_COLOR[p.status] || 'default'}>{p.status}</Tag>
                            <Badge count={p.open_tasks} overflowCount={99} style={{ background: '#1668dc' }} />
                            <Typography.Text type="secondary">{p.task_count} tasks</Typography.Text>
                            <Tag icon={<RobotOutlined />} color="geekblue">
                              {p.agent_count || 0} agents
                            </Tag>
                          </Space>
                        ),
                        extra: (
                          <Space onClick={e => e.stopPropagation()}>
                            <Button size="small" icon={<RobotOutlined />} onClick={() => openAlloc(p)}>
                              Agents
                            </Button>
                            <Button size="small" onClick={() => setTaskOpen(p)}>Add task</Button>
                            <Popconfirm title="Delete project?" onConfirm={async () => {
                              try {
                                await api(`/org/projects/${p.id}`, { method: 'DELETE' })
                                load()
                              } catch (e) { message.error(e.message) }
                            }}>
                              <Button size="small" danger icon={<DeleteOutlined />} />
                            </Popconfirm>
                          </Space>
                        ),
                        children: (
                          <div>
                            <Card size="small" type="inner" title="Allocated agents" style={{ marginBottom: 12 }}>
                              <Space wrap size={[4, 4]}>
                                {projectAgents(p).length === 0 ? (
                                  <Typography.Text type="secondary">None — click Agents to assign</Typography.Text>
                                ) : projectAgents(p).map(a => (
                                  <Tag
                                    key={a.id}
                                    color={isOrchestrator(a) ? 'gold' : 'blue'}
                                    style={{ cursor: 'pointer' }}
                                    onClick={() => nav(`/agents/${a.id}`)}
                                  >
                                    {isOrchestrator(a) && <CrownOutlined />} {a.name}
                                  </Tag>
                                ))}
                              </Space>
                            </Card>
                            <Card size="small" type="inner" title="Tasks">
                              <List
                                dataSource={p.tasks || []}
                                locale={{ emptyText: 'No tasks yet' }}
                                renderItem={t => (
                                  <List.Item
                                    actions={[
                                      t.agent_id && t.status !== 'completed' && (
                                        <Button
                                          key="run"
                                          type="link"
                                          icon={<ThunderboltOutlined />}
                                          loading={runningId === t.id}
                                          onClick={() => runTask(t)}
                                        >
                                          Run
                                        </Button>
                                      ),
                                      t.status !== 'completed' && (
                                        <Button key="done" type="link" onClick={() => setTaskStatus(t.id, 'completed')}>
                                          Complete
                                        </Button>
                                      ),
                                      <Button key="progress" type="link" onClick={() => setTaskStatus(t.id, 'in_progress')}>
                                        In progress
                                      </Button>,
                                    ].filter(Boolean)}
                                  >
                                    <List.Item.Meta
                                      avatar={<CheckSquareOutlined />}
                                      title={
                                        <Space wrap>
                                          {t.title}
                                          <Tag color={STATUS_COLOR[t.status] || 'default'}>{t.status}</Tag>
                                          {t.agent_id && (
                                            <Tag icon={<RobotOutlined />} color="geekblue">
                                              {agents.find(a => a.id === t.agent_id)?.name || 'Agent'}
                                            </Tag>
                                          )}
                                          {t.tokens_used > 0 && (
                                            <Tag color="purple">{t.tokens_used} tok · ${Number(t.cost || 0).toFixed(4)}</Tag>
                                          )}
                                        </Space>
                                      }
                                      description={t.description}
                                    />
                                  </List.Item>
                                )}
                              />
                            </Card>
                          </div>
                        ),
                      }))}
                    />
                  </Card>
                )}
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <Modal
        title="New company or personal workspace"
        open={companyOpen}
        onCancel={() => { setCompanyOpen(false); setSelectedCompanyTpl(null) }}
        footer={null}
        destroyOnClose
        width={640}
      >
        <Form
          form={companyForm}
          layout="vertical"
          onFinish={createCompany}
          initialValues={{ create_suggested_projects: true, template_id: 'personal' }}
        >
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message="Pick a type"
            description="Personal = life, goals, side projects. Business types seed industry projects + starter tasks. Universal task options work on every project."
          />
          <Form.Item name="template_id" label="Company type">
            <Select
              showSearch
              optionFilterProp="label"
              options={(templates.companies || []).map(t => ({
                value: t.id,
                label: `${t.kind === 'personal' ? '👤 ' : ''}${t.name}${t.industry ? ` · ${t.industry}` : ''}${t.badge ? ` (${t.badge})` : ''}`,
              }))}
              onChange={(id) => {
                const t = (templates.companies || []).find(x => x.id === id)
                setSelectedCompanyTpl(t || null)
                if (t && id !== 'blank') {
                  companyForm.setFieldsValue({
                    name: id === 'personal' ? 'Personal' : t.name,
                    industry: t.industry,
                    notes: t.notes,
                  })
                }
              }}
            />
          </Form.Item>
          {selectedCompanyTpl?.suggested_projects?.length > 0 && (
            <Card size="small" type="inner" title="What you get" style={{ marginBottom: 12 }}>
              <List
                size="small"
                dataSource={selectedCompanyTpl.suggested_projects}
                renderItem={(p) => (
                  <List.Item>
                    <List.Item.Meta
                      title={p.name}
                      description={
                        <>
                          {p.description}
                          {p.task_count > 0 && (
                            <Tag color="purple" style={{ marginLeft: 8 }}>{p.task_count} starter tasks</Tag>
                          )}
                        </>
                      }
                    />
                  </List.Item>
                )}
              />
            </Card>
          )}
          <Form.Item name="name" label={selectedCompanyTpl?.kind === 'personal' ? 'Name' : 'Company name'} rules={[{ required: true, message: 'Name or template required' }]}>
            <Input placeholder={selectedCompanyTpl?.kind === 'personal' ? 'Personal' : 'Acme Ltd'} />
          </Form.Item>
          <Form.Item name="industry" label="Industry">
            <Input placeholder="Electrical / SaaS / Agency" />
          </Form.Item>
          <Form.Item name="notes" label="Notes">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item
            name="create_suggested_projects"
            label="Create suggested projects + starter tasks"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>
            {selectedCompanyTpl?.kind === 'personal' ? 'Create personal workspace' : 'Create company'}
          </Button>
        </Form>
      </Modal>

      <Modal title="New project" open={!!projectOpen} onCancel={() => setProjectOpen(null)} footer={null} destroyOnClose width={520}>
        <Form form={projectForm} layout="vertical" onFinish={createProject} initialValues={{ status: 'active', template_id: 'blank' }}>
          <Form.Item name="template_id" label="Project template">
            <Select
              showSearch
              optionFilterProp="label"
              options={(templates.projects || []).map(t => ({
                value: t.id,
                label: `${t.name}${t.suggested_task_ids?.length ? ` · ${t.suggested_task_ids.length} tasks` : ''}`,
              }))}
              onChange={(id) => {
                const t = (templates.projects || []).find(x => x.id === id)
                if (t && id !== 'blank') {
                  projectForm.setFieldsValue({
                    name: t.name,
                    description: t.description,
                    status: t.status || 'active',
                  })
                }
              }}
            />
          </Form.Item>
          <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
            Templates seed starter tasks. You can always add more from universal task options.
          </Typography.Paragraph>
          <Form.Item name="name" label="Project name" rules={[{ required: true }]}>
            <Input placeholder="Website relaunch / Q3 sales" />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="status" label="Status">
            <Select options={[
              { value: 'active', label: 'Active' },
              { value: 'paused', label: 'Paused' },
              { value: 'done', label: 'Done' },
            ]} />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>Create project</Button>
        </Form>
      </Modal>

      <Modal
        title={allocOpen ? `Allocate agents · ${allocOpen.name}` : 'Agents'}
        open={!!allocOpen}
        onCancel={() => setAllocOpen(null)}
        onOk={saveAlloc}
        okText="Save allocation"
        destroyOnClose
      >
        <Typography.Paragraph type="secondary">
          Agents assigned here are scoped to this project (and its company). The Main Orchestrator stays global.
        </Typography.Paragraph>
        <Select
          mode="multiple"
          style={{ width: '100%' }}
          placeholder="Select project agents (orchestrator stays global)"
          value={allocIds.filter(id => {
            const a = agents.find(x => x.id === id)
            return a && !isOrchestrator(a)
          })}
          onChange={setAllocIds}
          options={agents
            .filter(a => !isOrchestrator(a))
            .map(a => ({
              value: a.id,
              label: `${a.name} (${a.template_type})`,
            }))}
        />
      </Modal>

      <Modal
        title={taskOpen ? `Task · ${taskOpen.name}` : 'Task'}
        open={!!taskOpen}
        onCancel={() => { setTaskOpen(null); taskForm.resetFields() }}
        footer={null}
        destroyOnClose
        width={560}
      >
        <Form form={taskForm} layout="vertical" onFinish={createTask}>
          <Form.Item name="template_id" label="Task option (all projects)">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="Pick a starter task template"
              options={(templates.tasks || []).map((t) => ({
                value: t.id,
                label: t.name,
              }))}
              onChange={(id) => {
                const t = (templates.tasks || []).find((x) => x.id === id)
                if (t) {
                  taskForm.setFieldsValue({
                    title: t.title || t.name,
                    description: t.description,
                  })
                }
              }}
            />
          </Form.Item>
          <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: -8 }}>
            Universal options: standup, inbox triage, follow-ups, content draft, research, checklists, and more.
          </Typography.Paragraph>
          <Form.Item name="title" label="Title">
            <Input placeholder="Optional short title" />
          </Form.Item>
          <Form.Item
            name="description"
            label="Description"
            rules={[{ required: true, message: 'Description or task template required' }]}
          >
            <Input.TextArea rows={3} placeholder="What needs doing?" />
          </Form.Item>
          <Form.Item name="agent_id" label="Assign agent">
            <Select
              allowClear
              placeholder="Optional — prefer project agents"
              options={agentsForProject(taskOpen || {}).map(a => ({
                value: a.id,
                label: `${a.name}${a.project_id === taskOpen?.id ? ' · on project' : ''}`,
              }))}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>Add task</Button>
        </Form>
      </Modal>
    </PageShell>
  )
}
