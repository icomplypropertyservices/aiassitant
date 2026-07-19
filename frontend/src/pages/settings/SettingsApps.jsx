import React, { useEffect, useMemo, useState } from 'react'
import {
  Card, Typography, Alert, Form, Input, Button, Tag, Space, message,
  Spin, List, Popconfirm, Modal, Select, Badge, Row, Col, Empty,
} from 'antd'
import {
  DeleteOutlined, RobotOutlined, LinkOutlined, ReloadOutlined,
  ExperimentOutlined, AppstoreOutlined,
} from '@ant-design/icons'
import { api } from '../../api'
import { connStatusColor } from './helpers'

const { Text, Paragraph } = Typography

export default function SettingsApps({ onConnectedCountChange }) {
  const [catalog, setCatalog] = useState([])
  const [oneClickApps, setOneClickApps] = useState([])
  const [googleOauthOk, setGoogleOauthOk] = useState(null)
  const [categories, setCategories] = useState([])
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [connections, setConnections] = useState([])
  const [appsLoading, setAppsLoading] = useState(true)
  const [agents, setAgents] = useState([])
  const [connectModal, setConnectModal] = useState(null)
  const [allocateModal, setAllocateModal] = useState(null)
  const [connectSaving, setConnectSaving] = useState(false)
  const [oauthStarting, setOauthStarting] = useState(false)
  const [connectForm] = Form.useForm()
  const [allocateForm] = Form.useForm()
  const [shopDomain, setShopDomain] = useState('')

  const loadApps = () => {
    setAppsLoading(true)
    Promise.all([
      api('/integrations/catalog').catch(() => ({ apps: [], categories: [], one_click_oauth: [] })),
      api('/integrations/connections').catch(() => ({ connections: [] })),
      api('/agents/').catch(() => []),
      api('/integrations/oauth/google-status').catch(() => null),
    ])
      .then(([cat, con, ag, gstat]) => {
        setCatalog(cat.apps || [])
        setOneClickApps(cat.one_click_oauth || (cat.apps || []).filter((a) => a.one_click_oauth))
        setCategories(cat.categories || [])
        setConnections(con.connections || [])
        setAgents(Array.isArray(ag) ? ag : [])
        setGoogleOauthOk(gstat)
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
        if (r.redirect_uri) {
          try {
            sessionStorage.setItem('last_oauth_redirect_uri', r.redirect_uri)
          } catch { /* ignore */ }
        }
        const url = r.authorize_url

        const isNative = !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform())

        if (isNative) {
          try {
            window.open(url, '_system')
          } catch {
            window.open(url, '_blank')
          }
          message.info('Finish Google login in the browser, then return here.')
        } else {
          window.location.href = url
        }
        return
      }
      if (r.redirect_uri) {
        message.warning(
          `${r.message || 'OAuth not ready'}. Redirect URI to whitelist: ${r.redirect_uri}`,
          10,
        )
      } else {
        message.info(r.message || 'OAuth not configured on server — use API credentials below')
      }
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

  return (
    <>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Card
          title={<Space><LinkOutlined /> OAuth & connections guide</Space>}
          className="aba-soft-card"
          type="inner"
        >
          <Alert
            type={googleOauthOk?.ok ? 'success' : 'warning'}
            showIcon
            style={{ marginBottom: 16 }}
            message={googleOauthOk?.ok ? 'Google 1-click OAuth is configured' : 'Google OAuth client not fully configured'}
            description={
              googleOauthOk?.ok ? (
                <div>
                  <p style={{ marginBottom: 8 }}>
                    Connect Google Workspace, Gmail, Sheets, Business Profile, and YouTube with one click.
                  </p>
                  <p style={{ marginBottom: 4 }}>
                    <strong>Authorized redirect URI</strong> (must match Google Cloud Console <em>exactly</em>):
                  </p>
                  <Text code copyable style={{ display: 'block', marginBottom: 8, wordBreak: 'break-all' }}>
                    {googleOauthOk.redirect_uri}
                  </Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    If Google shows “request is invalid”, the redirect URI above is missing or mistyped in
                    Console → Credentials → OAuth 2.0 Client (Web) → Authorized redirect URIs.
                  </Text>
                </div>
              ) : (
                <div>
                  <p>
                    Set <Text code>GOOGLE_OAUTH_CLIENT_ID</Text>, <Text code>GOOGLE_OAUTH_CLIENT_SECRET</Text>,
                    and <Text code>API_PUBLIC_URL</Text> (or <Text code>OAUTH_REDIRECT_URI</Text>) in production env.
                  </p>
                  {googleOauthOk?.redirect_uri && (
                    <>
                      <p style={{ marginBottom: 4 }}><strong>Redirect URI to add:</strong></p>
                      <Text code copyable style={{ display: 'block', wordBreak: 'break-all' }}>
                        {googleOauthOk.redirect_uri}
                      </Text>
                    </>
                  )}
                  {Array.isArray(googleOauthOk?.console_steps) && googleOauthOk.console_steps.length > 0 && (
                    <ol style={{ margin: '8px 0 0', paddingLeft: 18, fontSize: 12 }}>
                      {googleOauthOk.console_steps.map((s) => (
                        <li key={s}>{s}</li>
                      ))}
                    </ol>
                  )}
                </div>
              )
            }
          />
          <Alert
            type="info"
            showIcon
            message="Connections"
            description={
              <>
                <strong>Live 1-click:</strong> Google Workspace, Gmail, Sheets, Business Profile, YouTube.{' '}
                Other apps: use API keys when available, or Coming soon until OAuth env is set.
              </>
            }
          />
        </Card>

        <Card
          title={
            <Space>
              <LinkOutlined />
              Your connections
              <Badge count={connectedCount} style={{ backgroundColor: '#52c41a' }} />
            </Space>
          }
          className="aba-soft-card"
          type="inner"
          extra={
            <Button icon={<ReloadOutlined />} onClick={loadApps} size="small">Refresh</Button>
          }
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
          title={<Space><LinkOutlined /> 1-click OAuth (Google)</Space>}
          className="aba-soft-card"
          type="inner"
          extra={
            <Tag color={googleOauthOk?.ok ? 'success' : 'warning'}>
              {googleOauthOk?.ok ? 'Server ready' : 'Needs env keys'}
            </Tag>
          }
        >
          {appsLoading ? <Spin /> : (
            <List
              dataSource={oneClickApps.length ? oneClickApps : catalog.filter((a) => a.one_click_oauth)}
              locale={{ emptyText: 'No Google apps in catalog' }}
              renderItem={(app, idx) => {
                const conn = connectionByApp[app.id]
                const connected = conn?.status === 'connected'
                return (
                  <List.Item
                    actions={[
                      connected ? (
                        <Button key="m" size="small" onClick={() => openConnect(app)}>Manage</Button>
                      ) : (
                        <Button
                          key="c"
                          type="primary"
                          size="small"
                          icon={<LinkOutlined />}
                          disabled={!app.oauth_ready}
                          onClick={() => startOAuth(app)}
                        >
                          Connect with Google
                        </Button>
                      ),
                    ]}
                  >
                    <List.Item.Meta
                      avatar={
                        <div style={{
                          width: 40, height: 40, borderRadius: 8, background: app.color || '#4285F4',
                          color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700,
                        }}
                        >
                          {idx + 1}
                        </div>
                      }
                      title={
                        <Space wrap>
                          <Text strong>{app.name}</Text>
                          {connected && <Tag color="success">Connected</Tag>}
                          <Tag color="blue">1-click OAuth</Tag>
                        </Space>
                      }
                      description={app.description}
                    />
                  </List.Item>
                )
              }}
            />
          )}
        </Card>

        <Card
          title={<Space><AppstoreOutlined /> All apps</Space>}
          className="aba-soft-card"
          type="inner"
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
                const soon = !!app.coming_soon
                return (
                  <Col xs={24} sm={12} lg={8} key={app.id}>
                    <Card
                      size="small"
                      hoverable={!soon}
                      styles={{ body: { minHeight: 160, opacity: soon && !connected ? 0.85 : 1 } }}
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
                      extra={
                        connected
                          ? <Tag color="success">Connected</Tag>
                          : soon
                            ? <Tag color="default">Coming soon</Tag>
                            : <Tag color="blue">Live</Tag>
                      }
                    >
                      <Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ minHeight: 44 }}>
                        {app.description}
                      </Paragraph>
                      <Space wrap size={[4, 4]} style={{ marginBottom: 8 }}>
                        {soon ? (
                          <Tag>Coming soon</Tag>
                        ) : (
                          <>
                            {app.one_click_oauth && <Tag color="blue">1-click OAuth</Tag>}
                            {app.supports_oauth && (
                              <Tag color={app.oauth_ready ? 'processing' : 'default'}>
                                OAuth {app.oauth_ready ? 'ready' : 'needs keys'}
                              </Tag>
                            )}
                          </>
                        )}
                      </Space>
                      <Space wrap>
                        {soon && !connected ? (
                          <Button type="default" size="small" disabled>
                            Coming soon
                          </Button>
                        ) : app.supports_oauth && app.oauth_ready ? (
                          <Button
                            type="primary"
                            size="small"
                            onClick={() => startOAuth(app)}
                            icon={<LinkOutlined />}
                          >
                            Connect with Google
                          </Button>
                        ) : (
                          <Button type="primary" size="small" onClick={() => openConnect(app)} disabled={soon}>
                            {connected ? 'Manage' : 'Connect'}
                          </Button>
                        )}
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
      </Space>

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
            {Array.isArray(connectModal.agent_capabilities) && connectModal.agent_capabilities.length > 0 && (
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
              <div style={{ marginBottom: 16 }}>
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
                  size="large"
                  block
                  loading={oauthStarting}
                  disabled={connectModal.oauth_ready === false}
                  onClick={() => startOAuth(connectModal)}
                  icon={<LinkOutlined />}
                  style={{ height: 52, fontSize: 17, fontWeight: 600 }}
                >
                  {connectModal.oauth_ready
                    ? `Connect with ${connectModal.id.includes('google') || connectModal.id.includes('gmail') || connectModal.id.includes('youtube') || connectModal.id.includes('google_business') || connectModal.id.includes('google_sheets') ? 'Google' :
                       connectModal.id === 'meta' ? 'Facebook' :
                       connectModal.id === 'instagram' ? 'Instagram' :
                       connectModal.id === 'linkedin' ? 'LinkedIn' :
                       connectModal.id === 'slack' ? 'Slack' :
                       connectModal.id === 'microsoft' ? 'Microsoft' :
                       connectModal.name}`
                    : 'OAuth not configured on server'}
                </Button>
                <div style={{ textAlign: 'center', marginTop: 6, marginBottom: 4 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    Uses your existing login • works in browser and on mobile (no passwords or tokens to paste)
                  </Text>
                </div>
                {!connectModal.oauth_ready && (
                  <Paragraph type="secondary" style={{ marginTop: 4, fontSize: 12 }}>
                    Server needs OAuth client keys (Platform tab or Vercel env).
                  </Paragraph>
                )}

                {(connectModal.auth_modes || []).includes('api_key') && (
                  <details style={{ marginTop: 10 }}>
                    <summary style={{ cursor: 'pointer', color: '#666', fontSize: 13 }}>
                      Advanced: Connect with API keys / manual tokens
                    </summary>
                    <div style={{ marginTop: 12, paddingLeft: 4 }}>
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
                        <Button type="default" htmlType="submit" block loading={connectSaving}>
                          Save API credentials
                        </Button>
                      </Form>
                    </div>
                  </details>
                )}
              </div>
            )}

            {!(connectModal.auth_modes || []).includes('api_key') && (connectModal.fields || []).length > 0 && (
              <details style={{ marginTop: 8 }}>
                <summary style={{ cursor: 'pointer', color: '#666', fontSize: 13 }}>
                  Advanced: Paste tokens manually
                </summary>
                <div style={{ marginTop: 10, paddingLeft: 4 }}>
                  <Form form={connectForm} layout="vertical" onFinish={saveConnect}>
                    {(connectModal.fields || []).map((f) => (
                      <Form.Item key={f.name} name={f.name} label={f.label}>
                        {f.secret ? <Input.Password placeholder={f.placeholder} /> : <Input placeholder={f.placeholder} />}
                      </Form.Item>
                    ))}
                    <Form.Item name="agent_ids" label="Allocate to agents">
                      <Select mode="multiple" allowClear options={agents.map((a) => ({ value: a.id, label: a.name }))} />
                    </Form.Item>
                    <Button type="default" htmlType="submit" block loading={connectSaving}>
                      Save tokens manually
                    </Button>
                  </Form>
                </div>
              </details>
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
    </>
  )
}
