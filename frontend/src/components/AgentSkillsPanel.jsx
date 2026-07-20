import React, { useMemo, useState } from 'react'
import {
  Card, Space, Typography, Tag, List, Switch, Button, Form, Input, Select, message, Tooltip, Alert, Segmented,
} from 'antd'
import {
  ThunderboltOutlined, RobotOutlined, AppstoreOutlined, TeamOutlined,
  RocketOutlined, FunnelPlotOutlined, PictureOutlined, NodeIndexOutlined,
  CustomerServiceOutlined,
} from '@ant-design/icons'
import { api } from '../api'

/**
 * CRM + multi-agent workflow core — mirrors backend skills_policy._CORE_ALWAYS
 * subset so one click unlocks market-leading agent tooling without enabling the full free set.
 */
export const RECOMMENDED_CRM_WORKFLOW_SKILLS = [
  // Workflow / goals
  'create_task', 'execute_goal', 'create_workflow', 'announce_plan',
  'create_pattern', 'list_patterns', 'run_pattern', 'review_task',
  'message_agent', 'status_update', 'notify_human', 'list_team',
  'list_tasks', 'search_tasks', 'get_task', 'update_task', 'complete_task',
  'claim_task', 'set_task_status', 'respond_to_task',
  // CRM customers + diary
  'list_customers', 'get_customer', 'create_customer', 'update_customer',
  'log_customer_activity', 'schedule_meeting', 'list_diary',
  // Pipeline + deals
  'list_pipelines', 'get_pipeline', 'list_pipeline_stages', 'pipeline_summary',
  'ensure_sales_pipeline', 'list_deals', 'create_deal', 'update_deal',
  'move_deal', 'win_deal', 'lose_deal',
  // Products
  'list_products', 'get_product', 'search_products', 'create_product',
  'update_product', 'write_product', 'set_product_offer', 'archive_product',
  // Comms drafts (free) + workspace
  'draft_email', 'draft_sms', 'log_communication', 'generate_content',
  'research', 'summarize', 'save_memory', 'save_training',
  'read_workspace', 'search_knowledge', 'action_items', 'prioritize_list',
]

/** Friendly category labels (aligned with backend skills_policy.CATEGORY_LABELS). */
const CATEGORY_LABELS = {
  core: 'Core ops',
  crm: 'CRM & diary',
  comms: 'Communication',
  google: 'Google',
  sales: 'Sales',
  support: 'Support',
  content: 'Content & marketing',
  code: 'Engineering',
  data: 'Data & analytics',
  finance: 'Finance',
  hr: 'HR',
  legal: 'Legal & risk',
  design: 'Design & brand',
  social: 'Social',
  commerce: 'Commerce',
  automation: 'Automation',
  ops: 'Ops & process',
  media: 'Media',
  meta: 'Team / meta',
  other: 'Other',
  workflow: 'Workflows',
}

const CATEGORY_ORDER = [
  'crm', 'sales', 'comms', 'media', 'ops', 'core', 'content', 'automation',
  'google', 'support', 'commerce', 'data', 'code', 'finance', 'hr', 'legal',
  'design', 'social', 'meta', 'workflow', 'other',
]

function skillCategory(s) {
  return s?.category || s?.category_label || 'other'
}

function categoryLabel(cat) {
  return CATEGORY_LABELS[cat] || String(cat || 'Other').replace(/_/g, ' ')
}

