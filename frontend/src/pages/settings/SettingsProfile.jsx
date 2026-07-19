import React, { useState } from 'react'
import {
  Card, Descriptions, Typography, Alert, Form, Input, Button, Space, message,
  Divider, Modal,
} from 'antd'
import {
  DeleteOutlined, SafetyCertificateOutlined, UserOutlined,
  DownloadOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { getUser, setAuth, getToken, clearAuth, api } from '../../api'

const { Text, Paragraph } = Typography

export default function SettingsProfile() {
  const nav = useNavigate()
  const [user, setUser] = useState(getUser())
  const [saving, setSaving] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteForm] = Form.useForm()
  const marketingOrigin = typeof window !== 'undefined' ? window.location.origin : ''

  const saveProfile = async (values) => {
    setSaving(true)
    try {
      const updated = await api('/auth/me', { method: 'PATCH', body: { name: values.name } })
      setAuth(getToken(), updated)
      setUser(updated)
      message.success('Profile updated')
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
    <>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Card title="Quick links" className="aba-soft-card" type="inner">
          <Space wrap>
            <Button type="link" style={{ padding: 0 }} onClick={() => nav('/profile')}>
              Open full profile page
            </Button>
            <Button type="link" onClick={() => nav('/permissions')}>Team permissions</Button>
            <Button type="link" onClick={() => nav('/humans')}>Users / Team</Button>
          </Space>
        </Card>
        <Card title={<Space><UserOutlined /> Profile</Space>} className="aba-soft-card" type="inner">
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
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message="Password & 2FA"
              description={
                <>
                  Change password and manage email two-factor authentication under{' '}
                  <a onClick={() => nav('/profile')}>Profile → Security</a>
                  {' '}(email verification codes required).
                </>
              }
            />
            <Descriptions size="small" column={1} style={{ marginBottom: 12 }}>
              <Descriptions.Item label="Role">{user?.role}</Descriptions.Item>
              <Descriptions.Item label="Plan">{user?.plan}</Descriptions.Item>
              <Descriptions.Item label="2FA">
                {user?.twofa_enabled ? 'Email 2FA on' : 'Off'}
              </Descriptions.Item>
            </Descriptions>
            <Button type="primary" htmlType="submit" loading={saving}>Save changes</Button>
          </Form>
        </Card>
        <Card title={<Space><SafetyCertificateOutlined /> Privacy</Space>} className="aba-soft-card" type="inner">
          <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
            Export a copy of your account data, or permanently delete your account. Review our legal pages on this deploy origin.
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
      </Space>

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
    </>
  )
}
