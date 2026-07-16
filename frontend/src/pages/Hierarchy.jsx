import React, { useEffect, useState } from 'react'
import {
  Card, Tree, Button, Space, Typography, Tag, Modal, Form, Select, Switch,
  message, Empty, Spin, Row, Col, Statistic, Alert,
} from 'antd'
import {
  TeamOutlined, CrownOutlined, RobotOutlined, ReloadOutlined, ApartmentOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import OrchestratorBanner from '../components/OrchestratorBanner'
import { isOrchestrator, isLead } from '../agents/roles'

function toTreeData(nodes) {
  return (nodes || []).map(n => {
    const isOrch = isOrchestrator(n)
    return {
      key: String(n.id),
      title: (
        <Space
          wrap
          size={4}
          style={isOrch ? {
            background: '#fffbe6',
            border: '1px solid #faad14',
            borderRadius: 8,
            padding: '4px 8px',
          } : undefined}
        >
          {isOrch || isLead(n) ? (
            <CrownOutlined style={{ color: isOrch ? '#d48806' : '#faad14', fontSize: isOrch ? 18 : 14 }} />
          ) : (
            <RobotOutlined style={{ color: '#1668dc' }} />
          )}
          <span style={{ fontWeight: isOrch ? 800 : 600, fontSize: isOrch ? 15 : 14 }}>{n.name}</span>
          {isOrch && <Tag color="gold">MAIN ORCHESTRATOR</Tag>}
          <Tag>{n.template_type}</Tag>
          <Tag color={n.status === 'active' ? 'green' : 'orange'}>{n.status}</Tag>
          {!isOrch && isLead(n) && <Tag color="gold">Lead</Tag>}
          {n.hierarchy_role === 'specialist' && <Tag color="purple">Specialist</Tag>}
          {n.company_name && <Tag color="blue">{n.company_name}</Tag>}
          {n.project_name && <Tag color="cyan">{n.project_name}</Tag>}
          {n.reports_count > 0 && <Tag color="blue">{n.reports_count} reports</Tag>}
        </Space>
      ),
      children: n.children?.length ? toTreeData(n.children) : undefined,
    }
  })
}

export default function Hierarchy() {
  const nav = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [editOpen, setEditOpen] = useState(false)
  const [selected, setSelected] = useState(null)
  const [form] = Form.useForm()

  const load = () => {
    setLoading(true)
    api('/agents/hierarchy')
      .then(setData)
      .catch(e => message.error(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const openEdit = (agentId) => {
    const a = (data?.flat || []).find(x => x.id === agentId)
    if (!a) return
    setSelected(a)
    form.setFieldsValue({
      is_lead: a.is_lead || a.hierarchy_role === 'lead' || a.hierarchy_role === 'orchestrator',
      hierarchy_role: a.hierarchy_role || (a.is_orchestrator ? 'orchestrator' : (a.is_lead ? 'lead' : 'member')),
      parent_id: a.parent_id || undefined,
      report_ids: (data?.flat || []).filter(x => x.parent_id === a.id).map(x => x.id),
    })
    setEditOpen(true)
  }

  const save = async (v) => {
    try {
      await api(`/agents/${selected.id}/hierarchy`, {
        method: 'PUT',
        body: {
          is_lead: v.is_lead,
          hierarchy_role: v.hierarchy_role,
          parent_id: v.parent_id || null,
          clear_parent: !v.parent_id,
          report_ids: v.report_ids || [],
        },
      })
      message.success('Hierarchy updated')
      setEditOpen(false)
      load()
    } catch (e) {
      message.error(e.message)
    }
  }

  if (loading && !data) {
    return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>
  }

  const flat = data?.flat || []
  const leadCount = flat.filter(a => a.is_lead || a.hierarchy_role === 'lead').length
  const memberCount = flat.length - leadCount

  return (
    <div>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }} wrap>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            <ApartmentOutlined /> Agent hierarchy
          </Typography.Title>
          <Typography.Text type="secondary">
            Lead agents orchestrate the team. Assign reports and set who reports to whom.
          </Typography.Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button>
          <Button type="primary" onClick={() => nav('/agents')}>Manage agents</Button>
        </Space>
      </Space>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="How hierarchy works"
        description="Main AI Orchestrator is always at the top (gold). Under it: lead agents and project teams. Allocate agents to projects in Workspace. Leads can delegate tasks from the agent workspace."
      />

      <OrchestratorBanner orchestrator={data?.orchestrator} onChanged={load} />

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={8}><Card><Statistic title="Agents" value={data?.total || 0} prefix={<TeamOutlined />} /></Card></Col>
        <Col xs={8}><Card><Statistic title="Leads" value={leadCount} prefix={<CrownOutlined />} /></Card></Col>
        <Col xs={8}><Card><Statistic title="Members" value={memberCount} prefix={<RobotOutlined />} /></Card></Col>
      </Row>

      <Row gutter={16}>
        <Col xs={24} lg={14}>
          <Card title="Org tree" extra={<Typography.Text type="secondary">Click a node to edit</Typography.Text>}>
            {!data?.tree?.length ? (
              <Empty description="No agents yet — create a Lead Agent from Agents or Templates">
                <Button type="primary" onClick={() => nav('/agents')}>Create agents</Button>
              </Empty>
            ) : (
              <Tree
                showLine
                defaultExpandAll
                treeData={toTreeData(data.tree)}
                onSelect={(keys) => {
                  if (keys[0]) openEdit(Number(keys[0]))
                }}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title="All agents (flat)">
            {(flat).map(a => (
              <div
                key={a.id}
                style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '8px 0', borderBottom: '1px solid #f0f0f0', cursor: 'pointer',
                }}
                onClick={() => nav(`/agents/${a.id}`)}
              >
                <Space wrap>
                  {(isOrchestrator(a) || isLead(a)) && (
                    <CrownOutlined style={{ color: isOrchestrator(a) ? '#d48806' : '#faad14' }} />
                  )}
                  <strong style={isOrchestrator(a) ? { color: '#d48806' } : undefined}>{a.name}</strong>
                  {isOrchestrator(a) && <Tag color="gold">MAIN</Tag>}
                  <Tag>{a.hierarchy_role || 'member'}</Tag>
                  {a.project_name && <Tag color="cyan">{a.project_name}</Tag>}
                  {a.parent_name && <Tag color="default">→ {a.parent_name}</Tag>}
                </Space>
                <Button size="small" onClick={(e) => { e.stopPropagation(); openEdit(a.id) }}>
                  Set hierarchy
                </Button>
              </div>
            ))}
            {!flat.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />}
          </Card>
        </Col>
      </Row>

      <Modal
        title={selected ? `Hierarchy · ${selected.name}` : 'Hierarchy'}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        footer={null}
        destroyOnClose
        width={520}
      >
        <Form form={form} layout="vertical" onFinish={save}>
          <Form.Item name="is_lead" label="Lead agent" valuePropName="checked"
            extra="Lead agents can have direct reports and delegate work">
            <Switch checkedChildren="Lead" unCheckedChildren="Member" />
          </Form.Item>
          <Form.Item name="hierarchy_role" label="Role">
            <Select options={[
              { value: 'orchestrator', label: 'Main AI Orchestrator — always at the top' },
              { value: 'lead', label: 'Lead — orchestrates team' },
              { value: 'member', label: 'Member — reports to a lead' },
              { value: 'specialist', label: 'Specialist — deep skill, optional lead' },
            ]} />
          </Form.Item>
          <Form.Item name="parent_id" label="Reports to (parent lead)"
            extra="Leave empty for top-level">
            <Select
              allowClear
              placeholder="No parent (root)"
              options={(flat)
                .filter(a => a.id !== selected?.id)
                .map(a => ({
                  value: a.id,
                  label: `${a.name}${a.is_lead || a.hierarchy_role === 'lead' ? ' (lead)' : ''}`,
                }))}
            />
          </Form.Item>
          <Form.Item name="report_ids" label="Direct reports"
            extra="Agents that report to this one">
            <Select
              mode="multiple"
              allowClear
              placeholder="Select team members"
              options={(flat)
                .filter(a => a.id !== selected?.id)
                .map(a => ({ value: a.id, label: a.name }))}
            />
          </Form.Item>
          <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
            <Button onClick={() => selected && nav(`/agents/${selected.id}`)}>Open agent</Button>
            <Button type="primary" htmlType="submit">Save hierarchy</Button>
          </Space>
        </Form>
      </Modal>
    </div>
  )
}
