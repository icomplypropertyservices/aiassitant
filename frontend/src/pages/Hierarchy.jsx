import React, { useEffect, useState } from 'react'
import {
  Card, Button, Space, Typography, Tag, Modal, Form, Select, Switch,
  message, Empty, Spin, Row, Col, Statistic, Alert, Checkbox,
} from 'antd'
import {
  TeamOutlined, CrownOutlined, RobotOutlined, ReloadOutlined, ApartmentOutlined,
  CommentOutlined, RocketOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import OrchestratorBanner from '../components/OrchestratorBanner'
import PageHeader from '../components/PageHeader'
import { isOrchestrator, isLead } from '../agents/roles'
import PageShell from '../components/PageShell'
import { LogoLoading } from '../components/BrandLogo'


function parseCheckedAgentIds(checkedKeys) {
  return [...new Set(
    (checkedKeys || []).map(Number).filter((id) => Number.isFinite(id) && id > 0),
  )]
}

function pickChair(selected, agentsFlat = [], preferredId = null) {
  if (preferredId) {
    const preferred = (agentsFlat || []).find((a) => a.id === preferredId)
      || selected.find((a) => a.id === preferredId)
    if (preferred) return preferred
  }
  return (
    selected.find((a) => isOrchestrator(a)) ||
    selected.find((a) => isLead(a)) ||
    selected[0] ||
    null
  )
}

function meetingTitle(prefix, selected, ids) {
  const names = selected.map((a) => a.name).filter(Boolean)
  if (names.length === 1) return `${prefix} · ${names[0]}`
  if (names.length) {
    return `${prefix} · ${names.slice(0, 3).join(', ')}${names.length > 3 ? ` +${names.length - 3}` : ''}`
  }
  return `${prefix} · ${ids.length} agents`
}

/** Create a standup meeting room with the given agent ids. */
export async function createStandupMeeting(agentIds, agentsFlat = []) {
  const ids = parseCheckedAgentIds(agentIds)
  if (!ids.length) {
    throw new Error('Select one or more agents for standup')
  }
  const byId = new Map((agentsFlat || []).map((a) => [a.id, a]))
  const selected = ids.map((id) => byId.get(id)).filter(Boolean)
  const chair = pickChair(selected, agentsFlat)
  const chairId = chair?.id ?? ids[0]

  const body = {
    title: meetingTitle('Standup', selected, ids),
    purpose: 'Daily standup — what was done, what is next, blockers',
    room_type: 'standup',
    chair_agent_id: chairId,
    participants: ids
      .filter((id) => id !== chairId)
      .map((agent_id) => ({ kind: 'agent', agent_id, role: 'member' })),
  }
  return api('/meetings', { method: 'POST', body })
}

/** Goal / war-room meeting for selected agents (orchestrator chairs when available). */
export async function createGoalMeeting(agentIds, agentsFlat = [], orchestrator = null) {
  const ids = parseCheckedAgentIds(agentIds)
  if (!ids.length) {
    throw new Error('Select one or more agents for a goal run')
  }
  const byId = new Map((agentsFlat || []).map((a) => [a.id, a]))
  const selected = ids.map((id) => byId.get(id)).filter(Boolean)
  const orch =
    orchestrator && isOrchestrator(orchestrator)
      ? orchestrator
      : (agentsFlat || []).find((a) => isOrchestrator(a)) || null
  // Include orchestrator in the room when present, even if not multi-selected
  const allIds = orch?.id && !ids.includes(orch.id) ? [orch.id, ...ids] : ids
  const chair = pickChair(
    allIds.map((id) => byId.get(id) || (orch?.id === id ? orch : null)).filter(Boolean),
    agentsFlat,
    orch?.id,
  )
  const chairId = chair?.id ?? orch?.id ?? allIds[0]

  const body = {
    title: meetingTitle('Goal', selected, ids),
    purpose: 'Run goal — orchestrate the team, break work down, report progress and blockers',
    room_type: 'task_war_room',
    chair_agent_id: chairId,
    participants: allIds
      .filter((id) => id !== chairId)
      .map((agent_id) => ({ kind: 'agent', agent_id, role: 'member' })),
  }
  return api('/meetings', { method: 'POST', body })
}

function roomIdOf(room) {
  return room?.id ?? room?.meeting_id ?? room?.meeting?.id ?? null
}

function AgentRoleTags({ agent, compact = false }) {
  const isOrch = isOrchestrator(agent)
  return (
    <Space size={4} wrap>
      {agent.template_type && <Tag style={{ margin: 0 }}>{agent.template_type}</Tag>}
      {agent.status && (
        <Tag color={agent.status === 'active' ? 'green' : 'orange'} style={{ margin: 0 }}>
          {agent.status}
        </Tag>
      )}
      {isOrch && <Tag color="gold" style={{ margin: 0 }}>{compact ? 'MAIN' : 'MAIN ORCHESTRATOR'}</Tag>}
      {!isOrch && isLead(agent) && <Tag color="gold" style={{ margin: 0 }}>Lead</Tag>}
      {agent.hierarchy_role === 'specialist' && <Tag color="purple" style={{ margin: 0 }}>Specialist</Tag>}
      {!compact && agent.company_name && <Tag color="blue" style={{ margin: 0 }}>{agent.company_name}</Tag>}
      {agent.project_name && <Tag color="cyan" style={{ margin: 0 }}>{agent.project_name}</Tag>}
      {!compact && agent.reports_count > 0 && (
        <Tag color="blue" style={{ margin: 0 }}>{agent.reports_count} reports</Tag>
      )}
      {compact && agent.parent_name && (
        <Tag color="default" style={{ margin: 0 }}>→ {agent.parent_name}</Tag>
      )}
      {compact && !agent.parent_name && agent.hierarchy_role && !isOrch && (
        <Tag style={{ margin: 0 }}>{agent.hierarchy_role}</Tag>
      )}
    </Space>
  )
}

/**
 * Recursive org-tree node rendered as nested Ant Design Cards.
 * Depth drives left indent so hierarchy stays readable without Tree.
 */
function HierarchyTreeCards({
  nodes,
  depth = 0,
  checkedKeys,
  onToggle,
  onEdit,
  onOpenAgent,
}) {
  if (!nodes?.length) return null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {nodes.map((n) => {
        const isOrch = isOrchestrator(n)
        const key = String(n.id)
        const checked = checkedKeys.includes(key)
        const hasChildren = Boolean(n.children?.length)

        return (
          <div key={n.id} style={{ marginLeft: depth ? Math.min(depth * 16, 48) : 0 }}>
            <Card
              size="small"
              className={isOrch ? 'aba-soft-card aba-hierarchy-orch-card' : 'aba-soft-card'}
              hoverable
              styles={{
                body: {
                  padding: '10px 12px',
                  background: isOrch ? '#fffbe6' : undefined,
                },
              }}
              style={isOrch ? { borderColor: '#faad14' } : undefined}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 10,
                  flexWrap: 'wrap',
                }}
              >
                <Space wrap size={8} style={{ flex: 1, minWidth: 0 }}>
                  <Checkbox
                    checked={checked}
                    onChange={(e) => onToggle(n.id, e.target.checked)}
                    onClick={(e) => e.stopPropagation()}
                  />
                  {isOrch || isLead(n) ? (
                    <CrownOutlined
                      style={{ color: isOrch ? '#d48806' : '#faad14', fontSize: isOrch ? 18 : 14 }}
                    />
                  ) : (
                    <RobotOutlined style={{ color: '#1668dc' }} />
                  )}
                  <Typography.Text
                    strong
                    style={{
                      fontWeight: isOrch ? 800 : 600,
                      fontSize: isOrch ? 15 : 14,
                      color: isOrch ? '#d48806' : undefined,
                      cursor: 'pointer',
                    }}
                    onClick={() => onEdit(n.id)}
                  >
                    {n.name}
                  </Typography.Text>
                  <AgentRoleTags agent={n} />
                </Space>
                <Space size={4} wrap>
                  <Button
                    size="small"
                    type="link"
                    style={{ paddingInline: 4 }}
                    onClick={() => onOpenAgent(n.id)}
                  >
                    Open
                  </Button>
                  <Button size="small" onClick={() => onEdit(n.id)}>
                    Set hierarchy
                  </Button>
                </Space>
              </div>
            </Card>
            {hasChildren && (
              <div style={{ marginTop: 10 }}>
                <HierarchyTreeCards
                  nodes={n.children}
                  depth={depth + 1}
                  checkedKeys={checkedKeys}
                  onToggle={onToggle}
                  onEdit={onEdit}
                  onOpenAgent={onOpenAgent}
                />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** Flat agent row as a compact Card */
function AgentListCard({ agent, checked, onToggle, onEdit, onOpenAgent }) {
  const isOrch = isOrchestrator(agent)
  return (
    <Card
      size="small"
      className="aba-soft-card"
      hoverable
      styles={{
        body: {
          padding: '10px 12px',
          background: isOrch ? '#fffbe6' : undefined,
        },
      }}
      style={isOrch ? { borderColor: '#faad14', marginBottom: 0 } : { marginBottom: 0 }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 8,
          flexWrap: 'wrap',
        }}
      >
        <Space wrap style={{ flex: 1, minWidth: 0 }} size={8}>
          <Checkbox
            checked={checked}
            onChange={(e) => onToggle(agent.id, e.target.checked)}
          />
          {(isOrch || isLead(agent)) && (
            <CrownOutlined style={{ color: isOrch ? '#d48806' : '#faad14' }} />
          )}
          <Typography.Text
            strong
            style={{ color: isOrch ? '#d48806' : undefined, cursor: 'pointer' }}
            onClick={() => onOpenAgent(agent.id)}
            role="link"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter') onOpenAgent(agent.id) }}
          >
            {agent.name}
          </Typography.Text>
          <AgentRoleTags agent={agent} compact />
        </Space>
        <Button size="small" onClick={() => onEdit(agent.id)}>
          Set hierarchy
        </Button>
      </div>
    </Card>
  )
}

export default function Hierarchy() {
  const nav = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [editOpen, setEditOpen] = useState(false)
  const [selected, setSelected] = useState(null)
  const [checkedKeys, setCheckedKeys] = useState([])
  const [actionBusy, setActionBusy] = useState(false)
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

  const toggleChecked = (agentId, checked) => {
    const key = String(agentId)
    setCheckedKeys((prev) => {
      if (checked) return prev.includes(key) ? prev : [...prev, key]
      return prev.filter((k) => k !== key)
    })
  }

  const openAgent = (id) => nav(`/agents/${id}`)

  const openStandup = async (overrideIds = null, { closeEdit = false } = {}) => {
    const ids = overrideIds || parseCheckedAgentIds(checkedKeys)
    if (!ids.length) {
      message.warning('Check one or more agents, then open standup')
      return
    }
    setActionBusy(true)
    try {
      const room = await createStandupMeeting(ids, data?.flat || [])
      const roomId = roomIdOf(room)
      if (!roomId) throw new Error('Meeting created but no id returned')
      message.success('Standup meeting opened')
      setCheckedKeys([])
      if (closeEdit) setEditOpen(false)
      nav(`/meetings/${roomId}`)
    } catch (e) {
      message.error(e.message || 'Failed to open standup')
    } finally {
      setActionBusy(false)
    }
  }

  /** Selected agents → goal war-room; else open orchestrator chat. */
  const runGoal = async () => {
    const ids = parseCheckedAgentIds(checkedKeys)
    const flat = data?.flat || []
    const orch = data?.orchestrator || flat.find((a) => isOrchestrator(a)) || null

    if (ids.length) {
      setActionBusy(true)
      try {
        const room = await createGoalMeeting(ids, flat, orch)
        const roomId = roomIdOf(room)
        if (!roomId) throw new Error('Meeting created but no id returned')
        message.success('Goal room opened')
        setCheckedKeys([])
        nav(`/meetings/${roomId}`)
      } catch (e) {
        message.error(e.message || 'Failed to open goal room')
      } finally {
        setActionBusy(false)
      }
      return
    }

    if (orch?.id) {
      nav(`/agents/${orch.id}`)
      return
    }
    message.warning('Create a Main Orchestrator first, or check agents for a goal room')
  }

  if (loading && !data) {
    return (
      <PageShell>
        <Card className="aba-soft-card">
          <LogoLoading tip="Loading hierarchy…" minHeight={280} />
        </Card>
      </PageShell>
    )
  }

  const flat = data?.flat || []
  const leadCount = flat.filter(a => a.is_lead || a.hierarchy_role === 'lead').length
  const memberCount = flat.length - leadCount
  const selectedCount = checkedKeys.length

  /** Standup / goal / clear — shown in tree + flat Card extras */
  const selectionControls = (
    <Space size={4} wrap>
      <Button
        size="small"
        type="primary"
        icon={<CommentOutlined />}
        loading={actionBusy}
        disabled={!selectedCount}
        onClick={() => openStandup()}
      >
        {selectedCount ? `Standup (${selectedCount})` : 'Standup'}
      </Button>
      <Button
        size="small"
        icon={<RocketOutlined />}
        loading={actionBusy}
        onClick={runGoal}
      >
        {selectedCount ? `Run goal (${selectedCount})` : 'Run goal'}
      </Button>
      {selectedCount > 0 && (
        <Button size="small" onClick={() => setCheckedKeys([])}>Clear</Button>
      )}
    </Space>
  )

  return (
    <PageShell>
      <PageHeader
        title={(
          <span>
            <ApartmentOutlined style={{ marginRight: 8 }} />
            Agent hierarchy
          </span>
        )}
        subtitle="Lead agents orchestrate the team. Assign reports and set who reports to whom."
        extra={(
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>Refresh</Button>
            <Button onClick={() => nav('/console')}>Open console</Button>
          </Space>
        )}
      />

      <div className="aba-box" style={{ marginBottom: 16 }}>
        <Alert
          type="info"
          showIcon
          message="How hierarchy works"
          description="Main AI Orchestrator is always at the top (gold). Check agents in the tree or flat list, then use Standup or Run goal in the card header. Click a name to edit hierarchy."
        />
      </div>

      <OrchestratorBanner orchestrator={data?.orchestrator} onChanged={load} />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={8}>
          <Card className="aba-stat-card" size="small">
            <Statistic title="Agents" value={data?.total || 0} prefix={<TeamOutlined />} />
          </Card>
        </Col>
        <Col xs={8}>
          <Card className="aba-stat-card" size="small">
            <Statistic title="Leads" value={leadCount} prefix={<CrownOutlined />} />
          </Card>
        </Col>
        <Col xs={8}>
          <Card className="aba-stat-card" size="small">
            <Statistic title="Members" value={memberCount} prefix={<RobotOutlined />} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card
            className="aba-soft-card aba-hierarchy-section-card"
            title={(
              <Space size={8}>
                <ApartmentOutlined />
                <span>Org tree</span>
                {data?.tree?.length > 0 && (
                  <Tag style={{ marginInlineStart: 4 }}>{data.total || flat.length}</Tag>
                )}
              </Space>
            )}
            extra={selectionControls}
            styles={{
              header: { textAlign: 'center' },
            }}
          >
            <Typography.Text
              type="secondary"
              style={{ display: 'block', marginBottom: 12, textAlign: 'center' }}
            >
              Nested cards by reporting line · check agents for standup / goal · click name to edit
            </Typography.Text>
            {!data?.tree?.length ? (
              <Empty description="No agents yet — create a Lead Agent from Agents or Templates">
                <Button type="primary" onClick={() => nav('/console')}>Create agents</Button>
              </Empty>
            ) : (
              <HierarchyTreeCards
                nodes={data.tree}
                checkedKeys={checkedKeys}
                onToggle={toggleChecked}
                onEdit={openEdit}
                onOpenAgent={openAgent}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card
            className="aba-soft-card aba-hierarchy-section-card"
            title={(
              <Space size={8}>
                <TeamOutlined />
                <span>All agents</span>
                {flat.length > 0 && <Tag style={{ marginInlineStart: 4 }}>{flat.length}</Tag>}
              </Space>
            )}
            extra={selectionControls}
            styles={{
              header: { textAlign: 'center' },
              body: { paddingTop: flat.length ? 12 : 24 },
            }}
          >
            {flat.length ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {flat.map((a) => (
                  <AgentListCard
                    key={a.id}
                    agent={a}
                    checked={checkedKeys.includes(String(a.id))}
                    onToggle={toggleChecked}
                    onEdit={openEdit}
                    onOpenAgent={openAgent}
                  />
                ))}
              </div>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No agents yet" />
            )}
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
        centered
      >
        <Form form={form} layout="vertical" onFinish={save}>
          <Form.Item
            name="is_lead"
            label="Lead agent"
            valuePropName="checked"
            extra="Lead agents can have direct reports and delegate work"
          >
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
          <Form.Item
            name="parent_id"
            label="Reports to (parent lead)"
            extra="Leave empty for top-level"
          >
            <Select
              allowClear
              placeholder="No parent (root)"
              options={flat
                .filter((a) => a.id !== selected?.id)
                .map((a) => ({
                  value: a.id,
                  label: `${a.name}${a.is_lead || a.hierarchy_role === 'lead' ? ' (lead)' : ''}`,
                }))}
            />
          </Form.Item>
          <Form.Item
            name="report_ids"
            label="Direct reports"
            extra="Agents that report to this one"
          >
            <Select
              mode="multiple"
              allowClear
              placeholder="Select team members"
              options={flat
                .filter((a) => a.id !== selected?.id)
                .map((a) => ({ value: a.id, label: a.name }))}
            />
          </Form.Item>
          <Space style={{ width: '100%', justifyContent: 'flex-end' }} wrap>
            <Button
              icon={<CommentOutlined />}
              loading={actionBusy}
              onClick={() => {
                if (!selected?.id) return
                const reportIds = flat.filter((x) => x.parent_id === selected.id).map((x) => x.id)
                openStandup([selected.id, ...reportIds], { closeEdit: true })
              }}
            >
              Standup with reports
            </Button>
            <Button onClick={() => selected && nav(`/agents/${selected.id}`)}>Open agent</Button>
            <Button type="primary" htmlType="submit">Save hierarchy</Button>
          </Space>
        </Form>
      </Modal>
    </PageShell>
  )
}
