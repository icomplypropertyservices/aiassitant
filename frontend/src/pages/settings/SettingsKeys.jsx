import React, { useEffect, useState } from 'react'
import {
  Card, Typography, Alert, Form, Input, Button, Tag, Space, message,
  Spin, Divider, List, Popconfirm, Modal, Row, Col, Switch,
} from 'antd'
import {
  CheckCircleOutlined, LockOutlined, KeyOutlined, DeleteOutlined,
  SafetyCertificateOutlined, ApiOutlined, MailOutlined,
} from '@ant-design/icons'
import { getUser, api } from '../../api'
import { partitionKeys } from './helpers'

const { Text, Paragraph } = Typography

export default function SettingsKeys() {
  const user = getUser()
  const [keys, setKeys] = useState([])
  const [keysLoading, setKeysLoading] = useState(true)
  const [providers, setProviders] = useState([])
  const [keyModal, setKeyModal] = useState(null)
  const [keySaving, setKeySaving] = useState(false)
  const [keyForm] = Form.useForm()
  const [emailStatus, setEmailStatus] = useState(null)
  const [smtpSaving, setSmtpSaving] = useState(false)
  const [smtpForm] = Form.useForm()
  const [smtpPreset, setSmtpPreset] = useState('namecheap')

  const loadKeys = () => {
    setKeysLoading(true)
    Promise.all([
      api('/keys').catch(() => ({ keys: [] })),
      api('/keys/providers').catch(() => []),
      api('/keys/email/status').catch(() => null),
    ])
      .then(([k, p, em]) => {
        setKeys(k.keys || [])
        setProviders(Array.isArray(p) ? p : (p.providers || []))
        if (em) {
          setEmailStatus(em)
          const f = em.form || {}
          smtpForm.setFieldsValue({
            smtp_host: f.smtp_host || 'mail.privateemail.com',
            smtp_port: f.smtp_port || '587',
            smtp_user: f.smtp_user || '',
            smtp_from: f.smtp_from || '',
            smtp_tls: f.smtp_tls !== false,
            smtp_password: '',
            test_to: user?.email || '',
          })
        }
      })
      .finally(() => setKeysLoading(false))
  }

  useEffect(() => {
    loadKeys()
  }, [])

  const applySmtpPreset = (presetId) => {
    setSmtpPreset(presetId)
    const presets = emailStatus?.presets || []
    const p = presets.find((x) => x.id === presetId)
    if (!p) return
    smtpForm.setFieldsValue({
      smtp_host: p.smtp_host || '',
      smtp_port: p.smtp_port || '587',
      smtp_tls: p.smtp_tls !== '0',
    })
  }

  const saveSmtp = async (values) => {
    setSmtpSaving(true)
    try {
      const body = {
        preset: smtpPreset,
        smtp_host: values.smtp_host,
        smtp_port: values.smtp_port,
        smtp_user: values.smtp_user,
        smtp_from: values.smtp_from || values.smtp_user,
        smtp_tls: !!values.smtp_tls,
        test_to: values.send_test ? (values.test_to || user?.email) : undefined,
      }
      if (values.smtp_password) body.smtp_password = values.smtp_password
      const r = await api('/keys/email/smtp', { method: 'PUT', body })
      if (r.test && !r.test.ok) {
        message.warning(r.message || r.test.detail)
      } else {
        message.success(r.message || 'SMTP saved')
      }
      if (r.status) setEmailStatus((prev) => ({ ...(prev || {}), ...r.status, form: r.status.form || prev?.form }))
      loadKeys()
    } catch (e) {
      message.error(e.message)
    } finally {
      setSmtpSaving(false)
    }
  }

  const testSmtp = async () => {
    setSmtpSaving(true)
    try {
      const to = smtpForm.getFieldValue('test_to') || user?.email
      const r = await api('/keys/email/smtp/test', { method: 'POST', body: { to } })
      if (r.ok) message.success(`Test sent to ${r.to}`)
      else {
        const hint = r.hint || (r.detail && /Vercel|blocked|timed out|timeout/i.test(r.detail)
          ? ' Vercel often blocks SMTP — add Resend or Gmail OAuth.'
          : '')
        message.error((r.detail || 'Test failed') + hint, 12)
      }
      if (r.status) setEmailStatus((prev) => ({ ...(prev || {}), ...r.status }))
    } catch (e) {
      const msg = e?.message || String(e)
      message.error(
        /timed out|timeout|blocked|Vercel/i.test(msg)
          ? `${msg} — On Vercel use Resend API or Gmail Connected app instead of raw SMTP.`
          : msg,
        12,
      )
    } finally {
      setSmtpSaving(false)
    }
  }

  const clearSmtp = async () => {
    try {
      await api('/keys/email/smtp', { method: 'DELETE' })
      message.success('SMTP cleared')
      loadKeys()
    } catch (e) {
      message.error(e.message)
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

  const { llm: llmKeys, channels: channelKeys, other: otherKeys } = partitionKeys(keys, providers)

  const twilioReady = (() => {
    const has = (p) => channelKeys.some((k) => k.provider === p && (k.configured || k.has_value || k.masked))
    // providers list rows may use different shape
    const fromProviders = (providers || []).filter((p) => String(p.id || p.provider || '').startsWith('twilio'))
    const sid = channelKeys.find((k) => k.provider === 'twilio_sid')
      || fromProviders.find((p) => (p.id || p.provider) === 'twilio_sid')
    const tok = channelKeys.find((k) => k.provider === 'twilio_token')
      || fromProviders.find((p) => (p.id || p.provider) === 'twilio_token')
    const fr = channelKeys.find((k) => k.provider === 'twilio_from')
      || fromProviders.find((p) => (p.id || p.provider) === 'twilio_from')
    const ok = (row) => row && (row.configured || row.has_value || row.masked || row.hint)
    return !!(ok(sid) && ok(tok) && ok(fr))
  })()

  const openTwilioKeys = () => {
    const sid = providers.find((p) => p.id === 'twilio_sid') || {
      id: 'twilio_sid',
      label: 'Twilio Account SID',
      placeholder: 'AC…',
      help: 'From Twilio Console',
    }
    openKeyModal({ provider: 'twilio_sid', ...sid, configured: false })
  }

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
                <Space wrap>
                  {row.provider_label || row.provider}
                  {row.status === 'coming_soon' && <Tag>Coming soon</Tag>}
                  {row.status === 'api_only' && <Tag color="blue">API only</Tag>}
                  {(row.configured || row.id) ? (
                    <Tag color="success">Saved · {row.masked || `••••${row.hint}`}</Tag>
                  ) : (
                    <Tag>Not set</Tag>
                  )}
                </Space>
              }
              description={
                row.help
                || providers.find((p) => p.id === row.provider)?.help
                || 'Stored only for your subscriber account'
              }
            />
          </List.Item>
        )}
      />
    )
  )

  return (
    <>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Card
          title={<Space><MailOutlined /> Email (Resend) — platform ready</Space>}
          className="aba-soft-card"
          type="inner"
        >
          <Alert
            type={emailStatus?.ok || emailStatus?.user_resend || emailStatus?.platform_resend ? 'success' : 'info'}
            showIcon
            message={
              emailStatus?.ok || emailStatus?.platform_resend || emailStatus?.user_resend
                ? 'Email channel available (Resend and/or SMTP)'
                : 'Add Resend API key for reliable agent email (recommended on Vercel)'
            }
            description={
              <>
                Platform can use <Text code>RESEND_API_KEY</Text> + <Text code>RESEND_FROM</Text>.
                You can also save your own Resend key below under channel keys, or configure SMTP.
                On Vercel, Resend is preferred over raw SMTP (ports often blocked).
              </>
            }
            style={{ marginBottom: 0 }}
          />
        </Card>

        <Card
          title={<Space><ApiOutlined /> Twilio (SMS / calls) — priority</Space>}
          className="aba-soft-card"
          type="inner"
        >
          <Alert
            type={twilioReady ? 'success' : 'warning'}
            showIcon
            icon={twilioReady ? <CheckCircleOutlined /> : <SafetyCertificateOutlined />}
            message={twilioReady ? 'Twilio keys on file' : 'Connect Twilio for live SMS and voice'}
            description={
              twilioReady
                ? 'Channel keys are encrypted. Prefer Settings → Connected apps → Twilio for a guided connect (syncs here automatically).'
                : (
                  <>
                    Required: <Text code>twilio_sid</Text>, <Text code>twilio_token</Text>,{' '}
                    <Text code>twilio_from</Text> (E.164). Or use{' '}
                    <strong>Connected apps → Twilio</strong> (recommended).
                  </>
                )
            }
            action={(
              <Button type="primary" size="small" onClick={openTwilioKeys}>
                {twilioReady ? 'Update SID' : 'Add Twilio SID'}
              </Button>
            )}
            style={{ marginBottom: 0 }}
          />
        </Card>

        <Card title={<Space><KeyOutlined /> About your keys</Space>} className="aba-soft-card" type="inner">
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="Bring your own LLM & channel keys"
            description={
              <>
                Keys are encrypted with AES (Fernet) before storage and never shown in full again.
                <strong> Grok works via API only</strong> (your xAI key or the platform key).{' '}
                <strong>Claude</strong> and <strong>VPS small models</strong> are <strong>Coming soon</strong>.
                For Shopify, Google Workspace, Slack, etc. use the <strong>Connected apps</strong> tab.
                <strong> Twilio is highest priority</strong> for SMS/calls.
              </>
            }
          />
          <Space wrap>
            <Tag color="blue">Grok · API only</Tag>
            <Tag>Claude · Coming soon</Tag>
            <Tag>VPS small models · Coming soon</Tag>
            {!keysLoading && (() => {
              const configured = (p) => keys.some((k) => k.provider === p && (k.configured || k.id || k.hint || k.masked))
              const hasAnthropic = configured('anthropic')
              const hasXai = configured('xai')
              if (!hasAnthropic && !hasXai) return null
              const parts = []
              if (hasXai) parts.push('Grok (API)')
              if (hasAnthropic) parts.push('Claude (coming soon)')
              return (
                <Tag color="purple">
                  Using your {parts.join(' / ')} keys
                </Tag>
              )
            })()}
          </Space>
        </Card>

        <Card
          title={<Space><LockOutlined /> LLM providers <Tag icon={<SafetyCertificateOutlined />} color="green">Encrypted</Tag></Space>}
          className="aba-soft-card"
          type="inner"
        >
          {renderKeyList(llmKeys.length ? llmKeys : keys.filter((k) => ['anthropic', 'xai', 'openai', 'google'].includes(k.provider)))}
        </Card>

        <Card
          title={(
            <Space wrap>
              <MailOutlined />
              Email delivery (SMTP / Namecheap / Resend)
              {emailStatus?.ok ? <Tag color="success">Ready</Tag> : <Tag color="warning">Not set</Tag>}
            </Space>
          )}
          className="aba-soft-card"
          type="inner"
        >
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="Use your own mailbox to send agent email, notifications, and tests"
            description={(
              <>
                Recommended for domain email: <strong>Namecheap Private Email</strong>
                {' '}(<Text code>mail.privateemail.com</Text>, port 587, TLS).
                You can also use Gmail/Outlook SMTP or Resend API below.
                Platform env SMTP/Resend is used as fallback for password-reset / 2FA codes.
              </>
            )}
          />
          {(emailStatus?.smtp_blocked_risk || emailStatus?.serverless_host) && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message="Production host may block raw SMTP"
              description={(
                <>
                  This app runs on <strong>Vercel serverless</strong>, which often blocks outbound
                  ports 587/465. Saving Namecheap SMTP is fine for settings, but <strong>Send test</strong>
                  {' '}may time out. For reliable production mail, add a{' '}
                  <strong>Resend API key</strong> below or connect <strong>Gmail</strong> under Connected apps.
                  {(emailStatus?.warnings || []).length > 0 && (
                    <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
                      {emailStatus.warnings.map((w) => <li key={w}>{w}</li>)}
                    </ul>
                  )}
                </>
              )}
            />
          )}
          <Space wrap style={{ marginBottom: 12 }}>
            {(emailStatus?.presets || [
              { id: 'namecheap', label: 'Namecheap' },
              { id: 'gmail', label: 'Gmail' },
              { id: 'outlook', label: 'Outlook' },
              { id: 'custom', label: 'Custom' },
            ]).map((p) => (
              <Button
                key={p.id}
                type={smtpPreset === p.id ? 'primary' : 'default'}
                size="small"
                onClick={() => applySmtpPreset(p.id)}
              >
                {p.label}
              </Button>
            ))}
          </Space>
          {(() => {
            const p = (emailStatus?.presets || []).find((x) => x.id === smtpPreset)
            if (!p?.hints?.length) return null
            return (
              <Alert
                type="success"
                showIcon
                style={{ marginBottom: 16 }}
                message={p.label}
                description={(
                  <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
                    {p.hints.map((h) => <li key={h}>{h}</li>)}
                    {p.docs && (
                      <li>
                        <a href={p.docs} target="_blank" rel="noreferrer">Setup guide →</a>
                      </li>
                    )}
                  </ul>
                )}
              />
            )
          })()}
          <Form
            form={smtpForm}
            layout="vertical"
            onFinish={saveSmtp}
            style={{ maxWidth: 520 }}
            initialValues={{
              smtp_host: 'mail.privateemail.com',
              smtp_port: '587',
              smtp_tls: true,
              send_test: true,
            }}
          >
            <Row gutter={12}>
              <Col xs={24} sm={16}>
                <Form.Item
                  name="smtp_host"
                  label="SMTP host"
                  rules={[{ required: true, message: 'Host required' }]}
                >
                  <Input placeholder="mail.privateemail.com" />
                </Form.Item>
              </Col>
              <Col xs={24} sm={8}>
                <Form.Item name="smtp_port" label="Port" rules={[{ required: true }]}>
                  <Input placeholder="587" />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item
              name="smtp_user"
              label="Username (full email)"
              rules={[{ required: true, message: 'Email username required' }]}
            >
              <Input placeholder="you@yourdomain.com" autoComplete="username" />
            </Form.Item>
            <Form.Item
              name="smtp_password"
              label="Password"
              extra={emailStatus?.form?.smtp_password_set ? 'Leave blank to keep the saved password' : 'Mailbox password (Namecheap) or app password'}
              rules={emailStatus?.form?.smtp_password_set ? [] : [{ required: true, message: 'Password required' }]}
            >
              <Input.Password placeholder="••••••••" autoComplete="new-password" />
            </Form.Item>
            <Form.Item name="smtp_from" label="From address (optional)">
              <Input placeholder="Same as username if blank" />
            </Form.Item>
            <Form.Item name="smtp_tls" label="STARTTLS (port 587)" valuePropName="checked">
              <Switch checkedChildren="TLS on" unCheckedChildren="TLS off" />
            </Form.Item>
            <Form.Item name="test_to" label="Send test to">
              <Input placeholder={user?.email || 'you@example.com'} />
            </Form.Item>
            <Form.Item name="send_test" valuePropName="checked" initialValue>
              <Switch checkedChildren="Save + send test" unCheckedChildren="Save only" />
            </Form.Item>
            <Space wrap>
              <Button type="primary" htmlType="submit" loading={smtpSaving} icon={<CheckCircleOutlined />}>
                Save SMTP
              </Button>
              <Button loading={smtpSaving} onClick={testSmtp}>
                Send test email
              </Button>
              {emailStatus?.user_smtp && (
                <Popconfirm title="Remove saved SMTP credentials?" onConfirm={clearSmtp}>
                  <Button danger>Clear SMTP</Button>
                </Popconfirm>
              )}
            </Space>
          </Form>
          <Divider />
          <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
            Status: user SMTP {emailStatus?.user_smtp ? 'yes' : 'no'} · user Resend {emailStatus?.user_resend ? 'yes' : 'no'}
            {' · '}platform SMTP {emailStatus?.platform_smtp ? 'yes' : 'no'} · platform Resend {emailStatus?.platform_resend ? 'yes' : 'no'}
          </Text>
        </Card>

        <Card title={<Space><ApiOutlined /> Other channels (Resend API / SMS Twilio)</Space>} className="aba-soft-card" type="inner">
          {renderKeyList(
            (channelKeys.length ? channelKeys : keys.filter((k) => String(k.provider).startsWith('twilio') || k.provider === 'resend'))
              .filter((k) => !String(k.provider || '').startsWith('smtp_')),
          )}
        </Card>

        {otherKeys.length > 0 && (
          <Card title="Other keys" className="aba-soft-card" type="inner">
            {renderKeyList(otherKeys)}
          </Card>
        )}
      </Space>

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
    </>
  )
}
