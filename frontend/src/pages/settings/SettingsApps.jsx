import React, { useEffect, useMemo, useState } from 'react'
import {
  Card, Typography, Alert, Form, Input, Button, Tag, Space, message,
  Spin, List, Popconfirm, Modal, Select, Empty,
} from 'antd'
import {
  DeleteOutlined, RobotOutlined, LinkOutlined, ReloadOutlined,
  GoogleOutlined, CheckCircleOutlined,
} from '@ant-design/icons'
import { api } from '../../api'
import { connStatusColor } from './helpers'

const { Text, Paragraph } = Typography

const GOOGLE_IDS = new Set([
  'google', 'gmail', 'google_sheets', 'google_business', 'youtube',
])

function providerLabel(app) {
  const id = app?.id || ''
  if (GOOGLE_IDS.has(id) || id.includes('google') || id.includes('gmail') || id.includes('youtube')) {
    return 'Google'
  }
  if (id === 'meta') return 'Facebook'
  if (id === 'instagram') return 'Instagram'
  if (id === 'linkedin') return 'LinkedIn'
  if (id === 'slack') return 'Slack'
  if (id === 'microsoft') return 'Microsoft'
  if (id === 'shopify') return 'Shopify'
  return app?.name || 'OAuth'
}

export default function SettingsApps({ onConnectedCountChange }) {
  const [catalog, setCatalog] = useState([])
  const [googleOauthOk, setGoogleOauthOk] = useState(null)
  const [connections, setConnections] = useState([])
  const [appsLoading, setAppsLoading] = useState(true)
  const [agents, setAgents] = useState([])
  const [connectModal, setConnectModal] = useState(null)
  const [allocateModal, setAllocateModal] = useState(null)
  const [connectSaving, setConnectSaving] = useState(false)
  const [oauthStarting, setOauthStarting] = useState(null)
  const [connectForm] = Form.useForm()
  const [allocateForm] = Form.useForm()
  const [shopDomain, setShopDomain] = useState('')

  const loadApps = () => {
    setAppsLoading(true)
    Promise.all([
      api('/integrations/catalog').catch(() => ({ apps: [] })),
      api('/integrations/connections').catch(() => ({ connections: [] })),
      api('/agents/').catch(() => []),
      api('/integrations/oauth/google-status').catch(() => null),
    ])
      .then(([cat, con, ag, gstat]) => {
        const apps = Array.isArray(cat?.apps) ? cat.apps : (Array.isArray(cat) ? cat : [])
        const conns = Array.isArray(con?.connections)
          ? con.connections
          : (Array.isArray(con) ? con : [])
        let agentList = []
        if (Array.isArray(ag)) agentList = ag
        else if (Array.isArray(ag?.agents)) agentList = ag.agents
        else if (Array.isArray(ag?.items)) agentList = ag.items
        setCatalog(apps.filter((a) => a && a.id))
        setConnections(conns.filter((c) => c && c.id != null))
        setAgents(agentList.filter((a) => a && a.id != null))
        setGoogleOauthOk(gstat && typeof gstat === 'object' ? gstat : null)
      })
      .catch(() => {
        setCatalog([])
        setConnections([])
        setAgents([])
      })
      .finally(() => setAppsLoading(false))
  }

  useEffect(() => {
    loadApps()
  }, [])

  const connectedCount = connections.filter((c) => c.status === 'connected').length

  useEffect(() => {
    onConnectedCountChange?.(connectedCount)
  }, [connectedCount, onConnectedCountChange])

  const connectionByApp = useMemo(() => {
    const m = {}
    for (const c of connections) {
      if (!m[c.app_id] || c.status === 'connected') m[c.app_id] = c
    }
    return m
  }, [connections])

  /** Live apps first, then coming soon. Connected apps float to top. */
  const appRows = useMemo(() => {
    try {
      const rows = (Array.isArray(catalog) ? catalog : [])
        .filter((app) => app && app.id)
        .map((app) => {
          const conn = connectionByApp[app.id]
          return { app, conn, connected: conn?.status === 'connected' }
        })
      rows.sort((a, b) => {
        if (a.connected !== b.connected) return a.connected ? -1 : 1
        if (!!a.app.coming_soon !== !!b.app.coming_soon) return a.app.coming_soon ? 1 : -1
        return String(a.app.name || '').localeCompare(String(b.app.name || ''))
      })
      return rows
    } catch {
      return []
    }
  }, [catalog, connectionByApp])

  const redirectUri = googleOauthOk?.redirect_uri
    || 'https://www.aibusinessagent.xyz/api/integrations/oauth/callback'

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
        message.warning(r.probe?.message || r.last_error || 'Saved but test failed')
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
    setOauthStarting(app.id)
    try {
      const body = {
        redirect_after: '/settings?tab=apps',
        shop_domain: app.id === 'shopify' ? shopDomain || connectForm.getFieldValue('shop_domain') : undefined,
      }
      if (app.id === 'shopify' && !body.shop_domain) {
        message.warning('Enter your shop domain first (e.g. my-store.myshopify.com)')
        setOauthStarting(null)
        return
      }
      const r = await api(`/integrations/${app.id}/oauth/start`, { method: 'POST', body })
      if (r.ok && r.authorize_url) {
        if (r.redirect_uri) {
          try {
            sessionStorage.setItem('last_oauth_redirect_uri', r.redirect_uri)
          } catch { /* ignore */ }
        }
        const url = r.authorize_url
        const isNative = !!(window.Capacitor?.isNativePlatform?.())
        if (isNative) {
          try {
            const { Browser } = await import('@capacitor/browser')
            await Browser.open({ url, presentationStyle: 'popover' })
            message.info('Complete sign-in, then return here and tap Refresh.')
          } catch {
            window.open(url, '_blank')
          }
        } else {
          window.location.href = url
        }
        return
      }
      if (r.redirect_uri) {
        message.warning(
          `Add this Redirect URI in Google Cloud Console → Credentials → Web client:\n${r.redirect_uri}`,
          14,
        )
      } else {
        message.info(r.message || 'OAuth not configured — use API keys')
      }
    } catch (e) {
      const msg = e?.message || String(e)
      if (/redirect_uri|invalid_request|mismatch/i.test(msg)) {
        message.error(
          `redirect_uri_mismatch — Google Console must include exactly:\n${redirectUri}`,
          14,
        )
      } else {
        message.error(msg)
      }
    } finally {
      setOauthStarting(null)
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

  const deleteConn = async (conn) => {
    try {
      await api(`/integrations/connections/${conn.id}`, { method: 'DELETE' })
      message.success('Disconnected')
      loadApps()
    } catch (e) {
      message.error(e.message)
    }
  }

  const primaryAction = (app, conn, connected) => {
    const soon = !!app.coming_soon
    if (connected) {
      return (
        <Space size={4} wrap>
          <Button size="small" icon={<RobotOutlined />} onClick={() => openAllocate(conn)}>
            Agents
          </Button>
          <Button size="small" onClick={() => openConnect(app)}>
            Manage
          </Button>
          <Popconfirm title="Disconnect this app?" onConfirm={() => deleteConn(conn)}>
            <Button size="small" danger icon={<DeleteOutlined />}>
              Disconnect
            </Button>
          </Popconfirm>
        </Space>
      )
    }
    if (soon) {
      return (
        <Button size="small" disabled>
          Coming soon
        </Button>
      )
    }
    if (app.supports_oauth && app.oauth_ready) {
      return (
        <Button
          type="primary"
          size="middle"
          icon={GOOGLE_IDS.has(app.id) ? <GoogleOutlined /> : <LinkOutlined />}
          loading={oauthStarting === app.id}
          onClick={() => startOAuth(app)}
        >
          Connect{GOOGLE_IDS.has(app.id) ? ' with Google' : ''}
        </Button>
      )
    }
    return (
      <Button type="primary" size="middle" onClick={() => openConnect(app)}>
        Connect
      </Button>
    )
  }

  return (
    <>
      <Card
        className="aba-soft-card aba-settings-apps"
        title={
          <Space>
            <LinkOutlined />
            <span>Apps</span>
            {connectedCount > 0 && (
              <Tag color="success" icon={<CheckCircleOutlined />}>
                {connectedCount} connected
              </Tag>
            )}
          </Space>
        }
        extra={
          <Button icon={<ReloadOutlined />} onClick={loadApps} size="small" loading={appsLoading}>
            Refresh
          </Button>
        }
      >
        {googleOauthOk && !googleOauthOk.ok && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message="Google sign-in needs one setup step"
            description={
              <div>
                <Paragraph style={{ marginBottom: 8 }}>
                  In Google Cloud Console → Credentials → your <strong>Web</strong> OAuth client,
                  add this exact Authorized redirect URI (copy-paste, no trailing slash):
                </Paragraph>
                <Text code copyable style={{ display: 'block', wordBreak: 'break-all', marginBottom: 8 }}>
                  {redirectUri}
                </Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  Also add JavaScript origins: https://www.aibusinessagent.xyz
                </Text>
              </div>
            }
          />
        )}

        {appsLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : appRows.length === 0 ? (
          <Empty description="No apps available" />
        ) : (
          <List
            itemLayout="horizontal"
            dataSource={appRows}
            className="aba-apps-list"
            renderItem={({ app, conn, connected }) => (
              <List.Item
                className="aba-apps-list__item"
                actions={[primaryAction(app, conn, connected)]}
              >
                <List.Item.Meta
                  avatar={
                    <div
                      className="aba-apps-list__avatar"
                      style={{ background: app.color || '#1677ff' }}
                    >
                      {(app.name || '?').slice(0, 2).toUpperCase()}
                    </div>
                  }
                  title={
                    <Space wrap size={[6, 4]}>
                      <Text strong>{app.name}</Text>
                      {connected && (
                        <Tag color={connStatusColor(conn.status)}>{conn.status}</Tag>
                      )}
                      {app.coming_soon && !connected && <Tag>Coming soon</Tag>}
                    </Space>
                  }
                  description={
                    <Text type="secondary" ellipsis style={{ maxWidth: '100%', display: 'block' }}>
                      {app.description}
                      {connected && conn?.agents?.length
                        ? ` · Agents: ${conn.agents.map((a) => a.name).join(', ')}`
                        : ''}
                    </Text>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Card>

      <Modal
        title={connectModal ? `Connect ${connectModal.name}` : 'Connect app'}
        open={!!connectModal}
        onCancel={() => setConnectModal(null)}
        footer={null}
        width={480}
        destroyOnClose
      >
        {connectModal && (
          <>
            <Paragraph type="secondary" style={{ marginBottom: 16 }}>
              {connectModal.description}
            </Paragraph>

            {connectModal.supports_oauth && (
              <div style={{ marginBottom: 16 }}>
                {connectModal.oauth_needs_shop && (
                  <Form.Item label="Shop domain" style={{ marginBottom: 12 }}>
                    <Input
                      placeholder="your-store.myshopify.com"
                      value={shopDomain}
                      onChange={(e) => setShopDomain(e.target.value)}
                    />
                  </Form.Item>
                )}
                <Button
                  type="primary"
                  size="large"
                  block
                  loading={oauthStarting === connectModal.id}
                  disabled={connectModal.oauth_ready === false}
                  onClick={() => startOAuth(connectModal)}
                  icon={GOOGLE_IDS.has(connectModal.id) ? <GoogleOutlined /> : <LinkOutlined />}
                  style={{ height: 48, fontWeight: 600 }}
                >
                  {connectModal.oauth_ready
                    ? `Connect with ${providerLabel(connectModal)}`
                    : 'OAuth not ready on server'}
                </Button>
              </div>
            )}

            {(connectModal.auth_modes || []).includes('api_key') && (connectModal.fields || []).length > 0 && (
              <details style={{ marginTop: 8 }}>
                <summary style={{ cursor: 'pointer', color: '#666', fontSize: 13 }}>
                  Or connect with API keys
                </summary>
                <Form
                  form={connectForm}
                  layout="vertical"
                  onFinish={saveConnect}
                  style={{ marginTop: 12 }}
                >
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
                  <Form.Item name="agent_ids" label="Allocate to agents">
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
                  <Button type="default" htmlType="submit" block loading={connectSaving}>
                    Save credentials
                  </Button>
                </Form>
              </details>
            )}

            {!connectModal.supports_oauth && (connectModal.fields || []).length > 0 && (
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
                  Save
                </Button>
              </Form>
            )}
          </>
        )}
      </Modal>

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
              extra="These agents can use this app in chat and tasks"
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
              Save
            </Button>
          </Form>
        )}
      </Modal>
    </>
  )
}
