import React, { useEffect, useState } from 'react'
import {
  Card, Row, Col, Button, Modal, Form, Input, Select, Tag, Space, Typography,
  List, Empty, message, Popconfirm, Collapse, Badge,
} from 'antd'
import {
  PlusOutlined, BankOutlined, ProjectOutlined, CheckSquareOutlined, DeleteOutlined,
  ThunderboltOutlined, RobotOutlined,
} from '@ant-design/icons'
import { api } from '../api'

/** Align with TasksBoard column colors */
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
  const [tree, setTree] = useState(null)
  const [agents, setAgents] = useState([])
  const [companyOpen, setCompanyOpen] = useState(false)
  const [projectOpen, setProjectOpen] = useState(null) // company id
  const [taskOpen, setTaskOpen] = useState(null) // project
  const [runningId, setRunningId] = useState(null)
  const [companyForm] = Form.useForm()
  const [projectForm] = Form.useForm()
  const [taskForm] = Form.useForm()

  const load = () => api('/org/tree').then(setTree).catch(e => message.error(e.message))
  useEffect(() => {
    load()
    api('/agents/').then(setAgents).catch(() => setAgents([]))
  }, [])

  const createCompany = async (v) => {
    try {
      await api('/org/companies', { method: 'POST', body: v })
      message.success('Company created')
      setCompanyOpen(false)
      companyForm.resetFields()
      load()
    } catch (e) { message.error(e.message) }
  }

  const createProject = async (v) => {
    try {
      await api('/org/projects', {
        method: 'POST',
        body: { ...v, company_id: projectOpen },
      })
      message.success('Project created')
      setProjectOpen(null)
      projectForm.resetFields()
      load()
    } catch (e) { message.error(e.message) }
  }

  const createTask = async (v) => {
    try {
      const body = {
        title: v.title,
        description: v.description,
        project_id: taskOpen.id,
        agent_id: v.agent_id || null,
      }
      await api('/org/tasks', { method: 'POST', body })
      message.success('Task added')
      setTaskOpen(null)
      taskForm.resetFields()
      load()
    } catch (e) { message.error(e.message) }
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

  return (
    <div>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            Workspace
          </Typography.Title>
          <Typography.Text type="secondary">
            Subscriber → Companies → Projects → Tasks
            {tree?.subscriber && (
              <> · Plan <Tag color="blue">{tree.subscriber.plan}</Tag></>
            )}
          </Typography.Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCompanyOpen(true)}>
          New company
        </Button>
      </Space>

      {companies.length === 0 ? (
        <Card>
          <Empty description="No companies yet — create one to organise projects and tasks">
            <Button type="primary" onClick={() => setCompanyOpen(true)}>Create company</Button>
          </Empty>
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {companies.map(c => (
            <Col xs={24} key={c.id}>
              <Card
                title={
                  <Space>
                    <BankOutlined />
                    {c.name}
                    {c.industry && <Tag>{c.industry}</Tag>}
                  </Space>
                }
                extra={
                  <Space>
                    <Tag>{c.project_count} projects</Tag>
                    <Tag>{c.task_count} tasks</Tag>
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
                {(c.projects || []).length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No projects in this company" />
                ) : (
                  <Collapse
                    items={(c.projects || []).map(p => ({
                      key: p.id,
                      label: (
                        <Space>
                          <ProjectOutlined />
                          <strong>{p.name}</strong>
                          <Tag color={STATUS_COLOR[p.status] || 'default'}>{p.status}</Tag>
                          <Badge count={p.open_tasks} overflowCount={99} style={{ background: '#1668dc' }} />
                          <Typography.Text type="secondary">{p.task_count} tasks</Typography.Text>
                        </Space>
                      ),
                      extra: (
                        <Space onClick={e => e.stopPropagation()}>
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
                      ),
                    }))}
                  />
                )}
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <Modal title="New company" open={companyOpen} onCancel={() => setCompanyOpen(false)} footer={null} destroyOnClose>
        <Form form={companyForm} layout="vertical" onFinish={createCompany}>
          <Form.Item name="name" label="Company name" rules={[{ required: true }]}>
            <Input placeholder="Acme Ltd" />
          </Form.Item>
          <Form.Item name="industry" label="Industry">
            <Input placeholder="Electrical / SaaS / Agency" />
          </Form.Item>
          <Form.Item name="notes" label="Notes">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>Create</Button>
        </Form>
      </Modal>

      <Modal title="New project" open={!!projectOpen} onCancel={() => setProjectOpen(null)} footer={null} destroyOnClose>
        <Form form={projectForm} layout="vertical" onFinish={createProject}>
          <Form.Item name="name" label="Project name" rules={[{ required: true }]}>
            <Input placeholder="Website relaunch / Q3 sales" />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="status" label="Status" initialValue="active">
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
        title={taskOpen ? `Task · ${taskOpen.name}` : 'Task'}
        open={!!taskOpen}
        onCancel={() => { setTaskOpen(null); taskForm.resetFields() }}
        footer={null}
        destroyOnClose
      >
        <Form form={taskForm} layout="vertical" onFinish={createTask}>
          <Form.Item name="title" label="Title">
            <Input placeholder="Optional short title" />
          </Form.Item>
          <Form.Item name="description" label="Description" rules={[{ required: true }]}>
            <Input.TextArea rows={3} placeholder="What needs doing?" />
          </Form.Item>
          <Form.Item name="agent_id" label="Agent (optional)">
            <Select
              allowClear
              placeholder="Assign agent to run later"
              options={agents.map(a => ({
                value: a.id,
                label: `${a.name} (${a.status})`,
              }))}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>Add task</Button>
        </Form>
      </Modal>
    </div>
  )
}
