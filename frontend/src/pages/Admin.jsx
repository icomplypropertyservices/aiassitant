import React, { useEffect, useState, useCallback, useRef } from 'react'
import {
  Card, Table, Row, Col, Statistic, Tabs, Tag, Result, Button, Space, Input,
  InputNumber, message, Select, Alert, Typography, Spin, Descriptions, Switch,
  Popconfirm, Divider,
} from 'antd'
import { useNavigate } from 'react-router-dom'
import { api, getUser } from '../api'

const { Text, Paragraph, Title } = Typography
const { TextArea } = Input

export default function Admin() {
  const nav = useNavigate()
  const user = getUser()
  const [stats, setStats] = useState(null)
  const [users, setUsers] = useState([])
  const [agents, setAgents] = useState([])
  const [fleet, setFleet] = useState(null)
  const [usageByModel, setUsageByModel] = useState([])
  const [recentUsage, setRecentUsage] = useState([])
  const [mapEdits, setMapEdits] = useState({})
  const [topupUser, setTopupUser] = useState(null)
  const [topupAmount, setTopupAmount] = useState(10)
  const [pullTag, setPullTag] = useState('qwen2.5:7b')
  const [customPull, setCustomPull] = useState('')
  const [busy, setBusy] = useState(false)
  const [connForm, setConnForm] = useState({
    ollama_url: '',
    webui_url: '',
    api_key: '',
    support_notes: '',
    agent_terminal_enabled: true,
  })
  const [consoleCmd, setConsoleCmd] = useState('list')
  const [consoleOut, setConsoleOut] = useState('')
  const [consoleHistory, setConsoleHistory] = useState([])
  const [opsTeam, setOpsTeam] = useState(null)
  const consoleEndRef = useRef(null)

  const load = useCallback(() => {
    if (user?.role !== 'admin') return
    api('/admin/stats').then(setStats).catch(() => {})
    api('/admin/users').then(setUsers).catch(() => {})
    api('/admin/agents').then(setAgents).catch(() => {})
    api('/admin/fleet/status').then((f) => {
      setFleet(f)
      setMapEdits(f.model_map || {})
      const c = f.connection || {}
      setConnForm((prev) => ({
        ollama_url: c.ollama_url || '',
        webui_url: c.webui_url || '',
        api_key: '', // never prefill secrets
        support_notes: c.support_notes || '',
        agent_terminal_enabled: c.agent_terminal_enabled !== false,
        api_key_set: c.api_key_set,
      }))
    }).catch(() => {})
    api('/admin/ops-team').then(setOpsTeam).catch(() => {})
    api('/admin/usage/by-model').then(setUsageByModel).catch(() => {})
    api('/admin/usage/recent?limit=50').then(setRecentUsage).catch(() => {})
  }, [user?.role])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    consoleEndRef.current?.scrollIntoView?.({ behavior: 'smooth' })
  }, [consoleOut, consoleHistory])

  if (user?.role !== 'admin') {
    return (
      <Result
        status="403"
        title="Access denied"
        subTitle="Staff admin is only available to users with the admin role."
        extra={<Button type="primary" onClick={() => nav('/')}>Back to dashboard</Button>}
      />
    )
  }

  const saveMap = async () => {
    setBusy(true)
    try {
      await api('/admin/fleet/model-map', {
        method: 'PUT',
        body: { mapping: mapEdits },
      })
      message.success('Model routing updated — customers keep the same Fast/Quality labels')
      load()
    } catch (e) {
      message.error(e.message || 'Failed to save map')
    } finally {
      setBusy(false)
    }
  }

  const saveConnection = async () => {
    setBusy(true)
    try {
      const body = {
        ollama_url: connForm.ollama_url?.trim() || '',
        webui_url: connForm.webui_url?.trim() || '',
        support_notes: connForm.support_notes || '',
        agent_terminal_enabled: !!connForm.agent_terminal_enabled,
      }
      if (connForm.api_key && !connForm.api_key.startsWith('***')) {
        body.api_key = connForm.api_key
      }
      await api('/admin/fleet/connection', { method: 'PUT', body })
      message.success('Connection saved — live without redeploy')
      setConnForm((p) => ({ ...p, api_key: '' }))
      load()
    } catch (e) {
      message.error(e.message || 'Save failed')
    } finally {
      setBusy(false)
    }
  }

  const doTopup = async () => {
    if (!topupUser) return message.warning('Select a user')
    setBusy(true)
    try {
      const r = await api('/admin/wallet/topup', {
        method: 'POST',
        body: { user_id: topupUser, amount_usd: topupAmount, note: 'admin top-up' },
      })
      message.success(`Topped up $${topupAmount} → ${r.email} (balance $${r.credits})`)
      load()
    } catch (e) {
      message.error(e.message || 'Top-up failed')
    } finally {
      setBusy(false)
    }
  }

  const doPull = async (tag) => {
    const t = (tag || pullTag || customPull || '').trim()
    if (!t) return message.warning('Enter a model tag')
    setBusy(true)
    try {
      await api('/admin/fleet/pull', { method: 'POST', body: { tag: t } })
      message.success(`Pull completed for ${t}`)
      load()
    } catch (e) {
      message.error(e.message || 'Pull failed — large models can time out; retry or use console')
    } finally {
      setBusy(false)
    }
  }

  const doDelete = async (tag) => {
    setBusy(true)
    try {
      await api('/admin/fleet/delete', { method: 'POST', body: { tag } })
      message.success(`Removed ${tag}`)
      load()
    } catch (e) {
      message.error(e.message || 'Delete failed')
    } finally {
      setBusy(false)
    }
  }

  const doTest = async (tag) => {
    setBusy(true)
    try {
      const r = await api('/admin/fleet/test', {
        method: 'POST',
        body: { tag: tag || 'fast', prompt: 'Say hello in one short sentence.' },
      })
      message.success(`Test OK (${r.tag})`)
      setConsoleOut((prev) => `${prev}\n\n> test ${r.tag}\n${r.reply || ''}`.trim())
    } catch (e) {
      message.error(e.message || 'Test failed')
    } finally {
      setBusy(false)
    }
  }

  const runConsole = async (cmd) => {
    const command = (cmd || consoleCmd || '').trim()
    if (!command) return
    setBusy(true)
    try {
      const r = await api('/admin/fleet/console', {
        method: 'POST',
        body: { command },
      })
      const block = `> ${r.command || command}\n${r.output || ''}`
      setConsoleHistory((h) => [...h.slice(-30), { ok: r.ok, block }])
      setConsoleOut((prev) => `${prev}\n\n${block}`.trim())
      if (r.ok) message.success('Command finished')
      else message.warning('Command failed')
      if (/^(list|pull|rm|delete)/i.test(command.replace(/^ollama\s+/i, ''))) load()
    } catch (e) {
      message.error(e.message || 'Console error')
      setConsoleOut((prev) => `${prev}\n\n> ${command}\nERROR: ${e.message}`.trim())
    } finally {
      setBusy(false)
    }
  }

  const copySupportBundle = async () => {
    try {
      const b = await api('/admin/fleet/support-bundle')
      const text = JSON.stringify(b, null, 2)
      await navigator.clipboard.writeText(text)
      message.success('Support bundle copied — paste into Grok chat to grant setup context')
    } catch (e) {
      message.error(e.message || 'Copy failed')
    }
  }

  const ensureOpsTeam = async () => {
    setBusy(true)
    try {
      const r = await api('/admin/ops-team/ensure', { method: 'POST', body: {} })
      message.success(`Staff ops team ready (${(r.agents || []).length} agents)`)
      setOpsTeam(null)
      load()
    } catch (e) {
      message.error(e.message || 'Failed to create ops team')
    } finally {
      setBusy(false)
    }
  }

  const probeOk = fleet?.probe?.ok
  const webui = fleet?.webui_url
  const modelBadge = (m) => {
    if (!m) return 'default'
    if (String(m).includes('grok')) return 'gold'
    if (m === 'reasoning') return 'purple'
    if (m === 'quality') return 'blue'
    if (m === 'fast' || m === 'small') return 'cyan'
    return 'default'
  }

  return (
    <div className="aba-admin-page" style={{ maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}>
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={12} md={6}><Card size="small"><Statistic title="Users" value={stats?.users ?? 0} /></Card></Col>
        <Col xs={12} sm={12} md={6}><Card size="small"><Statistic title="Agents" value={stats?.agents ?? 0} /></Card></Col>
        <Col xs={12} sm={12} md={6}><Card size="small"><Statistic title="Total tokens" value={stats?.total_tokens ?? 0} /></Card></Col>
        <Col xs={12} sm={12} md={6}><Card size="small"><Statistic title="Revenue" prefix="$" precision={4} value={stats?.total_revenue ?? 0} /></Card></Col>
      </Row>

      <Alert
        type={probeOk ? 'success' : 'warning'}
        showIcon
        style={{ marginBottom: 16 }}
        message={probeOk ? 'Managed LLM fleet is reachable' : 'Managed LLM fleet offline or not configured'}
        description={
          probeOk
            ? `${fleet?.probe?.count ?? 0} models · ${fleet?.probe?.latency_ms ?? '?'} ms · customers only see Fast / Quality / Reasoning / Large`
            : 'Open the Connection tab, paste your RunPod Ollama proxy URL, Save, then pull models.'
        }
        action={<Button size="small" onClick={load}>Refresh</Button>}
        className="aba-admin-alert"
      />

      <Card styles={{ body: { paddingInline: 12, overflow: 'hidden' } }}>
        <Tabs
          tabBarStyle={{ marginBottom: 12 }}
          className="aba-admin-tabs"
          items={[
          {
            key: 'ops-team',
            label: 'Admin Ops Team',
            children: (
              <Spin spinning={busy}>
                <Space direction="vertical" style={{ width: '100%' }} size="large">
                  <Alert
                    type="info"
                    showIcon
                    message="Staff day-to-day operations"
                    description={
                      <>
                        <div><Text strong>Staff Admin Orchestrator</Text> — routes day-to-day admin issues (Qwen quality on RunPod).</div>
                        <div><Text strong>Server Monitor</Text> — fleet / uptime specialist on <Text strong>highest Grok</Text> only.</div>
                        <div>Fleet Ops, Billing Ops, Security Ops — Qwen or DeepSeek (reasoning) on RunPod. Not shown to customers.</div>
                      </>
                    }
                  />
                  <Space wrap>
                    <Button type="primary" onClick={ensureOpsTeam}>
                      {(opsTeam?.agents || []).length ? 'Repair / update ops team' : 'Create staff ops team'}
                    </Button>
                    <Button onClick={load}>Refresh</Button>
                    <Button
                      type="link"
                      disabled={!opsTeam?.agents?.length}
                      onClick={() => {
                        const orch = (opsTeam?.agents || []).find((a) => a.template_type === 'staff_orchestrator')
                        if (orch) nav(`/agents/${orch.id}`)
                        else message.info('Create the team first')
                      }}
                    >
                      Open Staff Orchestrator chat
                    </Button>
                    <Button
                      type="link"
                      disabled={!opsTeam?.agents?.length}
                      onClick={() => {
                        const mon = (opsTeam?.agents || []).find((a) => a.template_type === 'server_monitor')
                        if (mon) nav(`/agents/${mon.id}`)
                        else message.info('Create the team first')
                      }}
                    >
                      Open Server Monitor (Grok)
                    </Button>
                  </Space>
                  <Card type="inner" title="Blueprint (models)">
                    <Table
                      size="small"
                      rowKey="template_type"
                      pagination={false}
                      dataSource={opsTeam?.spec || [
                        { name: 'Staff Admin Orchestrator', template_type: 'staff_orchestrator', model: 'quality', role: 'lead' },
                        { name: 'Server Monitor Specialist', template_type: 'server_monitor', model: 'grok-max', role: 'specialist' },
                        { name: 'Fleet Ops Specialist', template_type: 'fleet_ops', model: 'fast', role: 'specialist' },
                        { name: 'Billing Ops Specialist', template_type: 'billing_ops', model: 'fast', role: 'specialist' },
                        { name: 'Security Ops Specialist', template_type: 'security_ops', model: 'reasoning', role: 'specialist' },
                      ]}
                      columns={[
                        { title: 'Agent', dataIndex: 'name', ellipsis: true },
                        { title: 'Type', dataIndex: 'template_type', width: 140, ellipsis: true },
                        {
                          title: 'Model tier',
                          dataIndex: 'model',
                          width: 110,
                          render: (m) => <Tag color={modelBadge(m)}>{m}</Tag>,
                        },
                        { title: 'Role', dataIndex: 'role', width: 100 },
                      ]}
                    />
                  </Card>
                  <Card type="inner" title="Live staff agents on this admin account">
                    <Table
                      size="small"
                      rowKey="id"
                      pagination={false}
                      dataSource={opsTeam?.agents || []}
                      locale={{ emptyText: 'No staff ops agents yet — click Create staff ops team' }}
                      columns={[
                        { title: 'Name', dataIndex: 'name', ellipsis: true },
                        { title: 'Type', dataIndex: 'template_type', width: 140, ellipsis: true },
                        {
                          title: 'Model',
                          dataIndex: 'model',
                          width: 110,
                          render: (m) => <Tag color={modelBadge(m)}>{m}</Tag>,
                        },
                        { title: 'Role', dataIndex: 'hierarchy_role', width: 100 },
                        {
                          title: 'Status',
                          dataIndex: 'status',
                          width: 90,
                          render: (s) => <Tag color={s === 'active' ? 'green' : 'orange'}>{s}</Tag>,
                        },
                        {
                          title: '',
                          width: 90,
                          render: (_, r) => (
                            <Button size="small" type="link" onClick={() => nav(`/agents/${r.id}`)}>
                              Chat
                            </Button>
                          ),
                        },
                      ]}
                    />
                  </Card>
                  {opsTeam?.probe && (
                    <Alert
                      type={opsTeam.probe.ok ? 'success' : 'warning'}
                      showIcon
                      message={opsTeam.probe.ok ? 'Fleet reachable for Server Monitor' : 'Fleet offline — Server Monitor will flag this'}
                      description={
                        opsTeam.probe.ok
                          ? `${opsTeam.probe.count || 0} models · ${opsTeam.probe.latency_ms || '?'} ms`
                          : (opsTeam.probe.error || 'Configure Connection first')
                      }
                    />
                  )}
                </Space>
              </Spin>
            ),
          },
          {
            key: 'connection',
            label: 'Connection',
            children: (
              <Spin spinning={busy}>
                <Space direction="vertical" style={{ width: '100%' }} size="large">
                  <Alert
                    type="info"
                    showIcon
                    message="Connect RunPod without redeploying"
                    description="Paste the HTTP proxy URLs from RunPod → Pod → Connect. Saved to the database so production keeps them. Then use Terminal / Models tabs to add models."
                  />
                  <Card type="inner" title="Pod endpoints">
                    <Space direction="vertical" style={{ width: '100%' }} size="middle">
                      <div>
                        <Text strong>Ollama URL (port 11434)</Text>
                        <Input
                          style={{ marginTop: 4 }}
                          placeholder="https://xxxxx-11434.proxy.runpod.net"
                          value={connForm.ollama_url}
                          onChange={(e) => setConnForm({ ...connForm, ollama_url: e.target.value })}
                        />
                      </div>
                      <div>
                        <Text strong>Open WebUI URL (port 8080, optional)</Text>
                        <Input
                          style={{ marginTop: 4 }}
                          placeholder="https://xxxxx-8080.proxy.runpod.net"
                          value={connForm.webui_url}
                          onChange={(e) => setConnForm({ ...connForm, webui_url: e.target.value })}
                        />
                      </div>
                      <div>
                        <Text strong>API key / auth header (optional)</Text>
                        <Input.Password
                          style={{ marginTop: 4 }}
                          placeholder={connForm.api_key_set ? 'Leave blank to keep existing' : 'If you put auth in front of Ollama'}
                          value={connForm.api_key}
                          onChange={(e) => setConnForm({ ...connForm, api_key: e.target.value })}
                        />
                      </div>
                      <div>
                        <Text strong>Support notes (for you / Grok)</Text>
                        <TextArea
                          rows={3}
                          style={{ marginTop: 4 }}
                          placeholder="Pod ID, GPU type, region, SSH notes…"
                          value={connForm.support_notes}
                          onChange={(e) => setConnForm({ ...connForm, support_notes: e.target.value })}
                        />
                      </div>
                      <Space>
                        <Switch
                          checked={!!connForm.agent_terminal_enabled}
                          onChange={(v) => setConnForm({ ...connForm, agent_terminal_enabled: v })}
                        />
                        <Text>Enable fleet terminal (list / pull / rm / test for admin & assisted setup)</Text>
                      </Space>
                      <Space wrap>
                        <Button type="primary" onClick={saveConnection}>Save connection</Button>
                        <Button onClick={() => doTest('fast')}>Test Fast model</Button>
                        <Button onClick={copySupportBundle}>Copy support bundle for Grok</Button>
                      </Space>
                      <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                        <Text strong>Give Grok access:</Text> save connection → click “Copy support bundle” → paste into this chat.
                        Grok can then guide you; you (or Grok with your admin session) run Terminal commands here.
                        Full free shell stays on RunPod’s own web terminal for first-time install only.
                      </Paragraph>
                    </Space>
                  </Card>
                </Space>
              </Spin>
            ),
          },
          {
            key: 'terminal',
            label: 'Fleet terminal',
            children: (
              <Spin spinning={busy}>
                <Space direction="vertical" style={{ width: '100%' }} size="middle">
                  <Alert
                    type="info"
                    showIcon
                    message="Safe ops console (not a free shell)"
                    description={
                      fleet?.console_help
                      || 'list | pull <tag> | rm <tag> | show <tag> | test <tag> [prompt] | ps | help'
                    }
                  />
                  <div
                    style={{
                      background: '#0d1117',
                      color: '#c9d1d9',
                      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                      fontSize: 12,
                      padding: 12,
                      borderRadius: 8,
                      minHeight: 220,
                      maxHeight: 360,
                      overflow: 'auto',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                    }}
                  >
                    {consoleOut || 'Ready. Try: list\nThen: pull qwen2.5:7b\nThen: test qwen2.5:7b'}
                    <div ref={consoleEndRef} />
                  </div>
                  <Space.Compact style={{ width: '100%' }}>
                    <Input
                      value={consoleCmd}
                      onChange={(e) => setConsoleCmd(e.target.value)}
                      onPressEnter={() => runConsole()}
                      placeholder="pull qwen2.5:7b"
                      style={{ fontFamily: 'monospace' }}
                    />
                    <Button type="primary" onClick={() => runConsole()}>Run</Button>
                  </Space.Compact>
                  <Space wrap>
                    <Button size="small" onClick={() => runConsole('list')}>list</Button>
                    <Button size="small" onClick={() => runConsole('ps')}>ps</Button>
                    <Button size="small" onClick={() => runConsole('help')}>help</Button>
                    <Button size="small" onClick={() => { setConsoleOut(''); setConsoleHistory([]) }}>Clear</Button>
                  </Space>
                  {(fleet?.ops_log || []).length > 0 && (
                    <Card type="inner" title="Recent ops" size="small">
                      <Table
                        size="small"
                        rowKey={(r) => r.ts + r.action}
                        pagination={false}
                        dataSource={fleet.ops_log}
                        columns={[
                          { title: 'When', dataIndex: 'ts', width: 180, ellipsis: true },
                          {
                            title: 'OK',
                            dataIndex: 'ok',
                            width: 56,
                            render: (v) => <Tag color={v ? 'green' : 'red'}>{v ? 'yes' : 'no'}</Tag>,
                          },
                          { title: 'Action', dataIndex: 'action', width: 100 },
                          { title: 'Detail', dataIndex: 'detail', ellipsis: true },
                        ]}
                      />
                    </Card>
                  )}
                </Space>
              </Spin>
            ),
          },
          {
            key: 'fleet',
            label: 'Models & routing',
            children: (
              <Spin spinning={busy}>
                <Space direction="vertical" style={{ width: '100%' }} size="large">
                  <Descriptions bordered size="small" column={1}>
                    <Descriptions.Item label="Hardware (start)">
                      Tier A: <Text strong>1× RTX 4090 24GB</Text> or <Text strong>A40 48GB</Text> — Ollama + Open WebUI.
                    </Descriptions.Item>
                    <Descriptions.Item label="Customer view">
                      Only neutral names: Fast, Quality, Reasoning, Large — never GPU/provider names.
                    </Descriptions.Item>
                  </Descriptions>

                  <Card type="inner" title="Route customer tiers → Ollama tags">
                    <Paragraph type="secondary">
                      Change supply without redeploying. Agents keep Fast/Quality; you point them at different weights.
                    </Paragraph>
                    <Row gutter={[12, 12]}>
                      {['fast', 'quality', 'reasoning', 'large', 'small', 'medium'].map((k) => (
                        <Col xs={24} md={12} key={k}>
                          <Text strong style={{ textTransform: 'capitalize' }}>{k}</Text>
                          <Input
                            value={mapEdits[k] || ''}
                            onChange={(e) => setMapEdits({ ...mapEdits, [k]: e.target.value })}
                            placeholder="e.g. qwen2.5:14b"
                            style={{ marginTop: 4 }}
                          />
                        </Col>
                      ))}
                    </Row>
                    <Button type="primary" style={{ marginTop: 12 }} onClick={saveMap}>Save routing</Button>
                  </Card>

                  <Card type="inner" title="Models on the GPU host">
                    <Table
                      size="small"
                      rowKey="name"
                      pagination={{ pageSize: 8 }}
                      scroll={{ x: true }}
                      dataSource={fleet?.probe?.models || []}
                      columns={[
                        { title: 'Ollama tag', dataIndex: 'name', ellipsis: true },
                        {
                          title: 'Size',
                          dataIndex: 'size',
                          width: 96,
                          render: (s) => (s ? `${(s / 1e9).toFixed(1)} GB` : '—'),
                        },
                        {
                          title: '',
                          width: 160,
                          fixed: 'right',
                          render: (_, row) => (
                            <Space size="small">
                              <Button size="small" onClick={() => doTest(row.name)}>Test</Button>
                              <Popconfirm
                                title={`Delete ${row.name}?`}
                                onConfirm={() => doDelete(row.name)}
                              >
                                <Button size="small" danger>Remove</Button>
                              </Popconfirm>
                            </Space>
                          ),
                        },
                      ]}
                      locale={{ emptyText: 'No models — save Connection, then pull models' }}
                    />
                    <Divider />
                    <Title level={5} style={{ marginTop: 0 }}>Add / pull model</Title>
                    <Space wrap style={{ width: '100%' }}>
                      <Select
                        style={{ width: '100%', minWidth: 0, maxWidth: 360 }}
                        value={pullTag}
                        onChange={setPullTag}
                        options={(fleet?.recommended || []).map((r) => ({
                          value: r.tag,
                          label: `${r.tag} (~${r.vram_gb}GB · ${r.tier})`,
                        }))}
                        showSearch
                        popupMatchSelectWidth={false}
                      />
                      <Button type="primary" onClick={() => doPull(pullTag)}>Pull selected</Button>
                    </Space>
                    <Space wrap style={{ marginTop: 12, width: '100%' }}>
                      <Input
                        style={{ maxWidth: 360 }}
                        placeholder="Custom tag e.g. llama3.1:8b"
                        value={customPull}
                        onChange={(e) => setCustomPull(e.target.value)}
                        onPressEnter={() => doPull(customPull)}
                      />
                      <Button onClick={() => doPull(customPull)}>Pull custom</Button>
                    </Space>
                  </Card>

                  <Card type="inner" title="Usage by model (customer billing)">
                    <Table
                      size="small"
                      rowKey="model"
                      scroll={{ x: true }}
                      dataSource={usageByModel}
                      columns={[
                        { title: 'Model', dataIndex: 'model', ellipsis: true },
                        { title: 'Tokens', dataIndex: 'tokens', width: 90 },
                        { title: 'Calls', dataIndex: 'calls', width: 72 },
                        { title: 'Revenue', dataIndex: 'cost', width: 96, render: (v) => `$${v}` },
                      ]}
                    />
                  </Card>
                </Space>
              </Spin>
            ),
          },
          {
            key: 'tokens',
            label: 'Tokens & top-up',
            children: (
              <Space direction="vertical" style={{ width: '100%' }} size="large">
                <Alert
                  type="info"
                  showIcon
                  message="Monitoring agent view"
                  description={`Low-credit users: ${stats?.low_credit_users ?? 0}. Top up wallets so agents keep serving customers.`}
                />
                <Card type="inner" title="Top up customer wallet">
                  <Space wrap style={{ width: '100%' }}>
                    <Select
                      style={{ width: '100%', minWidth: 0, maxWidth: 360 }}
                      placeholder="Select customer"
                      value={topupUser}
                      onChange={setTopupUser}
                      options={users.map((u) => ({
                        value: u.id,
                        label: `${u.email} · $${u.credits} · ${u.tokens} tok`,
                      }))}
                      showSearch
                      optionFilterProp="label"
                      popupMatchSelectWidth={false}
                    />
                    <InputNumber
                      min={1}
                      max={100000}
                      value={topupAmount}
                      onChange={setTopupAmount}
                      prefix="$"
                      style={{ width: 120 }}
                    />
                    <Button type="primary" loading={busy} onClick={doTopup}>Top up</Button>
                  </Space>
                </Card>
                <Table
                  rowKey="id"
                  size="small"
                  scroll={{ x: 720 }}
                  dataSource={users}
                  columns={[
                    { title: 'Email', dataIndex: 'email', ellipsis: true, width: 180 },
                    { title: 'Plan', dataIndex: 'plan', width: 90 },
                    { title: 'Credits', dataIndex: 'credits', width: 90, render: (v) => `$${v}` },
                    { title: 'Included', width: 110, render: (_, r) => `${r.tokens_used_period || 0} / ${r.tokens_included || '—'}` },
                    { title: 'Tokens', dataIndex: 'tokens', width: 90 },
                    { title: 'Spend', dataIndex: 'spend', width: 90, render: (v) => `$${v}` },
                    {
                      title: '',
                      width: 80,
                      fixed: 'right',
                      render: (_, r) => (
                        <Button size="small" onClick={() => { setTopupUser(r.id); message.info(`Selected ${r.email}`) }}>
                          Select
                        </Button>
                      ),
                    },
                  ]}
                />
                <Card type="inner" title="Recent usage">
                  <Table
                    size="small"
                    rowKey="id"
                    scroll={{ x: 520 }}
                    dataSource={recentUsage}
                    columns={[
                      { title: 'User', dataIndex: 'user', ellipsis: true },
                      { title: 'Model', dataIndex: 'model', ellipsis: true, width: 100 },
                      { title: 'In', dataIndex: 'input_tokens', width: 72 },
                      { title: 'Out', dataIndex: 'output_tokens', width: 72 },
                      { title: 'Cost', dataIndex: 'cost', width: 80, render: (v) => `$${v}` },
                    ]}
                  />
                </Card>
              </Space>
            ),
          },
          {
            key: 'webui',
            label: 'Open WebUI',
            children: webui ? (
              <div>
                <Paragraph>
                  Ops console for the GPU host. Customers never see this tab.
                  <Button type="link" href={webui} target="_blank" rel="noreferrer">Open in new tab</Button>
                </Paragraph>
                <iframe
                  title="Open WebUI"
                  src={webui}
                  style={{ width: '100%', height: '70vh', border: '1px solid #333', borderRadius: 8 }}
                  sandbox="allow-same-origin allow-scripts allow-forms allow-popups"
                />
              </div>
            ) : (
              <Result
                status="info"
                title="WebUI URL not set"
                subTitle="Save WebUI URL under Connection (e.g. https://xxxxx-8080.proxy.runpod.net)."
              />
            ),
          },
          {
            key: 'users',
            label: 'User management',
            children: (
              <Table
                rowKey="id"
                size="small"
                scroll={{ x: 720 }}
                dataSource={users}
                columns={[
                  { title: 'Email', dataIndex: 'email', ellipsis: true },
                  { title: 'Name', dataIndex: 'name', ellipsis: true, width: 120 },
                  { title: 'Role', dataIndex: 'role', width: 90, render: (r) => <Tag color={r === 'admin' ? 'gold' : 'default'}>{r}</Tag> },
                  { title: 'Plan', dataIndex: 'plan', width: 90 },
                  { title: 'Credits', dataIndex: 'credits', width: 90, render: (v) => `$${v}` },
                  { title: 'Agents', dataIndex: 'agents', width: 80 },
                  { title: 'Tokens', dataIndex: 'tokens', width: 90 },
                  { title: 'Spend', dataIndex: 'spend', width: 90, render: (v) => `$${v}` },
                ]}
              />
            ),
          },
          {
            key: 'agents',
            label: 'Agents oversight',
            children: (
              <Table
                rowKey="id"
                size="small"
                scroll={{ x: 640 }}
                dataSource={agents}
                columns={[
                  { title: 'Agent', dataIndex: 'name', ellipsis: true },
                  { title: 'Owner', dataIndex: 'owner', ellipsis: true, width: 140 },
                  { title: 'Template', dataIndex: 'template_type', ellipsis: true, width: 120 },
                  { title: 'Model', dataIndex: 'model', ellipsis: true, width: 100 },
                  { title: 'Status', dataIndex: 'status', width: 100, render: (s) => <Tag color={s === 'active' ? 'green' : 'orange'}>{s}</Tag> },
                  { title: 'Idle', dataIndex: 'idle_mode', width: 90 },
                ]}
              />
            ),
          },
        ]}
        />
      </Card>
    </div>
  )
}
