import React, { useEffect, useState } from 'react'
import {
  Card, Descriptions, Typography, Alert, Form, Input, Button, Tag, Space, message,
  Spin, Divider, List, Popconfirm, Modal,
} from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined, LockOutlined, KeyOutlined, DeleteOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { getUser, setAuth, getToken, API, api } from '../api'

function StatusTag({ ok, label }) {
  return (
    <Tag icon={ok ? <CheckCircleOutlined /> : <CloseCircleOutlined />} color={ok ? 'success' : 'default'}>
      {label}: {ok ? 'live' : 'not configured'}
    </Tag>
  )
}

export default function Settings() {
  const [user, setUser] = useState(getUser())
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [keys, setKeys] = useState([])
  const [keysLoading, setKeysLoading] = useState(true)
  const [providers, setProviders] = useState([])
  const [keyModal, setKeyModal] = useState(null) // provider meta + existing
  const [keySaving, setKeySaving] = useState(false)
  const [keyForm] = Form.useForm()
  const embed = `<script src="${API}/embed.js" data-business="${user?.email || ''}"></script>`

  const loadKeys = () => {
    setKeysLoading(true)
    Promise.all([
      api('/keys').catch(() => ({ keys: [] })),
      api('/keys/providers').catch(() => []),
    ])
      .then(([k, p]) => {
        setKeys(k.keys || [])
        setProviders(p || [])
      })
      .finally(() => setKeysLoading(false))
  }

  useEffect(() => {
    api('/system/status')
      .then(setStatus)
      .catch(() => setStatus(null))
      .finally(() => setLoading(false))
    loadKeys()
  }, [])

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
    const meta = providers.find(p => p.id === row.provider) || {
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

  return (
    <div>
      <Card title="Profile" style={{ marginBottom: 16 }}>
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

      <Card
        title={
          <Space>
            <LockOutlined />
            Your API keys
            <Tag icon={<SafetyCertificateOutlined />} color="green">Encrypted at rest</Tag>
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="Bring your own keys"
          description={
            <>
              Keys are encrypted with AES (Fernet) before storage and never shown in full again.
              Your keys are used for <strong>your</strong> Claude/Grok calls when set; otherwise the platform falls back to its own config or mock.
              Supported: Anthropic, xAI, OpenAI, Google, Resend, Twilio.
            </>
          }
        />
        {!keysLoading && (() => {
          const configured = (p) => keys.some(k => k.provider === p && (k.configured || k.id || k.hint || k.masked))
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
        {keysLoading ? <Spin /> : (
          <List
            dataSource={keys}
            renderItem={(row) => (
              <List.Item
                actions={[
                  <Button key="set" type="link" icon={<KeyOutlined />} onClick={() => openKeyModal(row)}>
                    {row.configured || row.id ? 'Update' : 'Add'}
                  </Button>,
                  (row.configured || row.id) && (
                    <Popconfirm
                      key="del"
                      title="Delete this encrypted key?"
                      onConfirm={() => deleteKey(row.provider)}
                    >
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
                    providers.find(p => p.id === row.provider)?.help
                    || 'Stored only for your subscriber account'
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Card>

      <Card title="Platform integration status" style={{ marginBottom: 16 }}>
        <Typography.Paragraph type="secondary">
          Platform-level keys (server <Typography.Text code>.env</Typography.Text>). Your vault keys above take priority for LLM providers when present.
        </Typography.Paragraph>
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
          </>
        ) : (
          <Alert type="error" message="Could not load system status" />
        )}
      </Card>

      <Card title="Website embed code">
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="Paste this on your website to add your AI assistant (embed widget ships in a later build)."
        />
        <Typography.Paragraph copyable code>{embed}</Typography.Paragraph>
      </Card>

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
            <Typography.Paragraph type="secondary">{keyModal.help}</Typography.Paragraph>
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
    </div>
  )
}
