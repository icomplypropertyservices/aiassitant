import React, { useEffect, useState } from 'react'
import {
  Card, Form, Input, Button, Descriptions, Tag, Statistic, Row, Col, message, Space, Typography, Divider, Modal, Progress, Alert,
} from 'antd'
import {
  UserOutlined, MailOutlined, CrownOutlined, CreditCardOutlined,
  DeleteOutlined, DownloadOutlined, ExclamationCircleOutlined, SafetyCertificateOutlined,
  ThunderboltOutlined, WalletOutlined, ReloadOutlined, TeamOutlined, RocketOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, getUser, setAuth, getToken, clearAuth } from '../api'
import PageHeader from '../components/PageHeader'
import PageShell from '../components/PageShell'

const { Text, Paragraph } = Typography

function formatTokens(n) {
  const v = Number(n) || 0
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(v % 1_000_000 === 0 ? 0 : 1)}M`
  if (v >= 1_000) return `${(v / 1_000).toFixed(v % 1_000 === 0 ? 0 : 1)}k`
  return v.toLocaleString()
}

export default function Profile() {
  const nav = useNavigate()
  const [me, setMe] = useState(getUser())
  const [meter, setMeter] = useState(null)
  const [saving, setSaving] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [reconciling, setReconciling] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [form] = Form.useForm()
  const [deleteForm] = Form.useForm()
  const [pwForm] = Form.useForm()
  const [twofaBusy, setTwofaBusy] = useState(false)
  const [pwStep, setPwStep] = useState('idle') // idle | code
  const [pwBusy, setPwBusy] = useState(false)
  const marketingOrigin = typeof window !== 'undefined' ? window.location.origin : ''

  const load = async () => {
    try {
      const u = await api('/auth/me')
      setMe(u)
      setAuth(getToken(), u)
      form.setFieldsValue({ name: u.name || '', email: u.email })
      let m = u.meter
      if (!m) {
        m = await api('/billing/meter').catch(() => null)
      }
      // Auto-heal: business/pro/starter with empty token pool
      const plan = (u.plan || m?.plan || '').toLowerCase()
      const included = Number(m?.tokens_included || 0)
      const paidPlans = ['starter', 'pro', 'business', 'trial']
      if (u.subscription_active && paidPlans.includes(plan) && included <= 0) {
        try {
          const fixed = await api('/billing/reconcile-plan', { method: 'POST', body: {} })
          if (fixed?.meter) m = fixed.meter
          if (fixed?.plan) setMe((prev) => ({ ...prev, plan: fixed.plan, subscription_expires_at: fixed.subscription_expires_at }))
          if (fixed?.tokens_included_after > 0) {
            message.success(fixed.message || 'Token pool restored from your plan')
          }
        } catch {
          /* ignore — user can click Fix token pool */
        }
      }
      setMeter(m)
    } catch (e) {
      message.error(e.message)
    }
  }

  useEffect(() => { load() }, [])

  const reconcile = async () => {
    setReconciling(true)
    try {
      const r = await api('/billing/reconcile-plan', { method: 'POST', body: {} })
      if (r?.meter) setMeter(r.meter)
      setMe((prev) => ({
        ...prev,
        plan: r.plan || prev?.plan,
        subscription_expires_at: r.subscription_expires_at ?? prev?.subscription_expires_at,
      }))
      message.success(r.message || 'Plan token pool updated')
    } catch (e) {
      message.error(e?.message || 'Could not sync plan tokens')
    } finally {
      setReconciling(false)
    }
  }

  const save = async (values) => {
    setSaving(true)
    try {
      const u = await api('/auth/me', { method: 'PATCH', body: { name: values.name } })
      setMe(u)
      setAuth(getToken(), { ...getUser(), ...u })
      message.success('Profile updated')
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const enable2faStart = async () => {
    setTwofaBusy(true)
    try {
      const r = await api('/auth/2fa/enable/start', { method: 'POST', body: {} })
      if (r.dev_otp_code) message.info(`Dev code: ${r.dev_otp_code}`)
      else message.success(r.message || 'Code sent to your email')
      setPwStep('enable2fa')
      pwForm.resetFields()
    } catch (e) {
      message.error(e.message)
    } finally {
      setTwofaBusy(false)
    }
  }

  const enable2faConfirm = async (values) => {
    setTwofaBusy(true)
    try {
      const r = await api('/auth/2fa/enable/confirm', {
        method: 'POST',
        body: { code: String(values.code || '').trim() },
      })
      setMe(r.user || { ...me, twofa_enabled: true })
      setAuth(getToken(), { ...getUser(), ...(r.user || {}), twofa_enabled: true })
      message.success(r.message || '2FA enabled')
      setPwStep('idle')
      pwForm.resetFields()
    } catch (e) {
      message.error(e.message)
    } finally {
      setTwofaBusy(false)
    }
  }

  const disable2faStart = async () => {
    setTwofaBusy(true)
    try {
      const r = await api('/auth/2fa/disable/start', { method: 'POST', body: {} })
      if (r.dev_otp_code) message.info(`Dev code: ${r.dev_otp_code}`)
      else message.success(r.message || 'Code sent')
      setPwStep('disable2fa')
      pwForm.resetFields()
    } catch (e) {
      message.error(e.message)
    } finally {
      setTwofaBusy(false)
    }
  }

  const disable2faConfirm = async (values) => {
    setTwofaBusy(true)
    try {
      const r = await api('/auth/2fa/disable/confirm', {
        method: 'POST',
        body: { code: String(values.code || '').trim() },
      })
      setMe(r.user || { ...me, twofa_enabled: false })
      setAuth(getToken(), { ...getUser(), ...(r.user || {}), twofa_enabled: false })
      message.success(r.message || '2FA disabled')
      setPwStep('idle')
      pwForm.resetFields()
    } catch (e) {
      message.error(e.message)
    } finally {
      setTwofaBusy(false)
    }
  }

  const passwordChangeStart = async (values) => {
    setPwBusy(true)
    try {
      const r = await api('/auth/password/change/start', {
        method: 'POST',
        body: { current_password: values.current_password },
      })
      if (r.dev_otp_code) message.info(`Dev code: ${r.dev_otp_code}`)
      else message.success(r.message || 'Code sent to your email')
      setPwStep('pwcode')
      pwForm.setFieldsValue({ current_password: values.current_password })
    } catch (e) {
      message.error(e.message)
    } finally {
      setPwBusy(false)
    }
  }

  const passwordChangeConfirm = async (values) => {
    setPwBusy(true)
    try {
      const r = await api('/auth/password/change', {
        method: 'POST',
        body: {
          current_password: values.current_password,
          password: values.password,
          code: String(values.code || '').trim(),
        },
      })
      if (r.api_key || r.token) {
        setAuth(r.api_key || r.token, r.user || me)
      }
      if (r.user) setMe(r.user)
      message.success(r.message || 'Password updated')
      setPwStep('idle')
      pwForm.resetFields()
    } catch (e) {
      message.error(e.message)
    } finally {
      setPwBusy(false)
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

  const planLabel = (me?.plan || meter?.plan || 'none').replace(/_/g, ' ')
  const included = Number(meter?.tokens_included ?? 0)
  const used = Number(meter?.tokens_used_period ?? 0)
  const remaining = Number(meter?.tokens_remaining_included ?? Math.max(0, included - used))
  const pct = included > 0 ? Math.min(100, Math.round((used / included) * 1000) / 10) : 0
  const emptyPool = (me?.subscription_active || meter?.subscription_active) && included <= 0
    && ['starter', 'pro', 'business', 'trial'].includes((me?.plan || '').toLowerCase())

  return (
    <PageShell narrow>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Card className="aba-soft-card" styles={{ body: { paddingBlock: 16 } }}>
          <PageHeader
            title={<Space><UserOutlined /> Your profile</Space>}
            subtitle={`Account owner settings for this workspace${me?.name ? ` · ${me.name}` : ''}.`}
            style={{ marginBottom: 0 }}
          />
        </Card>

        {emptyPool && (
          <Card className="aba-soft-card" size="small">
            <Alert
              type="warning"
              showIcon
              message="Token pool not applied"
              description={(
                <span>
                  Your plan is <strong>{planLabel}</strong> but the included token pool is still 0.
                  Click <strong>Fix token pool</strong> to load the Business/Pro monthly tokens so agents can run.
                </span>
              )}
              action={(
                <Button type="primary" size="small" icon={<ReloadOutlined />} loading={reconciling} onClick={reconcile}>
                  Fix token pool
                </Button>
              )}
            />
          </Card>
        )}

        <Card title="Usage overview" className="aba-soft-card" size="small">
          <Row gutter={[16, 16]}>
            <Col xs={12} md={8}>
              <Card size="small" type="inner" className="aba-stat-card">
                <Statistic
                  title="Plan"
                  value={planLabel}
                  prefix={<CrownOutlined />}
                  valueStyle={{ textTransform: 'capitalize', fontSize: 22 }}
                />
                <Tag color={me?.subscription_active || meter?.subscription_active ? 'green' : 'red'} style={{ marginTop: 8 }}>
                  {(me?.subscription_active || meter?.subscription_active) ? 'Subscription active' : 'Inactive'}
                </Tag>
              </Card>
            </Col>
            <Col xs={12} md={8}>
              <Card size="small" type="inner" className="aba-stat-card">
                <Statistic
                  title="Wallet credits"
                  prefix={<WalletOutlined />}
                  value={meter?.credits ?? 0}
                  precision={2}
                  suffix="USD"
                />
                <Button type="link" size="small" style={{ padding: 0, marginTop: 4 }} onClick={() => nav('/billing')}>
                  Top up wallet →
                </Button>
              </Card>
            </Col>
            <Col xs={24} md={8}>
              <Card size="small" type="inner" className="aba-stat-card">
                <Statistic
                  title="Tokens this period"
                  value={formatTokens(used)}
                  suffix={`/ ${formatTokens(included)}`}
                  prefix={<ThunderboltOutlined />}
                />
                {included > 0 ? (
                  <Progress
                    percent={pct}
                    size="small"
                    status={pct >= 95 ? 'exception' : pct >= 80 ? 'active' : 'normal'}
                    style={{ marginTop: 8 }}
                    format={() => `${formatTokens(remaining)} left`}
                  />
                ) : (
                  <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
                    No included pool yet — reconcile plan or top up wallet.
                  </Text>
                )}
              </Card>
            </Col>
          </Row>
        </Card>

        <Card title="Workspace & agents" className="aba-soft-card">
          <Space wrap>
            <Button type="primary" icon={<RocketOutlined />} onClick={() => nav('/agents')}>
              Open agents
            </Button>
            <Button icon={<TeamOutlined />} onClick={() => nav('/hierarchy')}>
              Agent hierarchy
            </Button>
            <Button onClick={() => nav('/companies')}>Companies</Button>
            <Button onClick={() => nav('/ops')}>Live ops</Button>
            <Button icon={<ReloadOutlined />} loading={reconciling} onClick={reconcile}>
              Sync plan tokens
            </Button>
          </Space>
          <Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
            Business plan includes up to <strong>40M tokens/month</strong>, 100 agents and 15 companies.
            If Live Ops says “waiting”, open Agents and ensure the Main Orchestrator is created.
          </Paragraph>
        </Card>

        <Card title="Account" className="aba-soft-card">
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="Email"><MailOutlined /> {me?.email}</Descriptions.Item>
            <Descriptions.Item label="Display name">{me?.name || '—'}</Descriptions.Item>
            <Descriptions.Item label="Role">
              <Tag color={me?.role === 'admin' ? 'gold' : 'blue'}>{me?.role || 'user'}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Plan">
              <Tag color="purple" style={{ textTransform: 'capitalize' }}>{planLabel}</Tag>
              {(meter?.plan_name || me?.plan) && (
                <Text type="secondary" style={{ marginLeft: 8 }}>
                  {meter?.plan_name || ''} · {formatTokens(included)} tokens/mo
                </Text>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="Subscription">
              <Tag color={me?.subscription_active || meter?.subscription_active ? 'green' : 'red'}>
                {(me?.subscription_active || meter?.subscription_active) ? 'Active' : 'Inactive'}
              </Tag>
            </Descriptions.Item>
            {(me?.subscription_expires_at || meter?.subscription_expires_at) ? (
              <Descriptions.Item label="Access ends">
                {new Date(me?.subscription_expires_at || meter?.subscription_expires_at).toLocaleString()}
                <Text type="secondary" style={{ display: 'block', fontSize: 12 }}>
                  Paid Business/Pro plans should not use a trial end date — use Sync plan tokens if this looks wrong.
                </Text>
              </Descriptions.Item>
            ) : (
              <Descriptions.Item label="Access ends">
                <Text type="secondary">No end date (open subscription)</Text>
              </Descriptions.Item>
            )}
          </Descriptions>
          <Space style={{ marginTop: 12 }} wrap>
            <Button icon={<CreditCardOutlined />} onClick={() => nav('/billing')}>Billing</Button>
            <Button onClick={() => nav('/permissions')}>Team permissions</Button>
            <Button onClick={() => nav('/humans')}>Team / humans</Button>
            <Button onClick={() => nav('/settings?tab=profile')}>Settings</Button>
          </Space>
        </Card>

        <Card title="Edit profile" className="aba-soft-card">
          <Form form={form} layout="vertical" onFinish={save} style={{ maxWidth: 420 }}>
            <Form.Item name="name" label="Display name" rules={[{ required: true }]}>
              <Input prefix={<UserOutlined />} placeholder="Your name (e.g. Jack Scott)" />
            </Form.Item>
            <Form.Item name="email" label="Email">
              <Input disabled prefix={<MailOutlined />} />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={saving}>Save profile</Button>
          </Form>
        </Card>

        <Card
          title={<Space><SafetyCertificateOutlined /> Security — email verification &amp; 2FA</Space>}
          className="aba-soft-card"
        >
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="Email is your second factor"
            description="Password reset and password changes require a code emailed to you. Optional 2FA also requires a code at every sign-in."
          />
          <Space wrap style={{ marginBottom: 16 }}>
            <Tag color={me?.email_verified ? 'success' : 'warning'}>
              Email {me?.email_verified ? 'verified' : 'not verified'}
            </Tag>
            <Tag color={me?.twofa_enabled ? 'success' : 'default'}>
              2FA {me?.twofa_enabled ? 'ON (email)' : 'OFF'}
            </Tag>
            {!me?.email_verified && (
              <Button
                size="small"
                onClick={async () => {
                  try {
                    const r = await api('/auth/resend-verification', { method: 'POST', body: {} })
                    message.success(r.message || 'Verification email sent')
                  } catch (e) {
                    message.error(e.message)
                  }
                }}
              >
                Resend verification email
              </Button>
            )}
          </Space>

          <Typography.Title level={5} style={{ marginTop: 0 }}>Two-factor authentication</Typography.Title>
          {me?.twofa_enabled ? (
            <Space wrap>
              <Button danger loading={twofaBusy} onClick={disable2faStart}>
                Turn off 2FA (email code required)
              </Button>
            </Space>
          ) : (
            <Button type="primary" loading={twofaBusy} onClick={enable2faStart}>
              Enable email 2FA
            </Button>
          )}

          {(pwStep === 'enable2fa' || pwStep === 'disable2fa') && (
            <Form
              form={pwForm}
              layout="vertical"
              style={{ maxWidth: 360, marginTop: 16 }}
              onFinish={pwStep === 'enable2fa' ? enable2faConfirm : disable2faConfirm}
            >
              <Form.Item
                name="code"
                label="Email verification code"
                rules={[{ required: true, len: 6, message: 'Enter the 6-digit code' }]}
              >
                <Input placeholder="123456" inputMode="numeric" maxLength={6} autoComplete="one-time-code" />
              </Form.Item>
              <Space>
                <Button type="primary" htmlType="submit" loading={twofaBusy}>
                  Confirm
                </Button>
                <Button onClick={() => { setPwStep('idle'); pwForm.resetFields() }}>Cancel</Button>
              </Space>
            </Form>
          )}

          <Divider />

          <Typography.Title level={5}>Change password</Typography.Title>
          <Paragraph type="secondary">
            Requires your current password plus a one-time code emailed to you.
          </Paragraph>
          {pwStep === 'pwcode' ? (
            <Form form={pwForm} layout="vertical" style={{ maxWidth: 420 }} onFinish={passwordChangeConfirm}>
              <Form.Item name="current_password" hidden>
                <Input.Password />
              </Form.Item>
              <Form.Item
                name="code"
                label="Email verification code"
                rules={[{ required: true, len: 6, message: '6-digit code from email' }]}
              >
                <Input placeholder="123456" inputMode="numeric" maxLength={6} autoComplete="one-time-code" />
              </Form.Item>
              <Form.Item
                name="password"
                label="New password"
                rules={[
                  { required: true, min: 8 },
                  {
                    validator(_, value) {
                      if (!value) return Promise.resolve()
                      if (!/[A-Za-z]/.test(value)) return Promise.reject(new Error('Need a letter'))
                      if (!/[0-9]/.test(value)) return Promise.reject(new Error('Need a number'))
                      return Promise.resolve()
                    },
                  },
                ]}
              >
                <Input.Password placeholder="At least 8 characters, letter + number" autoComplete="new-password" />
              </Form.Item>
              <Space>
                <Button type="primary" htmlType="submit" loading={pwBusy}>Update password</Button>
                <Button onClick={() => { setPwStep('idle'); pwForm.resetFields() }}>Cancel</Button>
              </Space>
            </Form>
          ) : (
            <Form form={pwForm} layout="vertical" style={{ maxWidth: 420 }} onFinish={passwordChangeStart}>
              <Form.Item
                name="current_password"
                label="Current password"
                rules={[{ required: true, message: 'Enter current password' }]}
              >
                <Input.Password autoComplete="current-password" />
              </Form.Item>
              <Button type="primary" htmlType="submit" loading={pwBusy}>
                Email me a verification code
              </Button>
            </Form>
          )}
        </Card>

        <Card title={<Space><SafetyCertificateOutlined /> Privacy</Space>} className="aba-soft-card">
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
      </Space>

      <Modal
        title={(
          <Space>
            <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />
            Delete your account?
          </Space>
        )}
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
    </PageShell>
  )
}
