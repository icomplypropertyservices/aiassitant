import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Row, Col, Card, Button, Tag, Modal, Form, Input, Select, Switch, Space,
  message, Empty, Popconfirm, Typography, Dropdown, Segmented, Spin,
} from 'antd'
import {
  PlusOutlined, MessageOutlined, PauseCircleOutlined,
  PlayCircleOutlined, DeleteOutlined, MailOutlined, PhoneOutlined, BulbOutlined,
  CheckCircleOutlined, InfoCircleOutlined, ThunderboltOutlined,
  CrownOutlined, DownOutlined, TeamOutlined, ApartmentOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import { api, createRealtime } from '../api'
import ModelSelect from '../components/ModelSelect'
import OrchestratorBanner from '../components/OrchestratorBanner'
import PageHeader from '../components/PageHeader'
import { modelLabel } from '../models'
import { isOrchestrator, isLead, sortAgents } from '../agents/roles'
import PageShell from '../components/PageShell'
import CoreTeam from '../components/CoreTeam'
import { goBay } from '../publicPaths'


const ICONS = {
  thinking: <BulbOutlined style={{ color: '#faad14' }} />,
  action: <ThunderboltOutlined style={{ color: '#1668dc' }} />,
  email: <MailOutlined style={{ color: '#52c41a' }} />,
  sms: <MessageOutlined style={{ color: '#52c41a' }} />,
  call: <PhoneOutlined style={{ color: '#52c41a' }} />,
  done: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  info: <InfoCircleOutlined style={{ color: '#8c8c8c' }} />,
}

const STATUS_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'active', label: 'Active' },
  { value: 'paused', label: 'Paused' },
]

const ROLE_FILTERS = [
  { value: 'all', label: 'All roles' },
  { value: 'lead', label: 'Leads' },
  { value: 'member', label: 'Members' },
]

/** Always-available catalogue so Spawn never blocks if /templates is empty/cold. */
const FALLBACK_TEMPLATES = [
  { id: 'fb-orchestrator', name: 'Main AI Orchestrator', type: 'orchestrator', unique_fields: [], est_cost: '', ephemeral: true },
  { id: 'fb-lead', name: 'Team Lead', type: 'lead', unique_fields: [], est_cost: '', ephemeral: true },
  { id: 'fb-sales', name: 'Sales Agent', type: 'sales', unique_fields: [], est_cost: '', ephemeral: true },
  { id: 'fb-support', name: 'Support Agent', type: 'support', unique_fields: [], est_cost: '', ephemeral: true },
  { id: 'fb-ops', name: 'Ops Agent', type: 'ops', unique_fields: [], est_cost: '', ephemeral: true },
  { id: 'fb-marketing', name: 'Marketing Agent', type: 'marketing', unique_fields: [], est_cost: '', ephemeral: true },
  { id: 'fb-coding', name: 'Coding Agent', type: 'coding', unique_fields: [], est_cost: '', ephemeral: true },
  { id: 'fb-custom', name: 'Custom agent', type: 'custom', unique_fields: [], est_cost: '', ephemeral: true },
]

function lastActivity(agent) {
  const list = agent?.activity
  if (!Array.isArray(list) || !list.length) return null
  return list[list.length - 1]
}

function clearFilterState(setSearch, setStatusFilter, setRoleFilter) {
  setSearch('')
  setStatusFilter('all')
  setRoleFilter('all')
}

function mergeTemplates(apiList) {
  const list = Array.isArray(apiList) ? apiList.filter(Boolean) : []
  if (list.length) return list
  return FALLBACK_TEMPLATES
}

/**
 * Agent Console — list, filters, and spawn UI as Ant Design Cards inside the
 * centered page shell (PageShell → aba-page-shell-inner / AppLayout aba-page-center).
 * Orchestrator is pinned in OrchestratorBanner; team agents render as a Card grid.
 */
