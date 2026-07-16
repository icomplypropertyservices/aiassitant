import React, { useEffect, useMemo, useState } from 'react'
import {
  Card, Descriptions, Typography, Alert, Form, Input, Button, Tag, Space, message,
  Spin, Divider, List, Popconfirm, Modal, Tabs, Select, Badge, Row, Col, Empty,
} from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined, LockOutlined, KeyOutlined, DeleteOutlined,
  SafetyCertificateOutlined, ApiOutlined, AppstoreOutlined, RobotOutlined,
  LinkOutlined, ReloadOutlined, UserOutlined, ExperimentOutlined, CloudOutlined,
} from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import { getUser, setAuth, getToken, API, api } from '../api'
import { connStatusColor, partitionKeys } from './settings/helpers'

const { Text, Paragraph, Title } = Typography

function StatusTag({ ok, label }) {
  return (
    <Tag icon={ok ? <CheckCircleOutlined /> : <CloseCircleOutlined />} color={ok ? 'success' : 'default'}>
      {label}: {ok ? 'live' : 'not configured'}
    </Tag>
  )
}

export default function Settings() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialTab = searchParams.get('tab') || 'profile'
  const [tab, setTab] = useState(initialTab)

  const [user, setUser] = useState(getUser())
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  // API keys vault
  const [keys, setKeys] = useState([])
  const [keysLoading, setKeysLoading] = useState(true)
  const [providers, setProviders] = useState([])
  const [keyModal, setKeyModal] = useState(null)
  const [keySaving, setKeySaving] = useState(false)
  const [keyForm] = Form.useForm()

  // Connected apps
  const [catalog, setCatalog] = useState([])
  const [categories, setCategories] = useState([])
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [connections, setConnections] = useState([])
  const [appsLoading, setAppsLoading] = useState(true)
  const [agents, setAgents] = useState([])
  const [connectModal, setConnectModal] = useState(null) // catalog app
  const [allocateModal, setAllocateModal] = useState(null) // connection
  const [connectSaving, setConnectSaving] = useState(false)
  const [oauthStarting, setOauthStarting] = useState(false)
  const [connectForm] = Form.useForm()
  const [allocateForm] = Form.useForm()
  const [shopDomain, setShopDomain] = useState('')

  const embed = `<script src="${API}/embed.js" data-business="${user?.email || ''}"></script>`

  const loadKeys = () => {
    setKeysLoading(true)
    Promise.all([
      api('/keys').catch(() => ({ keys: [] })),
      api('/keys/providers').catch(() => []),
    ])
      .then(([k, p]) => {
        setKeys(k.keys || [])
        setProviders(Array.isArray(p) ? p : (p.providers || []))
      })
      .finally(() => setKeysLoading(false))
  }

  const loadApps = () => {
    setAppsLoading(true)
    Promise.all([
      api('/integrations/catalog').catch(() => ({ apps: [], categories: [] })),
      api('/integrations/connections').catch(() => ({ connections: [] })),
      api('/agents/').catch(() => []),
    ])
      .then(([cat, con, ag]) => {
        setCatalog(cat.apps || [])
        setCategories(cat.categories || [])
        setConnections(con.connections || [])
        setAgents(Array.isArray(ag) ? ag : [])
      })
      .finally(() => setAppsLoading(false))
  }

  useEffect(() => {
    api('/system/status')
      .then(setStatus)
      .catch(() => setStatus(null))
      .finally(() => setLoading(false))
    loadKeys()
    loadApps()
  }, [])

  // OAuth return toast
  useEffect(() => {
    const oauth = searchParams.get('oauth')
    if (!oauth) return
    if (oauth === 'success') {
      message.success('App connected via OAuth')
      setTab('apps')
      loadApps()
    } else if (oauth === 'error') {
      message.error(searchParams.get('message') || 'OAuth failed')
      setTab('apps')
    }
    const next = new URLSearchParams(searchParams)
    next.delete('oauth')
    next.delete('message')
    if (!next.get('tab')) next.set('tab', 'apps')
    setSearchParams(next, { replace: true })
  }, [])

  const onTabChange = (key) => {
    setTab(key)
    const next = new URLSearchParams(searchParams)
    next.set('tab', key)
    setSearchParams(next, { replace: true })
  }

  const saveProfile = async (values) => {
    setSaving(true)
    try {
      const body = { name: values.name }
      if (values.password) body.password = values.password
      const updated = await api('/auth/me', { method: 'PATCH', body })
      setAuth(getToken(), updated)
      setUser(updated)
      message.success('Profile updated')
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const openKeyModal = (row) => {
    const meta = providers.find((p) => p.id === row.provider) || {
      id: row.provider,
      label: row.provider_label,
      placeholder: 'Paste key',
      help: '',
    }
    setKeyModal({ ...meta, existing: row })
    keyForm.resetFields()
  }

  const saveKey = async (values) => {
    if (!keyModal) return
    setKeySaving(true)
    try {
      await api(`/keys/${keyModal.id}`, {
        method: 'PUT',
        body: {
          provider: keyModal.id,
          value: values.value,
          label: values.label || '',
        },
      })
      message.success(`${keyModal.label} saved (encrypted)`)
      setKeyModal(null)
      loadKeys()
    } catch (e) {
      message.error(e.message)
    } finally {
      setKeySaving(false)
    }
  }

  const deleteKey = async (provider) => {
    try {
      await api(`/keys/${provider}`, { method: 'DELETE' })
      message.success('Key removed')
      loadKeys()
    } catch (e) {
      message.error(e.message)
    }
  }

  const verifyKey = async (provider) => {
    try {
      const r = await api(`/keys/${provider}/verify`, { method: 'POST' })
      if (r.ok) message.success(`Key OK · ${r.masked || 'encrypted'}`)
      else message.warning(r.error || 'Key not usable')
    } catch (e) {
      message.error(e.message)
    }
  }

  const connectionByApp = useMemo(() => {
    const m = {}
    for (const c of connections) {
      // keep newest / preferred connected
      if (!m[c.app_id] || c.status === 'connected') m[c.app_id] = c
    }
    return m
  }, [connections])

  const filteredCatalog = useMemo(() => {
    if (categoryFilter === 'all') return catalog
    return catalog.filter((a) => a.category === categoryFilter)
  }, [catalog, categoryFilter])

  const openConnect = (app) => {
    setConnectModal(app)
    connectForm.resetFields()
    const existing = connectionByApp[app.id]
    if (existing?.agent_ids?.length) {
      connectForm.setFieldsValue({ agent_ids: existing.agent_ids })
    }
    setShopDomain(existing?.meta?.shop_domain || '')
  }

  const saveConnect = async (values) => {
    if (!connectModal) return
    setConnectSaving(true)
    try {
      const credentials = { ...values }
      delete credentials.agent_ids
      delete credentials.display_name
      const r = await api(`/integrations/${connectModal.id}/connect`, {
        method: 'POST',
        body: {
          credentials,
          display_name: values.display_name || connectModal.name,
          agent_ids: values.agent_ids || [],
          test: true,
        },
      })
      if (r.status === 'connected' || r.probe?.ok) {
        message.success(r.probe?.message || `${connectModal.name} connected`)
      } else if (r.status === 'error') {
        message.warning(r.probe?.message || r.last_error || 'Saved but test failed — check credentials')
      } else {
        message.success('Connection saved')
      }
      setConnectModal(null)
      loadApps()
    } catch (e) {
      message.error(e.message)
    } finally {
      setConnectSaving(false)
    }
  }

  const startOAuth = async (app) => {
    setOauthStarting(true)
    try {
      const body = {
        redirect_after: '/settings?tab=apps',
        shop_domain: app.id === 'shopify' ? shopDomain || connectForm.getFieldValue('shop_domain') : undefined,
      }
      if (app.id === 'shopify' && !body.shop_domain) {
        message.warning('Enter your shop domain first (e.g. my-store.myshopify.com)')
        setOauthStarting(false)
        return
      }
      const r = await api(`/integrations/${app.id}/oauth/start`, { method: 'POST', body })
      if (r.ok && r.authorize_url) {
        window.location.href = r.authorize_url
        return
      }
      message.info(r.message || 'OAuth not configured on server — use API credentials below')
    } catch (e) {
      message.error(e.message)
    } finally {
      setOauthStarting(false)
    }
  }

  const openAllocate = (conn) => {
    setAllocateModal(conn)
    allocateForm.setFieldsValue({
      agent_ids: conn.agent_ids || [],
      permission: 'full',
    })
  }

  const saveAllocate = async (values) => {
    if (!allocateModal) return
    setConnectSaving(true)
    try {
      const r = await api(`/integrations/connections/${allocateModal.id}/agents`, {
        method: 'PUT',
        body: {
          agent_ids: values.agent_ids || [],
          permission: values.permission || 'full',
        },
      })
      message.success(r.message || 'Agents updated')
      setAllocateModal(null)
      loadApps()
    } catch (e) {
      message.error(e.message)
    } finally {
      setConnectSaving(false)
    }
  }

  const testConn = async (conn) => {
    try {
      const r = await api(`/integrations/connections/${conn.id}/test`, { method: 'POST' })
      if (r.probe?.ok) message.success(r.probe.message || 'Connection OK')
      else message.warning(r.probe?.message || 'Test failed')
      loadApps()
    } catch (e) {
      message.error(e.message)
    }
  }

  const deleteConn = async (conn) => {
    try {
      await api(`/integrations/connections/${conn.id}`, { method: 'DELETE' })
      message.success('Disconnected')
      loadApps()
    } catch (e) {
      message.error(e.message)
    }
  }

  const { llm: llmKeys, channels: channelKeys, other: otherKeys } = partitionKeys(keys, providers)

  const renderKeyList = (rows) => (
    keysLoading ? <Spin /> : (
      <List
        dataSource={rows}
        locale={{ emptyText: 'No providers in this group' }}
        renderItem={(row) => (
          <List.Item
            actions={[
              (row.configured || row.id) && (
                <Button key="v" type="link" onClick={() => verifyKey(row.provider)}>Verify</Button>
              ),
              <Button key="set" type="link" icon={<KeyOutlined />} onClick={() => openKeyModal(row)}>
                {row.configured || row.id ? 'Update' : 'Add'}
              </Button>,
              (row.configured || row.id) && (
                <Popconfirm key="del" title="Delete this encrypted key?" onConfirm={() => deleteKey(row.provider)}>
                  <Button type="link" danger icon={<DeleteOutlined />}>Remove</Button>
                </Popconfirm>
              ),
            ].filter(Boolean)}
          >
            <List.Item.Meta
              title={
                <Space>
                  {row.provider_label || row.provider}
                  {(row.configured || row.id) ? (
                    <Tag color="success">Saved · {row.masked || `••••${row.hint}`}</Tag>
                  ) : (
                    <Tag>Not set</Tag>
                  )}
                </Space>
              }
              description={
                providers.find((p) => p.id === row.provider)?.help
                || 'Stored only for your subscriber account'
              }
            />
          </List.Item>
        )}
      />
    )
  )

  const profileTab = (
    <Card>
      <Form
        layout="vertical"
        style={{ maxWidth: 420 }}
        initialValues={{ name: user?.name || '', email: user?.email }}
        onFinish={saveProfile}
        key={user?.email}
      >
        <Form.Item name="email" label="Email">
          <Input disabled />
        </Form.Item>
        <Form.Item name="name" label="Display name">
          <Input placeholder="Your name" />
        </Form.Item>
        <Form.Item name="password" label="New password" extra="Leave blank to keep current password">
          <Input.Password placeholder="At least 6 characters" />
        </Form.Item>
        <Descriptions size="small" column={1} style={{ marginBottom: 12 }}>
          <Descriptions.Item label="Role">{user?.role}</Descriptions.Item>
          <Descriptions.Item label="Plan">{user?.plan}</Descriptions.Item>
        </Descriptions>
        <Button type="primary" htmlType="submit" loading={saving}>Save changes</Button>
      </Form>
    </Card>
  )

  const keysTab = (
    <div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="Bring your own LLM & channel keys"
        description={
          <>
            Keys are encrypted with AES (Fernet) before storage and never shown in full again.
            Your keys power <strong>your</strong> Claude/Grok calls when set; otherwise the platform falls back to its config or mock.
            For Shopify, Google Workspace, Slack, etc. use the <strong>Connected apps</strong> tab.
          </>
        }
      />
      {!keysLoading && (() => {
        const configured = (p) => keys.some((k) => k.provider === p && (k.configured || k.id || k.hint || k.masked))
        const hasAnthropic = configured('anthropic')
        const hasXai = configured('xai')
        if (!hasAnthropic && !hasXai) return null
        const parts = []
        if (hasAnthropic) parts.push('Claude')
        if (hasXai) parts.push('Grok')
        return (
          <Tag color="purple" style={{ marginBottom: 12 }}>
            Using your {parts.join('/')} keys for premium models
          </Tag>
        )
      })()}

      <Card
        title={<Space><LockOutlined /> LLM providers <Tag icon={<SafetyCertificateOutlined />} color="green">Encrypted</Tag></Space>}
        style={{ marginBottom: 16 }}
      >
        {renderKeyList(llmKeys.length ? llmKeys : keys.filter((k) => ['anthropic', 'xai', 'openai', 'google'].includes(k.provider)))}
      </Card>

      <Card title={<Space><ApiOutlined /> Channels (email / SMS)</Space>} style={{ marginBottom: 16 }}>
        {renderKeyList(channelKeys.length ? channelKeys : keys.filter((k) => String(k.provider).startsWith('twilio') || k.provider === 'resend'))}
      </Card>

      {otherKeys.length > 0 && (
        <Card title="Other keys" style={{ marginBottom: 16 }}>
          {renderKeyList(otherKeys)}
        </Card>
      )}
    </div>
  )

  const appsTab = (
    <div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="Connect business apps your agents can use"
        description={
          <>
            Connect Shopify, Google, Slack, HubSpot, and more with <strong>OAuth</strong> (when configured on the server)
            or <strong>API credentials</strong>. Then allocate agents so they receive that app context in chat and tasks.
          </>
        }
      />

      <Card
        title={
          <Space>
            <LinkOutlined />
            Your connections
            <Badge count={connections.filter((c) => c.status === 'connected').length} style={{ backgroundColor: '#52c41a' }} />
          </Space>
        }
        extra={
          <Button icon={<ReloadOutlined />} onClick={loadApps} size="small">Refresh</Button>
        }
        style={{ marginBottom: 16 }}
      >
        {appsLoading ? <Spin /> : connections.length === 0 ? (
          <Empty description="No apps connected yet — pick one below" />
        ) : (
          <List
            dataSource={connections}
            renderItem={(conn) => (
              <List.Item
                actions={[
                  <Button key="agents" type="link" icon={<RobotOutlined />} onClick={() => openAllocate(conn)}>
                    Agents ({conn.agent_count || 0})
                  </Button>,
                  <Button key="test" type="link" icon={<ExperimentOutlined />} onClick={() => testConn(conn)}>
                    Test
                  </Button>,
                  <Button
                    key="edit"
                    type="link"
                    onClick={() => {
                      const app = catalog.find((a) => a.id === conn.app_id)
                      if (app) openConnect(app)
                    }}
                  >
                    Update
                  </Button>,
                  <Popconfirm key="del" title="Disconnect this app?" onConfirm={() => deleteConn(conn)}>
                    <Button type="link" danger icon={<DeleteOutlined />}>Disconnect</Button>
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  avatar={
                    <div
                      style={{
                        width: 40,
                        height: 40,
                        borderRadius: 8,
                        background: conn.color || '#1677ff',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: '#fff',
                        fontWeight: 700,
                        fontSize: 14,
                      }}
                    >
                      {(conn.app_name || conn.app_id || '?').slice(0, 2).toUpperCase()}
                    </div>
                  }
                  title={
                    <Space wrap>
                      <Text strong>{conn.display_name || conn.app_name}</Text>
                      <Tag color={connStatusColor(conn.status)}>{conn.status}</Tag>
                      <Tag>{conn.auth_mode}</Tag>
                      {conn.meta?.shop_domain && <Tag>{conn.meta.shop_domain}</Tag>}
                      {conn.meta?.shop_name && <Tag color="green">{conn.meta.shop_name}</Tag>}
                    </Space>
                  }
                  description={
                    <div>
                      <div>
                        {conn.agents?.length
                          ? `Agents: ${conn.agents.map((a) => a.name).join(', ')}`
                          : 'No agents allocated yet'}
                      </div>
                      {conn.last_error && (
                        <Text type="danger" style={{ fontSize: 12 }}>{conn.last_error}</Text>
                      )}
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Card>

      <Card
        title={<Space><AppstoreOutlined /> Available apps</Space>}
        extra={
          <Select
            value={categoryFilter}
            onChange={setCategoryFilter}
            style={{ width: 160 }}
            options={[
              { value: 'all', label: 'All categories' },
              ...categories.map((c) => ({ value: c, label: c })),
            ]}
          />
        }
      >
        {appsLoading ? <Spin /> : (
          <Row gutter={[12, 12]}>
            {filteredCatalog.map((app) => {
              const conn = connectionByApp[app.id]
              const connected = conn?.status === 'connected'
              return (
                <Col xs={24} sm={12} lg={8} key={app.id}>
                  <Card
                    size="small"
                    hoverable
                    styles={{ body: { minHeight: 160 } }}
                    title={
                      <Space>
                        <span
                          style={{
                            display: 'inline-block',
                            width: 10,
                            height: 10,
                            borderRadius: '50%',
                            background: app.color || '#999',
                          }}
                        />
                        {app.name}
                      </Space>
                    }
                    extra={connected ? <Tag color="success">Connected</Tag> : <Tag>Available</Tag>}
                  >
                    <Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ minHeight: 44 }}>
                      {app.description}
                    </Paragraph>
                    <Space wrap size={[4, 4]} style={{ marginBottom: 8 }}>
                      {app.auth_modes?.map((m) => (
                        <Tag key={m}>{m === 'api_key' ? 'API key' : 'OAuth'}</Tag>
                      ))}
                      {app.supports_oauth && (
                        <Tag color={app.oauth_ready ? 'blue' : 'default'}>
                          OAuth {app.oauth_ready ? 'ready' : 'needs server keys'}
                        </Tag>
                      )}
                    </Space>
                    <Space wrap>
                      <Button type="primary" size="small" onClick={() => openConnect(app)}>
                        {connected ? 'Manage' : 'Connect'}
                      </Button>
                      {app.docs_url && (
                        <Button type="link" size="small" href={app.docs_url} target="_blank" rel="noreferrer">
                          Docs
                        </Button>
                      )}
                    </Space>
                  </Card>
                </Col>
              )
            })}
          </Row>
        )}
      </Card>
    </div>
  )

  const agentsTab = (
    <div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="Allocate apps to agents"
        description="Agents only see apps you assign. Open a connection to change the agent list, or manage per agent below."
      />
      {appsLoading ? <Spin /> : agents.length === 0 ? (
        <Empty description="Create agents first, then allocate apps" />
      ) : (
        <List
          dataSource={agents}
          renderItem={(agent) => {
            const linked = (agent.integrations || []).filter(Boolean)
            // Also derive from connections
            const fromConns = connections.filter((c) => (c.agent_ids || []).includes(agent.id))
            const apps = linked.length
              ? linked
              : fromConns.map((c) => ({
                connection_id: c.id,
                app_id: c.app_id,
                display_name: c.display_name,
                status: c.status,
              }))
            return (
              <Card size="small" style={{ marginBottom: 12 }} title={
                <Space>
                  <RobotOutlined />
                  {agent.name}
                  <Tag>{agent.template_type}</Tag>
                  <Tag color={agent.status === 'active' ? 'success' : 'default'}>{agent.status}</Tag>
                </Space>
              }>
                <Space wrap style={{ marginBottom: 8 }}>
                  {apps.length === 0 ? (
                    <Text type="secondary">No apps allocated</Text>
                  ) : apps.map((a) => (
                    <Tag key={a.connection_id || a.app_id} color={connStatusColor(a.status)}>
                      {a.display_name || a.app_id}
                    </Tag>
                  ))}
                </Space>
                <div>
                  <Select
                    mode="multiple"
                    allowClear
                    placeholder="Select connected apps for this agent"
                    style={{ width: '100%', maxWidth: 560 }}
                    value={fromConns.map((c) => c.id)}
                    options={connections.map((c) => ({
                      value: c.id,
                      label: `${c.display_name || c.app_name} (${c.status})`,
                    }))}
                    onChange={async (ids) => {
                      try {
                        await api(`/integrations/agents/${agent.id}`, {
                          method: 'PUT',
                          body: { connection_ids: ids, permission: 'full' },
                        })
                        message.success(`Updated apps for ${agent.name}`)
                        loadApps()
                      } catch (e) {
                        message.error(e.message)
                      }
                    }}
                  />
                </div>
              </Card>
            )
          }}
        />
      )}
    </div>
  )

  const platformTab = (
    <Card>
      <Paragraph type="secondary">
        Platform-level keys (server <Text code>.env</Text>). Your vault keys and Connected apps take priority when present.
      </Paragraph>
      {loading ? <Spin /> : status ? (
        <>
          <Space wrap style={{ marginBottom: 12 }}>
            <Tag color="blue">Environment: {status.environment}</Tag>
            <Tag color="blue">Database: {status.database?.driver}</Tag>
          </Space>
          <Divider orientation="left" plain>LLM (platform)</Divider>
          <Space wrap>
            <StatusTag ok={status.llm?.anthropic} label="Anthropic (Claude)" />
            <StatusTag ok={status.llm?.xai} label="xAI (Grok)" />
            <Tag>Ollama: {status.llm?.ollama_url}</Tag>
          </Space>
          <Divider orientation="left" plain>Billing</Divider>
          <Space wrap>
            <StatusTag ok={status.billing?.stripe} label="Stripe payments" />
          </Space>
          <Divider orientation="left" plain>Channels</Divider>
          <Space wrap>
            <StatusTag ok={status.channels?.email_resend} label="Email (Resend)" />
            <StatusTag ok={status.channels?.sms_twilio} label="SMS (Twilio)" />
          </Space>
          <Divider orientation="left" plain>OAuth apps (server)</Divider>
          <Space wrap>
            {status.oauth ? Object.entries(status.oauth).map(([k, v]) => (
              <StatusTag key={k} ok={v} label={k} />
            )) : (
              <Text type="secondary">No OAuth status</Text>
            )}
          </Space>
        </>
      ) : (
        <Alert type="error" message="Could not load system status" />
      )}

      <Divider />
      <Title level={5}>Website embed</Title>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="Paste this on your website to add your AI assistant (embed widget ships in a later build)."
      />
      <Paragraph copyable code>{embed}</Paragraph>
    </Card>
  )

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Title level={3} style={{ marginBottom: 4 }}>Settings</Title>
        <Text type="secondary">Profile, API keys, connected apps, and agent access</Text>
      </div>

      <Tabs
        activeKey={tab}
        onChange={onTabChange}
        items={[
          { key: 'profile', label: <span><UserOutlined /> Profile</span>, children: profileTab },
          { key: 'keys', label: <span><KeyOutlined /> API keys</span>, children: keysTab },
          {
            key: 'apps',
            label: (
              <span>
                <AppstoreOutlined /> Connected apps{' '}
                <Badge
                  count={connections.filter((c) => c.status === 'connected').length}
                  size="small"
                  offset={[4, -2]}
                />
              </span>
            ),
            children: appsTab,
          },
          { key: 'agents', label: <span><RobotOutlined /> Agent apps</span>, children: agentsTab },
          { key: 'platform', label: <span><CloudOutlined /> Platform</span>, children: platformTab },
        ]}
      />

      {/* API key modal */}
      <Modal
        title={
          <Space>
            <LockOutlined />
            {keyModal ? `${keyModal.existing?.id ? 'Update' : 'Add'} · ${keyModal.label}` : 'API key'}
          </Space>
        }
        open={!!keyModal}
        onCancel={() => setKeyModal(null)}
        footer={null}
        destroyOnClose
      >
        {keyModal && (
          <>
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message="Encrypted on save"
              description="We store only ciphertext. After you save, the full key cannot be retrieved — only a masked hint."
            />
            <Paragraph type="secondary">{keyModal.help}</Paragraph>
            {keyModal.existing?.hint && (
              <Tag color="blue" style={{ marginBottom: 12 }}>
                Current: {keyModal.existing.masked || `••••${keyModal.existing.hint}`}
              </Tag>
            )}
            <Form form={keyForm} layout="vertical" onFinish={saveKey}>
              <Form.Item name="label" label="Label (optional)">
                <Input placeholder="e.g. Production Anthropic" />
              </Form.Item>
              <Form.Item
                name="value"
                label="API key"
                rules={[{ required: true, min: 4, message: 'Paste your API key' }]}
              >
                <Input.Password
                  placeholder={keyModal.placeholder || 'Paste secret key'}
                  autoComplete="new-password"
                />
              </Form.Item>
              <Button type="primary" htmlType="submit" block loading={keySaving} icon={<LockOutlined />}>
                Encrypt & save
              </Button>
            </Form>
          </>
        )}
      </Modal>

      {/* Connect app modal */}
      <Modal
        title={connectModal ? `Connect ${connectModal.name}` : 'Connect app'}
        open={!!connectModal}
        onCancel={() => setConnectModal(null)}
        footer={null}
        width={560}
        destroyOnClose
      >
        {connectModal && (
          <>
            <Paragraph type="secondary">{connectModal.description}</Paragraph>
            {connectModal.agent_capabilities?.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <Text strong>What agents can do: </Text>
                <Space wrap size={[4, 4]}>
                  {connectModal.agent_capabilities.map((c) => (
                    <Tag key={c}>{c}</Tag>
                  ))}
                </Space>
              </div>
            )}

            {connectModal.supports_oauth && (
              <Card size="small" style={{ marginBottom: 16 }} title="OAuth">
                {connectModal.oauth_needs_shop && (
                  <Form.Item label="Shop domain" style={{ marginBottom: 8 }}>
                    <Input
                      placeholder="your-store.myshopify.com"
                      value={shopDomain}
                      onChange={(e) => setShopDomain(e.target.value)}
                    />
                  </Form.Item>
                )}
                <Button
                  type="primary"
                  block
                  loading={oauthStarting}
                  disabled={connectModal.oauth_ready === false}
                  onClick={() => startOAuth(connectModal)}
                  icon={<LinkOutlined />}
                >
                  {connectModal.oauth_ready
                    ? `Continue with ${connectModal.name} OAuth`
                    : 'OAuth not configured on server'}
                </Button>
                {!connectModal.oauth_ready && (
                  <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}>
                    Set server env vars (e.g. GOOGLE_OAUTH_CLIENT_ID / SHOPIFY_CLIENT_ID) to enable one-click OAuth.
                    You can still connect with API credentials below.
                  </Paragraph>
                )}
              </Card>
            )}

            {(connectModal.auth_modes || []).includes('api_key') && (
              <>
                <Divider plain>Or use API credentials</Divider>
                <Form form={connectForm} layout="vertical" onFinish={saveConnect}>
                  <Form.Item name="display_name" label="Display name">
                    <Input placeholder={connectModal.name} />
                  </Form.Item>
                  {(connectModal.fields || []).map((f) => (
                    <Form.Item
                      key={f.name}
                      name={f.name}
                      label={f.label}
                      rules={f.required ? [{ required: true, message: `Required: ${f.label}` }] : []}
                    >
                      {f.secret ? (
                        <Input.Password placeholder={f.placeholder} autoComplete="new-password" />
                      ) : (
                        <Input placeholder={f.placeholder} />
                      )}
                    </Form.Item>
                  ))}
                  <Form.Item
                    name="agent_ids"
                    label="Allocate to agents"
                    extra="These agents will receive this app in their context"
                  >
                    <Select
                      mode="multiple"
                      allowClear
                      placeholder="Select agents"
                      options={agents.map((a) => ({ value: a.id, label: `${a.name} (${a.template_type})` }))}
                    />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block loading={connectSaving} icon={<LockOutlined />}>
                    Encrypt, test & connect
                  </Button>
                </Form>
              </>
            )}

            {!(connectModal.auth_modes || []).includes('api_key') && connectModal.supports_oauth && (
              <Paragraph type="secondary">
                This app is OAuth-only. If OAuth is not ready, paste tokens under Platform docs or enable OAuth client IDs.
              </Paragraph>
            )}

            {/* OAuth-only apps still allow manual token paste via fields if any */}
            {!(connectModal.auth_modes || []).includes('api_key') && (connectModal.fields || []).length > 0 && (
              <>
                <Divider plain>Manual tokens (advanced)</Divider>
                <Form form={connectForm} layout="vertical" onFinish={saveConnect}>
                  {(connectModal.fields || []).map((f) => (
                    <Form.Item key={f.name} name={f.name} label={f.label}>
                      {f.secret ? (
                        <Input.Password placeholder={f.placeholder} />
                      ) : (
                        <Input placeholder={f.placeholder} />
                      )}
                    </Form.Item>
                  ))}
                  <Form.Item name="agent_ids" label="Allocate to agents">
                    <Select
                      mode="multiple"
                      allowClear
                      options={agents.map((a) => ({ value: a.id, label: a.name }))}
                    />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block loading={connectSaving}>
                    Save tokens
                  </Button>
                </Form>
              </>
            )}
          </>
        )}
      </Modal>

      {/* Allocate agents modal */}
      <Modal
        title={allocateModal ? `Agents · ${allocateModal.display_name || allocateModal.app_name}` : 'Agents'}
        open={!!allocateModal}
        onCancel={() => setAllocateModal(null)}
        footer={null}
        destroyOnClose
      >
        {allocateModal && (
          <Form form={allocateForm} layout="vertical" onFinish={saveAllocate}>
            <Form.Item
              name="agent_ids"
              label="Agents with access"
              extra="Allocated agents see this app in chat and task prompts"
            >
              <Select
                mode="multiple"
                allowClear
                placeholder="Select agents"
                options={agents.map((a) => ({
                  value: a.id,
                  label: `${a.name} (${a.template_type})`,
                }))}
              />
            </Form.Item>
            <Form.Item name="permission" label="Permission" initialValue="full">
              <Select
                options={[
                  { value: 'read', label: 'Read' },
                  { value: 'write', label: 'Write' },
                  { value: 'full', label: 'Full' },
                ]}
              />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={connectSaving} icon={<RobotOutlined />}>
              Save agent allocation
            </Button>
          </Form>
        )}
      </Modal>
    </div>
  )
}