/** Agent manage page — Skills tab body. */
export default function AgentSkillsPanel({
  id, skills, setSkills, skillBusy, setSkillBusy,
  templates, spawnForm, load, setAllAgents, agentApps, humans, nav,
}) {
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [showFilter, setShowFilter] = useState('all') // all | on | off | free

  const recommendedMissing = useMemo(() => {
    if (!skills?.length) return []
    const pack = new Set(RECOMMENDED_CRM_WORKFLOW_SKILLS)
    return skills.filter(
      (s) => pack.has(s.id) && s.role_allowed && !s.premium && !s.enabled,
    )
  }, [skills])

  const enabledCount = useMemo(
    () => (skills || []).filter((s) => s.enabled).length,
    [skills],
  )

  const categoriesPresent = useMemo(() => {
    const counts = {}
    for (const s of skills || []) {
      const c = skillCategory(s)
      counts[c] = (counts[c] || 0) + 1
    }
    return CATEGORY_ORDER
      .filter((c) => counts[c])
      .map((c) => ({ value: c, label: `${categoryLabel(c)} (${counts[c]})` }))
  }, [skills])

  const filteredSkills = useMemo(() => {
    let list = skills || []
    if (categoryFilter !== 'all') {
      list = list.filter((s) => skillCategory(s) === categoryFilter)
    }
    if (showFilter === 'on') list = list.filter((s) => s.enabled)
    if (showFilter === 'off') list = list.filter((s) => !s.enabled && s.role_allowed)
    if (showFilter === 'free') list = list.filter((s) => !s.premium && s.role_allowed)
    // Stable: enabled first, then by category, then name
    return [...list].sort((a, b) => {
      if (!!b.enabled !== !!a.enabled) return a.enabled ? -1 : 1
      const ca = skillCategory(a)
      const cb = skillCategory(b)
      if (ca !== cb) return ca.localeCompare(cb)
      return String(a.name || a.id).localeCompare(String(b.name || b.id))
    })
  }, [skills, categoryFilter, showFilter])

  const enableRecommendedPack = async () => {
    const pack = new Set(RECOMMENDED_CRM_WORKFLOW_SKILLS)
    // Enable CRM+workflow core that exists + role allows; keep anything already on
    // (including premium) so we never strip tooling.
    const alreadyOn = skills.filter((s) => s.enabled).map((s) => s.id)
    const packIds = skills
      .filter((s) => pack.has(s.id) && s.role_allowed && !s.premium)
      .map((s) => s.id)
    const enabled = [...new Set([...alreadyOn, ...packIds])]
    if (!packIds.length) {
      message.info('Recommended pack not available for this role')
      return
    }
    setSkillBusy(true)
    try {
      const r = await api(`/agents/${id}/skills`, {
        method: 'PUT',
        body: { enabled },
      })
      setSkills(r.skills || [])
      const turnedOn = recommendedMissing.length
      message.success(
        turnedOn
          ? `Enabled recommended pack (+${turnedOn} CRM & workflow skills)`
          : (r.message || 'Recommended pack already enabled'),
      )
    } catch (e) {
      message.error(e.message || 'Could not enable recommended pack')
    } finally {
      setSkillBusy(false)
    }
  }

  const recommendedPackTip =
    'Turns on core CRM + multi-agent workflow skills (customers, deals, pipelines, products, create_workflow / execute_goal, tasks). Keeps anything already enabled; does not enable premium send skills.'

  const packReady = skills.length > 0 && recommendedMissing.length === 0

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {/* Primary CTA — always obvious when pack is incomplete */}
      {recommendedMissing.length > 0 ? (
        <Alert
          type="success"
          showIcon
          icon={<RocketOutlined />}
          message="Unlock CRM + multi-agent tools in one click"
          description={(
            <span>
              {recommendedMissing.length} recommended skills still off — customers, deals, pipelines,
              workflows (<Typography.Text code>create_workflow</Typography.Text> /{' '}
              <Typography.Text code>execute_goal</Typography.Text>), and draft outreach.
              Keeps anything already on; does not enable premium send.
            </span>
          )}
          action={(
            <Button
              type="primary"
              size="middle"
              icon={<RocketOutlined />}
              loading={skillBusy}
              onClick={enableRecommendedPack}
            >
              Enable recommended pack
            </Button>
          )}
          style={{ borderColor: '#52c41a' }}
        />
      ) : skills.length > 0 ? (
        <Alert
          type="info"
          showIcon
          message="Recommended CRM + workflow pack is on"
          description="Tune categories below, or enable media / premium delivery when you need real send."
        />
      ) : null}

      <Card bordered size="small" className="aba-soft-card">
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          Skills are the tools this agent can use: CRM, workflows, media, apps, and team actions.
          Enable what you need; chat may emit <Typography.Text code>{'```skill'}</Typography.Text> blocks automatically.
        </Typography.Paragraph>
        <Space wrap>
          <Tooltip title={recommendedPackTip}>
            <span>
              <Button
                type={packReady ? 'default' : 'primary'}
                size="middle"
                icon={<RocketOutlined />}
                loading={skillBusy}
                disabled={!skills.length || recommendedMissing.length === 0}
                onClick={enableRecommendedPack}
              >
                {packReady ? 'Recommended pack on' : 'Enable recommended pack'}
              </Button>
            </span>
          </Tooltip>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {recommendedMissing.length
              ? `${recommendedMissing.length} CRM + workflow skills not yet on`
              : skills.length
                ? 'CRM + workflow pack ready'
                : 'Loading skills…'}
          </Typography.Text>
          {enabledCount > 0 && (
            <Tag color="blue" icon={<ThunderboltOutlined />}>
              {enabledCount} enabled
            </Tag>
          )}
        </Space>
      </Card>

      {/* Discovery hints — CRM, media, workflows */}
      <Card
        bordered
        size="small"
        className="aba-soft-card"
        title={(
          <Space>
            <AppstoreOutlined />
            <span>What to enable</span>
          </Space>
        )}
      >
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Space align="start" wrap>
            <FunnelPlotOutlined style={{ color: '#1668dc', marginTop: 4 }} />
            <div>
              <Typography.Text strong>CRM</Typography.Text>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 13 }}>
                <Typography.Text code>list_customers</Typography.Text>,{' '}
                <Typography.Text code>create_customer</Typography.Text>,{' '}
                <Typography.Text code>qualify_lead</Typography.Text>,{' '}
                <Typography.Text code>create_deal</Typography.Text>, pipelines & diary —
                filter category <Tag style={{ marginInlineStart: 4 }}>CRM & diary</Tag>
                <Tag>Sales</Tag>
              </Typography.Paragraph>
            </div>
          </Space>
          <Space align="start" wrap>
            <NodeIndexOutlined style={{ color: '#722ed1', marginTop: 4 }} />
            <div>
              <Typography.Text strong>Workflows</Typography.Text>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 13 }}>
                <Typography.Text code>create_workflow</Typography.Text>,{' '}
                <Typography.Text code>execute_goal</Typography.Text>,{' '}
                <Typography.Text code>run_pattern</Typography.Text>,{' '}
                <Typography.Text code>review_task</Typography.Text> —
                multi-step team runs from the agent dashboard.
              </Typography.Paragraph>
            </div>
          </Space>
          <Space align="start" wrap>
            <PictureOutlined style={{ color: '#d48806', marginTop: 4 }} />
            <div>
              <Typography.Text strong>Media</Typography.Text>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 13 }}>
                Image / video generation skills live under{' '}
                <Tag color="gold">Media</Tag>
                — often premium. Draft email/SMS under Communication stays free.
              </Typography.Paragraph>
            </div>
          </Space>
          <Space wrap>
            <Button
              size="small"
              icon={<FunnelPlotOutlined />}
              onClick={() => { setCategoryFilter('crm'); setShowFilter('all') }}
            >
              Show CRM
            </Button>
            <Button
              size="small"
              icon={<CustomerServiceOutlined />}
              onClick={() => { setCategoryFilter('sales'); setShowFilter('all') }}
            >
              Show sales
            </Button>
            <Button
              size="small"
              icon={<PictureOutlined />}
              onClick={() => { setCategoryFilter('media'); setShowFilter('all') }}
            >
              Show media
            </Button>
            <Button size="small" onClick={() => { setCategoryFilter('all'); setShowFilter('all') }}>
              Clear filters
            </Button>
            {nav && (
              <Button size="small" type="link" onClick={() => nav('/business')}>
                Open CRM
              </Button>
            )}
          </Space>
        </Space>
      </Card>

      <Card
        bordered
        size="small"
        className="aba-soft-card"
        title={(
          <Space wrap>
            <ThunderboltOutlined />
            <span>Enabled skills</span>
            {skills.length > 0 && (
              <Tag color="blue">
                {enabledCount}/{skills.length}
              </Tag>
            )}
          </Space>
        )}
        extra={skills.length > 0 ? (
          <Space wrap size={[8, 4]}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {skills.filter((s) => s.enabled && !s.premium).length}/
              {skills.filter((s) => !s.premium && s.role_allowed).length} free on
            </Typography.Text>
            <Tooltip title={recommendedPackTip}>
              <span>
                <Button
                  size="small"
                  type={packReady ? 'default' : 'primary'}
                  ghost={!packReady}
                  icon={<RocketOutlined />}
                  loading={skillBusy}
                  disabled={recommendedMissing.length === 0}
                  onClick={enableRecommendedPack}
                >
                  Recommended pack
                </Button>
              </span>
            </Tooltip>
            <Button
              size="small"
              type="primary"
              ghost
              loading={skillBusy}
              disabled={
                !skills.some((s) => !s.premium && s.role_allowed && !s.enabled)
              }
              onClick={async () => {
                // PUT /agents/:id/skills — enable every free role-allowed skill;
                // keep any already-enabled premium skills.
                const freeIds = skills
                  .filter((s) => !s.premium && s.role_allowed)
                  .map((s) => s.id)
                const premiumOn = skills
                  .filter((s) => s.premium && s.enabled)
                  .map((s) => s.id)
                const enabled = [...new Set([...freeIds, ...premiumOn])]
                setSkillBusy(true)
                try {
                  const r = await api(`/agents/${id}/skills`, {
                    method: 'PUT',
                    body: { enabled },
                  })
                  setSkills(r.skills || [])
                  message.success(`Enabled ${freeIds.length} free skills`)
                } catch (e) {
                  message.error(e.message)
                } finally {
                  setSkillBusy(false)
                }
              }}
            >
              Enable all free
            </Button>
          </Space>
        ) : null}
      >
        {skills.length > 0 && (
          <Space direction="vertical" size={8} style={{ width: '100%', marginBottom: 12 }}>
            <Space wrap style={{ width: '100%' }}>
              <Select
                size="small"
                style={{ minWidth: 180 }}
                value={categoryFilter}
                onChange={setCategoryFilter}
                options={[
                  { value: 'all', label: `All categories (${skills.length})` },
                  ...categoriesPresent,
                ]}
              />
              <Segmented
                size="small"
                value={showFilter}
                onChange={setShowFilter}
                options={[
                  { value: 'all', label: 'All' },
                  { value: 'on', label: 'On' },
                  { value: 'off', label: 'Off' },
                  { value: 'free', label: 'Free' },
                ]}
              />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Showing {filteredSkills.length}
              </Typography.Text>
            </Space>
          </Space>
        )}
        <List
          dataSource={filteredSkills}
          locale={{
            emptyText: skills.length
              ? 'No skills match this filter'
              : 'Loading skills…',
          }}
          renderItem={(s) => (
            <List.Item
              actions={[
                <Switch
                  key="en"
                  checked={!!s.enabled}
                  disabled={!s.role_allowed}
                  onChange={async (checked) => {
                    const enabled = skills
                      .filter((x) => (x.id === s.id ? checked : x.enabled))
                      .map((x) => x.id)
                    try {
                      const r = await api(`/agents/${id}/skills`, { method: 'PUT', body: { enabled } })
                      setSkills(r.skills || [])
                      message.success('Skills updated')
                    } catch (e) { message.error(e.message) }
                  }}
                />,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space wrap>
                    <ThunderboltOutlined />
                    <span>{s.name}</span>
                    <Tag>{s.id}</Tag>
                    <Tag color="geekblue">{categoryLabel(skillCategory(s))}</Tag>
                    {s.enabled && <Tag color="success">on</Tag>}
                    {s.premium && <Tag color="gold">PREMIUM • {s.cost_credits || 0.02} credits</Tag>}
                    {!s.role_allowed && <Tag color="orange">role blocked</Tag>}
                  </Space>
                }
                description={
                  <div>
                    {s.description}
                    {s.premium && (
                      <div style={{ fontSize: 11, color: '#d48806', marginTop: 2 }}>
                        Real delivery (Email/SMS/WhatsApp/Voice) — charged per use
                      </div>
                    )}
                  </div>
                }
              />
            </List.Item>
          )}
        />
      </Card>

      <Card bordered size="small" className="aba-soft-card" title={<Space><RobotOutlined /> Spawn agent</Space>}>
        <Typography.Paragraph type="secondary" style={{ fontSize: 13, marginTop: 0 }}>
          Add a specialist under this agent from a template. Prefer enabling tools above so new agents can use CRM and workflows immediately.
        </Typography.Paragraph>
        <Form
          form={spawnForm}
          layout="vertical"
          style={{ maxWidth: 520 }}
          onFinish={async (v) => {
            setSkillBusy(true)
            try {
              const tid = v.template_id
              const tpl = tid === '__custom__' ? null : templates.find((t) => t.id === tid || String(t.id) === String(tid))
              const body = {
                name: (v.name || tpl?.name || 'New agent').trim(),
                template_type: tpl?.type || v.template_type || 'custom',
                hierarchy_role: v.hierarchy_role || 'member',
                personality: v.personality || 'Professional, helpful, concise.',
                parent_id: Number(id),
              }
              const r = await api(`/agents/${id}/spawn`, { method: 'POST', body })
              if (r?.ok === false || r?.error) {
                throw new Error(r.error || r.message || 'Spawn failed')
              }
              message.success(r.message || `Spawned ${body.name}`)
              spawnForm.resetFields()
              spawnForm.setFieldsValue({ hierarchy_role: 'member', template_type: 'custom', template_id: '__custom__' })
              load()
              api('/agents/').then(setAllAgents).catch(() => {})
              const childId = r?.agent?.id
              if (childId) {
                message.success(`${body.name} ready — open skills to enable the CRM pack`)
              }
            } catch (e) {
              const msg = e?.message || 'Spawn failed'
              message.error(msg)
              if (e?.status === 402 || /subscription|plan|billing/i.test(msg)) {
                message.info('Open Billing to activate a plan, then try again')
              }
            } finally { setSkillBusy(false) }
          }}
          initialValues={{ hierarchy_role: 'member', template_type: 'custom', template_id: '__custom__' }}
        >
          <Form.Item name="name" label="Name" rules={[{ required: true, message: 'Name the new agent' }]}>
            <Input placeholder="e.g. Sales specialist" />
          </Form.Item>
          <Form.Item
            name="template_id"
            label="Template"
            rules={[{ required: true, message: 'Choose a template' }]}
            extra={templates.length ? `${templates.length} templates` : 'Using built-in roles'}
          >
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="Pick a template"
              options={[
                { value: '__custom__', label: 'Custom (generic agent)' },
                ...templates.map((t) => ({
                  value: t.id,
                  label: `${t.type === 'orchestrator' ? '👑 ' : ''}${t.name || 'Unnamed'} (${t.type || 'custom'})`,
                })),
              ]}
              onChange={(tid) => {
                const t = templates.find((x) => x.id === tid || String(x.id) === String(tid))
                if (t) {
                  spawnForm.setFieldsValue({
                    template_type: t.type,
                    name: spawnForm.getFieldValue('name') || t.name,
                  })
                } else {
                  spawnForm.setFieldsValue({ template_type: 'custom' })
                }
              }}
            />
          </Form.Item>
          <Form.Item name="template_type" hidden><Input /></Form.Item>
          <Form.Item name="hierarchy_role" label="Role">
            <Select options={[
              { value: 'member', label: 'Member' },
              { value: 'specialist', label: 'Specialist' },
              { value: 'lead', label: 'Lead' },
            ]} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={skillBusy} block icon={<RobotOutlined />} className="aba-spawn-agent-btn">
            Spawn under this agent
          </Button>
        </Form>
      </Card>

      <Card bordered size="small" className="aba-soft-card" title={<Space><AppstoreOutlined /> Use connected app</Space>}>
        <Space wrap>
          {(agentApps || []).map((c) => (
            <Button
              key={c.id}
              loading={skillBusy}
              onClick={async () => {
                setSkillBusy(true)
                try {
                  const r = await api(`/agents/${id}/skills/run`, {
                    method: 'POST',
                    body: { skill: 'use_app', args: { app_id: c.app_id, action: 'status' } },
                  })
                  if (r.ok) message.success(r.message || `${c.app_name} OK`)
                  else message.error(r.error || 'App action failed')
                } catch (e) { message.error(e.message) }
                finally { setSkillBusy(false) }
              }}
            >
              Test {c.app_name || c.app_id}
            </Button>
          ))}
          {!agentApps?.length && (
            <Typography.Text type="secondary">
              Link apps in Settings → Connected apps, then allocate to this agent.
            </Typography.Text>
          )}
        </Space>
      </Card>

      <Card bordered size="small" className="aba-soft-card" title={<Space><TeamOutlined /> Assign human</Space>}>
        <Space wrap>
          {humans.filter((h) => h.status === 'active').map((h) => (
            <Button
              key={h.id}
              onClick={async () => {
                const title = window.prompt(`Task title for ${h.name}`, 'Please handle this work item')
                if (!title) return
                setSkillBusy(true)
                try {
                  const r = await api(`/agents/${id}/skills/run`, {
                    method: 'POST',
                    body: { skill: 'assign_human', args: { human_id: h.id, title, description: title } },
                  })
                  if (r.ok) message.success(r.message)
                  else message.error(r.error)
                } catch (e) { message.error(e.message) }
                finally { setSkillBusy(false) }
              }}
            >
              <TeamOutlined /> {h.name}
            </Button>
          ))}
          {!humans.length && <Button type="link" onClick={() => nav('/humans')}>Add humans</Button>}
        </Space>
      </Card>
    </Space>
  )
}
