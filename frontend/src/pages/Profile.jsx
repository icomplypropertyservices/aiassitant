import React, { useEffect, useState } from 'react'
import {
  Card, Form, Input, Button, Descriptions, Tag, Statistic, Row, Col, message, Space, Typography, Divider, Modal,
} from 'antd'
import {
  UserOutlined, MailOutlined, CrownOutlined, CreditCardOutlined,
  DeleteOutlined, DownloadOutlined, ExclamationCircleOutlined, SafetyCertificateOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, getUser, setAuth, getToken, clearAuth } from '../api'

const { Title, Text, Paragraph } = Typography

export default function Profile() {
  const nav = useNavigate()
  const [me, setMe] = useState(getUser())
  const [meter, setMeter] = useState(null)
  const [saving, setSaving] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [form] = Form.useForm()
  const [deleteForm] = Form.useForm()
  const marketingOrigin = typeof window !== 'undefined' ? window.location.origin : ''

  const load = async () => {
    try {
      const u = await api('/auth/me')
      setMe(u)
      setAuth(getToken(), u)
      form.setFieldsValue({ name: u.name || '', email: u.email })
      if (u.meter) setMeter(u.meter)
      else {
        const m = await api('/billing/meter').catch(() => null)
        setMeter(m)
      }
    } catch (e) {
      message.error(e.message)
    }
  }

  useEffect(() => { load() }, [])

  const save = async (values) => {
    setSaving(true)
    try {
      const body = { name: values.name }
      if (values.password) body.password = values.password
      const u = await api('/auth/me', { method: 'PATCH', body })
      setMe(u)
      setAuth(getToken(), { ...getUser(), ...u })
      message.success('Profile updated')
      form.setFieldsValue({ password: '' })
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const exportData = async () => {
    setExporting(true)
    try {
      const data = await api('/auth/export')
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `account-export-${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      message.success('Data export downloaded')
    } catch (e) {
      message.error(e?.message || 'Export failed')
    } finally {
      setExporting(false)
    }
  }

  const confirmDeleteAccount = async (values) => {
    setDeleting(true)
    try {
      await api('/auth/delete-account', { method: 'POST', body: { password: values.password } })
      clearAuth()
      message.success('Account deleted')
      setDeleteOpen(false)
      deleteForm.resetFields()
      nav('/login', { replace: true })
    } catch (e) {
      message.error(e?.message || 'Could not delete account')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: '0 auto' }}>
      <Title level={3}><UserOutlined /> Your profile</Title>
      <Text type="secondary">Account owner settings for this workspace.</Text>

      <Row gutter={[16, 16]} style={{ marginTop: 16, marginBottom: 16 }}>
        <Col xs={12} md={8}>
          <Card size="small">
            <Statistic title="Plan" value={(me?.plan || 'none').replace(/_/g, ' ')} prefix={<CrownOutlined />} />
          </Card>
        </Col>
        <Col xs={12} md={8}>
          <Card size="small">
            <Statistic title="Wallet" prefix="$" value={meter?.credits ?? 0} precision={2} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small">
            <Statistic
              title="Tokens this period"
              value={meter?.tokens_used_period ?? 0}
              suffix={`/ ${(meter?.tokens_included ?? 0).toLocaleString()}`}
            />
          </Card>
        </Col>
      </Row>

      <Card title="Account" style={{ marginBottom: 16 }}>
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="Email"><MailOutlined /> {me?.email}</Descriptions.Item>
          <Descriptions.Item label="Role">
            <Tag color={me?.role === 'admin' ? 'gold' : 'blue'}>{me?.role || 'user'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Subscription">
            <Tag color={me?.subscription_active ? 'green' : 'red'}>
              {me?.subscription_active ? 'Active' : 'Inactive'}
            </Tag>
          </Descriptions.Item>
          {me?.subscription_expires_at && (
            <Descriptions.Item label="Expires">{new Date(me.subscription_expires_at).toLocaleString()}</Descriptions.Item>
          )}
        </Descriptions>
        <Space style={{ marginTop: 12 }} wrap>
          <Button icon={<CreditCardOutlined />} onClick={() => nav('/billing')}>Billing</Button>
          <Button onClick={() => nav('/permissions')}>Team permissions</Button>
          <Button onClick={() => nav('/humans')}>Team / humans</Button>
          <Button onClick={() => nav('/settings?tab=profile')}>Settings</Button>
        </Space>
      </Card>

      <Card title="Edit profile">
        <Form form={form} layout="vertical" onFinish={save}>
          <Form.Item name="name" label="Display name" rules={[{ required: true }]}>
            <Input prefix={<UserOutlined />} placeholder="Your name" />
          </Form.Item>
          <Form.Item name="email" label="Email">
            <Input disabled prefix={<MailOutlined />} />
          </Form.Item>
          <Form.Item
            name="password"
            label="New password"
            extra="Leave blank to keep current password. Min 8 characters, include a letter and a number."
            rules={[
              { min: 8, message: 'Password must be at least 8 characters' },
              {
                validator(_, value) {
                  if (!value) return Promise.resolve()
                  if (!/[A-Za-z]/.test(value)) return Promise.reject(new Error('Password must contain at least one letter'))
                  if (!/[0-9]/.test(value)) return Promise.reject(new Error('Password must contain at least one number'))
                  return Promise.resolve()
                },
              },
            ]}
          >
            <Input.Password placeholder="At least 8 characters, include a letter and number" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving}>Save profile</Button>
        </Form>
      </Card>

      <Card
        title={<Space><SafetyCertificateOutlined /> Privacy</Space>}
        style={{ marginTop: 16 }}
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          Export a copy of your account data, or permanently delete your account. Legal pages use this deploy origin.
        </Text>
        <Space wrap style={{ marginBottom: 12 }}>
          <Button icon={<DownloadOutlined />} loading={exporting} onClick={exportData}>
            Export my data
          </Button>
          <Button
            danger
            icon={<DeleteOutlined />}
            loading={deleting}
            onClick={() => {
              deleteForm.resetFields()
              setDeleteOpen(true)
            }}
          >
            Delete account
          </Button>
        </Space>
        <div>
          <Space split={<Divider type="vertical" />} wrap>
            <a href={`${marketingOrigin}/privacy.html`} target="_blank" rel="noopener noreferrer">
              Privacy policy
            </a>
            <a href={`${marketingOrigin}/terms.html`} target="_blank" rel="noopener noreferrer">
              Terms of service
            </a>
          </Space>
        </div>
      </Card>

      <Modal
        title={
          <Space>
            <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />
            Delete your account?
          </Space>
        }
        open={deleteOpen}
        onCancel={() => {
          if (!deleting) {
            setDeleteOpen(false)
            deleteForm.resetFields()
          }
        }}
        footer={null}
        destroyOnClose
      >
        <Paragraph type="secondary">
          This deactivates your account, scrubs personal identifiers, and cannot be undone.
          Enter your password to confirm.
        </Paragraph>
        <Form form={deleteForm} layout="vertical" onFinish={confirmDeleteAccount}>
          <Form.Item
            name="password"
            label="Current password"
            rules={[{ required: true, message: 'Password is required' }]}
          >
            <Input.Password placeholder="Current password" autoComplete="current-password" />
          </Form.Item>
          <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
            <Button
              onClick={() => {
                setDeleteOpen(false)
                deleteForm.resetFields()
              }}
              disabled={deleting}
            >
              Cancel
            </Button>
            <Button type="primary" danger htmlType="submit" loading={deleting} icon={<DeleteOutlined />}>
              Delete account
            </Button>
          </Space>
        </Form>
      </Modal>
    </div>
  )
}