export default function Agents() {
  const nav = useNavigate()
  const loc = useLocation()
  const [agents, setAgents] = useState([])
  const [templates, setTemplates] = useState([])
  const [companies, setCompanies] = useState([])
  const [projects, setProjects] = useState([])
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [roleFilter, setRoleFilter] = useState('all')
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [createBusy, setCreateBusy] = useState(false)
  const [templatesLoading, setTemplatesLoading] = useState(false)
  const [form] = Form.useForm()
  const selectedTemplate = Form.useWatch('template_id', form)
  const watchIsLead = Form.useWatch('is_lead', form)
  const watchCompany = Form.useWatch('company_id', form)
  const wsRef = useRef(null)

  const load = (opts = {}) => {
    const quiet = Boolean(opts.quiet)
    if (!quiet) setLoading(true)
    return api('/agents/')
      .then((list) => setAgents(Array.isArray(list) ? list : []))
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false))
  }

  /** Normalize GET /templates/ payload → array of {id, name, type, ...}. */
  const normalizeTemplateList = (payload) => {
    if (Array.isArray(payload)) return payload
    if (Array.isArray(payload?.templates)) return payload.templates
    if (Array.isArray(payload?.items)) return payload.items
    if (Array.isArray(payload?.data)) return payload.data
    return []
  }

  /**
   * Load agent template catalogue for spawn modal / dropdown.
   * Never leaves the UI empty — falls back to built-in roles.
   */
  const loadTemplates = () => {
    setTemplatesLoading(true)
    return api('/templates/')
      .then(async (t) => {
        let list = normalizeTemplateList(t)
        if (!list.length) {
          try {
            await api('/templates/ensure', { method: 'POST' })
          } catch {
            /* ensure is best-effort */
          }
          try {
            const t2 = await api('/templates/')
            list = normalizeTemplateList(t2)
          } catch {
            list = []
          }
        }
        const merged = mergeTemplates(list)
        setTemplates(merged)
        return merged
      })
      .catch((e) => {
        // Keep spawn usable offline / API blip
        const merged = mergeTemplates([])
        setTemplates((prev) => (prev?.length ? prev : merged))
        if (!templates.length) {
          message.warning(e?.message || 'Using offline templates — spawn still works')
        }
        return mergeTemplates(templates)
      })
      .finally(() => setTemplatesLoading(false))
  }

  useEffect(() => {
    // Seed offline catalogue immediately so Spawn is never empty on first paint
    setTemplates((prev) => (prev?.length ? prev : FALLBACK_TEMPLATES))
    load()
    loadTemplates().then((list) => {
      const tid = loc.state?.templateId
      if (tid != null && list?.length) {
        setCreateOpen(true)
        const t = list.find((x) => x.id === tid || String(x.id) === String(tid) || x.type === tid)
        form.setFieldsValue({
          template_id: t?.id ?? tid,
          name: form.getFieldValue('name') || t?.name || undefined,
          hierarchy_role: t?.type === 'orchestrator' ? 'orchestrator' : (t?.type === 'lead' ? 'lead' : undefined),
          is_lead: t?.type === 'orchestrator' || t?.type === 'lead',
        })
      }
    })
    api('/org/companies')
      .then((c) => setCompanies(Array.isArray(c) ? c : (c?.companies || [])))
      .catch(() => setCompanies([]))
    api('/org/projects')
      .then((p) => setProjects(Array.isArray(p) ? p : (p?.projects || [])))
      .catch(() => setProjects([]))
    const ws = createRealtime({ path: '/agents/ws' })
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data)
      if (m.type === 'auth_ok') return
      if (m.event === 'activity') {
        setAgents((prev) => (Array.isArray(prev) ? prev : []).map((a) => (a.id === m.agent_id
          ? { ...a, activity: [...(a.activity || []).slice(-7), m.entry] }
          : a)))
      }
      if (m.event === 'task_done') load({ quiet: true })
    }
    wsRef.current = ws
    return () => ws.close()
  }, [])

  const createAgent = async (values) => {
    const catalog = templates.length ? templates : FALLBACK_TEMPLATES
    const tpl = catalog.find(
      (t) => t.id === values.template_id || String(t.id) === String(values.template_id),
    )
    const custom_fields = {}
    ;(tpl?.unique_fields || []).forEach((f) => {
      if (f?.name) custom_fields[f.name] = values[`field_${f.name}`] || ''
    })
    const config = { custom_fields }
    const name = (values.name || tpl?.name || 'New agent').trim()
    if (!name) {
      message.error('Enter an agent name')
      return
    }
    setCreateBusy(true)
    try {
      const isOrch = tpl?.type === 'orchestrator' || values.hierarchy_role === 'orchestrator'
      const asLead = isOrch || values.is_lead || tpl?.type === 'lead'
      const a = await api('/agents/', {
        method: 'POST',
        body: {
          name,
          template_type: tpl?.type || values.template_type || 'custom',
          personality: values.personality || 'Professional, friendly and concise.',
          model: values.model || 'vps-fast',
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
      await load({ quiet: true })
      if (a?.id) {
        nav(`/console/${a.id}`)
      }
    } catch (e) {
      const msg = e?.message || 'Could not create agent'
      // Plan / billing guidance
      if (e?.status === 402 || /subscription|plan|billing|402/i.test(msg)) {
        message.error(msg)
        Modal.confirm({
          title: 'Plan required to spawn agents',
          content: msg,
          okText: 'Open Billing',
          cancelText: 'Close',
          onOk: () => nav('/billing'),
        })
      } else {
        message.error(msg)
      }
    } finally {
      setCreateBusy(false)
    }
  }

  const action = async (id, act, e) => {
    e?.stopPropagation?.()
    try {
      await api(`/agents/${id}/${act}`, { method: 'POST' })
      load({ quiet: true })
    } catch (err) {
      message.error(err.message)
    }
  }

  const orch = agents.find((a) => isOrchestrator(a))
  const tpl = (templates.length ? templates : FALLBACK_TEMPLATES).find(
    (t) => t.id === selectedTemplate || String(t.id) === String(selectedTemplate),
  )

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    const list = agents.filter((a) => {
      if (orch?.id && a.id === orch.id) return false
      if (q && !(a.name || '').toLowerCase().includes(q)
        && !(a.template_type || '').toLowerCase().includes(q)
        && !(a.personality || '').toLowerCase().includes(q)) {
        return false
      }
      const st = (a.status || 'active').toLowerCase()
      if (statusFilter === 'active' && st !== 'active') return false
      if (statusFilter === 'paused' && st === 'active') return false
      if (roleFilter === 'lead' && !isLead(a)) return false
      if (roleFilter === 'member' && isLead(a)) return false
      return true
    })
    return sortAgents(list)
  }, [agents, search, statusFilter, roleFilter, orch?.id])

  const openSpawn = (templateId) => {
    // Always open modal immediately — never block on network
    setCreateOpen(true)
    const catalog = templates.length ? templates : FALLBACK_TEMPLATES
    if (!templates.length) {
      setTemplates(FALLBACK_TEMPLATES)
      loadTemplates() // refresh in background
    }
    const applyTemplate = (list, tid) => {
      if (tid == null || tid === '' || tid === 'custom') {
        const custom = (list || []).find((x) => x.type === 'custom') || FALLBACK_TEMPLATES.find((x) => x.type === 'custom')
        form.setFieldsValue({
          template_id: custom?.id,
          hierarchy_role: 'member',
          is_lead: false,
          name: form.getFieldValue('name') || undefined,
        })
        return
      }
      const t = (list || catalog).find(
        (x) => x.id === tid || String(x.id) === String(tid) || x.type === tid,
      )
      const next = { template_id: t?.id ?? tid }
      if (t?.type === 'orchestrator') {
        next.is_lead = true
        next.hierarchy_role = 'orchestrator'
        next.name = form.getFieldValue('name') || t.name || 'Main AI Orchestrator'
      } else if (t?.type === 'lead') {
        next.is_lead = true
        next.hierarchy_role = 'lead'
        next.name = form.getFieldValue('name') || t.name
      } else if (t?.name && !form.getFieldValue('name')) {
        next.name = t.name
      }
      form.setFieldsValue(next)
    }
    applyTemplate(catalog, templateId)
    // If a real API catalogue loads later with matching id, re-apply
    if (!templates.length || templates.every((t) => t.ephemeral)) {
      loadTemplates().then((list) => {
        if (list?.length && templateId != null) applyTemplate(list, templateId)
      })
    }
  }

  const spawnCatalog = templates.length ? templates : FALLBACK_TEMPLATES

  const spawnMenuItems = [
    {
      key: 'custom',
      icon: <PlusOutlined />,
      label: 'Custom agent…',
      onClick: () => openSpawn(null),
    },
    { type: 'divider' },
    {
      key: 'from-template',
      label: `From template (${spawnCatalog.length})`,
      children: spawnCatalog.map((t) => ({
        key: `tpl-${t.id}`,
        label: `${t.type === 'orchestrator' ? '👑 ' : t.type === 'lead' ? '★ ' : ''}${t.name || t.type || `Template #${t.id}`}`,
        onClick: () => openSpawn(t.id),
      })),
    },
    {
      key: 'reload-tpl',
      label: templatesLoading ? 'Loading templates…' : 'Reload templates…',
      disabled: templatesLoading,
      onClick: () => {
        loadTemplates().then((list) => {
          if (list?.length) message.success(`${list.length} templates ready`)
        })
      },
    },
    { type: 'divider' },
    {
      key: 'seed-team',
      icon: <TeamOutlined />,
      label: 'Seed professional team (~20)',
      onClick: async () => {
        const hide = message.loading('Seeding professional team…', 0)
        try {
          let res
          try {
            res = await api('/agents/seed-starter-team', { method: 'POST' })
          } catch (e) {
            // Fall back if starter endpoint is missing (older deploy)
            const msg = String(e?.message || '')
            const notFound = e?.status === 404 || /404|not found|not available/i.test(msg)
            if (!notFound) throw e
            res = await api('/agents/seed-professional-40', { method: 'POST' })
          }
          hide()
          const count = res?.count ?? res?.agents?.length
          message.success(
            res?.message
              || (count != null
                ? `Professional team ready (${count} agents)`
                : 'Professional team seeded'),
          )
          load({ quiet: true })
        } catch (e) {
          hide()
          message.error(e.message || 'Could not seed team')
        }
      },
    },
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

  const hasActiveFilters = Boolean(search.trim()) || statusFilter !== 'all' || roleFilter !== 'all'
  const showEmptyTeam = !loading && agents.filter((a) => a.id !== orch?.id).length === 0
  const showFilteredEmpty = !loading && !showEmptyTeam && filtered.length === 0

  /** Featured templates for quick-spawn strip (leads + common roles). */
  const quickSpawnTemplates = useMemo(() => {
    const source = spawnCatalog
    if (!source.length) return FALLBACK_TEMPLATES.slice(0, 6)
    const preferred = ['orchestrator', 'lead', 'sales', 'support', 'ops', 'coding', 'marketing', 'custom']
    const ranked = [...source].sort((a, b) => {
      const ai = preferred.indexOf(a.type)
      const bi = preferred.indexOf(b.type)
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi)
    })
    return ranked.slice(0, 6)
  }, [spawnCatalog])

  return (
    <PageShell>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {/* Header — boxed Card */}
        <Card className="aba-soft-card" styles={{ body: { paddingBlock: 16 } }}>
          <PageHeader
            title={(
              <span>
                Console{' '}
                <Tag color="blue" style={{ marginInlineStart: 8, verticalAlign: 'middle' }}>
                  {agents.length}
                </Tag>
              </span>
            )}
            subtitle="Your agents in one place — open any chat, manage roles, keep work organised."
            style={{ marginBottom: 0 }}
            extra={(
              <Space wrap>
                <Button
                  icon={<ReloadOutlined />}
                  onClick={() => load({ quiet: agents.length > 0 })}
                  loading={loading && agents.length > 0}
                >
                  Refresh
                </Button>
                <Button icon={<ThunderboltOutlined />} onClick={() => nav('/agent-dash')}>
                  Dashboard
                </Button>
                <Button icon={<ApartmentOutlined />} onClick={() => nav('/hierarchy')}>
                  Hierarchy
                </Button>
                <Button onClick={() => nav('/workspace')}>Workspace</Button>
                <Button
                  type="primary"
                  icon={<PlusOutlined />}
                  className="aba-spawn-agent-btn"
                  onClick={() => openSpawn(null)}
                >
                  Spawn agent
                </Button>
                <Dropdown menu={{ items: spawnMenuItems }} trigger={['click']}>
                  <Button type="primary" icon={<DownOutlined />} className="aba-spawn-agent-btn">
                    More
                  </Button>
                </Dropdown>
              </Space>
            )}
          />
        </Card>

        {/* Core Team — pinned standing roster for every user */}
        <CoreTeam compact />

        {/* Filters — Ant Design Card */}
        <Card
          className="aba-soft-card"
          size="small"
          title="Filters"
          styles={{ body: { padding: '12px 16px' } }}
        >
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Space wrap style={{ width: '100%', justifyContent: 'space-between' }}>
              <Space wrap>
                <Input.Search
                  placeholder="Search name, type, personality…"
                  style={{ width: '100%', maxWidth: 360 }}
                  allowClear
                  size="large"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                <Typography.Text type="secondary">
                  {filtered.length}
                  {hasActiveFilters
                    ? ` match${filtered.length === 1 ? '' : 'es'}`
                    : ' agents'}
                </Typography.Text>
              </Space>
              <Space wrap>
                <Button onClick={() => nav('/tasks')}>Tasks board</Button>
                <Button type="link" href="/bay/browse" style={{ paddingInline: 0 }} onClick={(e) => { e.preventDefault(); goBay('/browse') }}>
                  Browse AgentBay →
                </Button>
              </Space>
            </Space>
            <Space wrap size={[12, 8]}>
              <Segmented
                size="small"
                options={STATUS_FILTERS}
                value={statusFilter}
                onChange={setStatusFilter}
              />
              <Segmented
                size="small"
                options={ROLE_FILTERS}
                value={roleFilter}
                onChange={setRoleFilter}
              />
              {hasActiveFilters && (
                <Button
                  type="link"
                  size="small"
                  style={{ paddingInline: 0 }}
                  onClick={() => clearFilterState(setSearch, setStatusFilter, setRoleFilter)}
                >
                  Clear filters
                </Button>
              )}
            </Space>
          </Space>
        </Card>

        {/* Quick spawn strip — always show so spawn is one tap away */}
        {quickSpawnTemplates.length > 0 && (
          <Card
            className="aba-soft-card"
            size="small"
            title={(
              <Space size={8}>
                <ThunderboltOutlined />
                <span>Quick spawn</span>
              </Space>
            )}
            extra={(
              <Button type="link" size="small" style={{ paddingInline: 0 }} onClick={() => nav('/templates')}>
                All templates
              </Button>
            )}
            styles={{ body: { paddingTop: 12, paddingBottom: 12 } }}
          >
            <Space wrap size={[8, 8]}>
              {quickSpawnTemplates.map((t) => (
                <Button
                  key={t.id}
                  size="small"
                  icon={t.type === 'orchestrator' ? <CrownOutlined /> : <PlusOutlined />}
                  onClick={() => openSpawn(t.id)}
                >
                  {t.name || t.type || `Template #${t.id}`}
                </Button>
              ))}
              <Dropdown menu={{ items: spawnMenuItems }} trigger={['click']}>
                <Button size="small" type="dashed" icon={<PlusOutlined />}>
                  More…
                </Button>
              </Dropdown>
            </Space>
          </Card>
        )}

        {/* Banner is itself a Card; cancel its outer margin so Space owns vertical rhythm */}
        <div className="aba-orch-banner-slot" style={{ marginBottom: -16, width: '100%' }}>
          <OrchestratorBanner orchestrator={orch} onChanged={() => load({ quiet: true })} compact />
        </div>

        {/* Agent list — Ant Design Card grid */}
        <Card
          className="aba-soft-card"
          title={(
            <Space size={8}>
              <TeamOutlined />
              <span>Agent team</span>
              {!loading && !showEmptyTeam && (
                <Tag style={{ marginInlineStart: 4 }}>{filtered.length}</Tag>
              )}
            </Space>
          )}
          extra={(
            <Space size={4}>
              <Button
                type="primary"
                size="small"
                icon={<PlusOutlined />}
                className="aba-spawn-agent-btn"
                onClick={() => openSpawn(null)}
              >
                Spawn agent
              </Button>
              <Dropdown menu={{ items: spawnMenuItems }} trigger={['click']}>
                <Button type="link" icon={<DownOutlined />} style={{ paddingInline: 4 }}>
                  More
                </Button>
              </Dropdown>
            </Space>
          )}
          styles={{ body: { paddingTop: filtered.length || loading ? 16 : 24 } }}
        >
          {loading && agents.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '64px 24px' }}>
              <Spin size="large" tip="Loading agents…" />
            </div>
          ) : showEmptyTeam ? (
            <Empty
              description="No agents yet — spawn one, then open chat"
              style={{ padding: '32px 0' }}
            >
              <Space wrap style={{ marginTop: 8, justifyContent: 'center' }}>
                {quickSpawnTemplates.slice(0, 3).map((t) => (
                  <Button key={t.id} onClick={() => openSpawn(t.id)}>
                    {t.name || t.type}
                  </Button>
                ))}
                <Dropdown menu={{ items: spawnMenuItems }} trigger={['click']}>
                  <Button type="primary" icon={<PlusOutlined />}>
                    Spawn agent <DownOutlined />
                  </Button>
                </Dropdown>
              </Space>
            </Empty>
          ) : showFilteredEmpty ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="No agents match your filters"
              style={{ padding: '32px 0' }}
            >
              <Button onClick={() => clearFilterState(setSearch, setStatusFilter, setRoleFilter)}>
                Clear filters
              </Button>
            </Empty>
          ) : (
            <Row gutter={[16, 16]} justify="center">
              {filtered.map((a) => {
                const act = lastActivity(a)
                return (
                  <Col xs={24} sm={12} lg={8} xl={6} key={a.id}>
                    <Card
                      className="aba-agent-card aba-soft-card aba-card-clickable"
                      hoverable
                      style={{ height: '100%' }}
                      styles={{ body: { padding: 14, height: '100%', display: 'flex', flexDirection: 'column' } }}
                      onClick={() => nav(`/console/${a.id}`)}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontWeight: 700, fontSize: 15, lineHeight: 1.2 }}>{a.name}</div>
                          <Space size={4} style={{ marginTop: 4 }} wrap>
                            <Tag style={{ margin: 0 }}>{a.template_type}</Tag>
                            {isLead(a) && !isOrchestrator(a) && <Tag color="gold" style={{ margin: 0 }}>Lead</Tag>}
                            {isOrchestrator(a) && <Tag color="purple" style={{ margin: 0 }}>Orchestrator</Tag>}
                          </Space>
                        </div>
                        <Tag
                          color={a.status === 'active' ? 'success' : 'warning'}
                          style={{ margin: 0, flexShrink: 0 }}
                        >
                          {a.status}
                        </Tag>
                      </div>

                      <div style={{ margin: '10px 0', fontSize: 12, color: '#666', minHeight: 32, lineHeight: 1.4, flex: 1 }}>
                        {a.personality || 'Your AI teammate'}
                      </div>

                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
                        <Tag color={a.idle_mode === 'never_idle' ? 'purple' : 'default'} style={{ margin: 0 }}>
                          {a.idle_mode === 'never_idle' ? 'Self-running' : 'Idle allowed'}
                        </Tag>
                        <Tag color="blue" style={{ margin: 0 }}>{modelLabel(a.model)}</Tag>
                        {a.permission_level && <Tag style={{ margin: 0 }}>{a.permission_level}</Tag>}
                      </div>

                      {act && (
                        <div
                          style={{
                            fontSize: 11,
                            color: '#8c8c8c',
                            marginBottom: 10,
                            display: 'flex',
                            alignItems: 'center',
                            gap: 6,
                            minHeight: 18,
                          }}
                        >
                          {ICONS[act.kind] || ICONS.info}
                          <span style={{
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                          >
                            {act.message || act.summary || act.kind || 'Activity'}
                          </span>
                        </div>
                      )}

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
                        <Space size={0}>
                          <Button
                            type="link"
                            size="small"
                            onClick={(e) => { e.stopPropagation(); nav(`/console/${a.id}/dash`) }}
                          >
                            Dashboard
                          </Button>
                          <Button
                            type="link"
                            size="small"
                            onClick={(e) => { e.stopPropagation(); nav(`/console/${a.id}/manage`) }}
                          >
                            Settings
                          </Button>
                        </Space>
                        <Space size={2}>
                          {a.status === 'active'
                            ? (
                              <Button
                                type="text"
                                size="small"
                                icon={<PauseCircleOutlined />}
                                onClick={(e) => action(a.id, 'pause', e)}
                              />
                            )
                            : (
                              <Button
                                type="text"
                                size="small"
                                icon={<PlayCircleOutlined />}
                                onClick={(e) => action(a.id, 'resume', e)}
                              />
                            )}
                          <Popconfirm
                            title={`Delete ${a.name}?`}
                            description="Removes the agent and unlinks its chats, tasks, and skills."
                            okText="Delete"
                            okButtonProps={{ danger: true }}
                            cancelText="Cancel"
                            onConfirm={async (e) => {
                              e?.stopPropagation?.()
                              try {
                                await api(`/agents/${a.id}`, { method: 'DELETE' })
                                message.success(`${a.name} deleted`)
                                // Drop from list immediately, then refresh
                                setAgents((prev) => (Array.isArray(prev) ? prev.filter((x) => x.id !== a.id) : prev))
                                load({ quiet: true })
                              } catch (err) {
                                const msg = err?.message || err?.detail || 'Delete failed'
                                message.error(typeof msg === 'string' ? msg : 'Delete failed')
                              }
                            }}
                            onCancel={(e) => e?.stopPropagation?.()}
                          >
                            <Button
                              type="text"
                              size="small"
                              danger
                              icon={<DeleteOutlined />}
                              aria-label={`Delete ${a.name}`}
                              onClick={(e) => e.stopPropagation()}
                            />
                          </Popconfirm>
                        </Space>
                      </div>
                    </Card>
                  </Col>
                )
              })}
            </Row>
          )}
        </Card>
      </Space>

      {/* Spawn UI — Identity / Organisation / Behaviour Cards inside modal */}
      <Modal
        title={(
          <Space>
            <PlusOutlined />
            <span>Spawn agent</span>
          </Space>
        )}
        open={createOpen}
        onCancel={() => { setCreateOpen(false); form.resetFields(); setCreateBusy(false) }}
        onOk={() => form.submit()}
        okText="Create & open chat"
        confirmLoading={createBusy}
        okButtonProps={{ disabled: createBusy, loading: createBusy }}
        destroyOnClose
        centered
        width={560}
        className="aba-spawn-modal"
        styles={{ body: { paddingTop: 12, maxHeight: '70vh', overflowY: 'auto' } }}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={createAgent}
          requiredMark="optional"
          initialValues={{
            model: 'vps-fast',
            personality: 'Professional, friendly and concise.',
            hierarchy_role: 'member',
            is_lead: false,
            template_id: FALLBACK_TEMPLATES.find((t) => t.type === 'custom')?.id,
          }}
        >
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Card size="small" className="aba-soft-card" title="Identity">
              <Form.Item
                name="name"
                label="Agent name"
                rules={[{ required: true, message: 'Name your agent' }]}
                style={{ marginBottom: 12 }}
              >
                <Input placeholder="e.g. Sales Lead or Lead Chaser" autoFocus />
              </Form.Item>
              <Form.Item
                name="template_id"
                label="Template"
                rules={[{ required: true, message: 'Pick a template (or Custom)' }]}
                style={{ marginBottom: (tpl?.unique_fields || []).length ? 12 : 0 }}
                extra={`${spawnCatalog.length} templates available${templatesLoading ? ' · refreshing…' : ''}`}
              >
                <Select
                  showSearch
                  optionFilterProp="label"
                  loading={templatesLoading}
                  notFoundContent={templatesLoading ? 'Loading…' : 'No match'}
                  options={spawnCatalog.map((t) => ({
                    value: t.id,
                    label: `${t.type === 'orchestrator' ? '👑 ' : ''}${t.name || 'Unnamed'} (${t.type || 'custom'})${t.type === 'lead' ? ' ★' : ''}`,
                  }))}
                  placeholder="Choose a template — or Custom agent"
                  onDropdownVisibleChange={(open) => {
                    if (open && templates.every((t) => t.ephemeral)) loadTemplates()
                  }}
                  onChange={(tid) => {
                    const t = spawnCatalog.find((x) => x.id === tid || String(x.id) === String(tid))
                    if (t?.type === 'orchestrator') {
                      form.setFieldsValue({
                        is_lead: true,
                        hierarchy_role: 'orchestrator',
                        name: form.getFieldValue('name') || t.name || 'Main AI Orchestrator',
                      })
                    } else if (t?.type === 'lead') {
                      form.setFieldsValue({
                        is_lead: true,
                        hierarchy_role: 'lead',
                        name: form.getFieldValue('name') || t.name,
                      })
                    } else if (t?.name && !form.getFieldValue('name')) {
                      form.setFieldsValue({ name: t.name })
                    }
                  }}
                />
              </Form.Item>
              {(tpl?.unique_fields || []).map((f, i, arr) => (
                <Form.Item
                  key={f.name}
                  name={`field_${f.name}`}
                  label={f.label}
                  style={{ marginBottom: i === arr.length - 1 ? 0 : 12 }}
                >
                  <Input placeholder={f.placeholder} />
                </Form.Item>
              ))}
            </Card>

            <Card size="small" className="aba-soft-card" title="Organisation">
              <Form.Item name="company_id" label="Company (optional)" style={{ marginBottom: 12 }}>
                <Select
                  allowClear
                  placeholder="Assign to a company"
                  options={companies.map((c) => ({ value: c.id, label: c.name }))}
                  onChange={() => form.setFieldsValue({ project_id: undefined })}
                />
              </Form.Item>
              <Form.Item name="project_id" label="Project (optional)" style={{ marginBottom: 12 }}>
                <Select
                  allowClear
                  placeholder="Assign to a project"
                  options={projects
                    .filter((p) => !watchCompany || p.company_id === watchCompany)
                    .map((p) => ({ value: p.id, label: p.name }))}
                />
              </Form.Item>
              <Form.Item
                name="is_lead"
                label="Lead agent (can have a team)"
                valuePropName="checked"
                style={{ marginBottom: 12 }}
              >
                <Switch checkedChildren="Lead" unCheckedChildren="Member" />
              </Form.Item>
              <Form.Item
                name="hierarchy_role"
                label="Hierarchy role"
                style={{ marginBottom: watchIsLead ? 0 : 12 }}
              >
                <Select options={[
                  { value: 'orchestrator', label: 'Main AI Orchestrator (top)' },
                  { value: 'lead', label: 'Lead' },
                  { value: 'member', label: 'Member' },
                  { value: 'specialist', label: 'Specialist' },
                ]}
                />
              </Form.Item>
              {!watchIsLead && (
                <Form.Item
                  name="parent_id"
                  label="Reports to (lead)"
                  extra="Optional — defaults under Main Orchestrator"
                  style={{ marginBottom: 0 }}
                >
                  <Select
                    allowClear
                    placeholder="No parent (or Main Orchestrator)"
                    options={agents.filter((a) => isLead(a)).map((a) => ({
                      value: a.id,
                      label: `${a.name}${isOrchestrator(a) ? ' ★' : ''}`,
                    }))}
                  />
                </Form.Item>
              )}
            </Card>

            <Card size="small" className="aba-soft-card" title="Behaviour">
              <Form.Item name="personality" label="Personality" style={{ marginBottom: 12 }}>
                <Input.TextArea rows={2} />
              </Form.Item>
              <Form.Item name="model" label="Model" style={{ marginBottom: 12 }}>
                <ModelSelect style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="never_idle" label="Never be idle" valuePropName="checked" style={{ marginBottom: 0 }}>
                <Switch />
              </Form.Item>
            </Card>
          </Space>
        </Form>
      </Modal>
    </PageShell>
  )
}
