import React, { useMemo, useState } from 'react'
import { Card, Form, Input, Button, message, Typography, Alert, Tabs } from 'antd'
import { LockOutlined, CheckCircleOutlined, ArrowLeftOutlined, MailOutlined } from '@ant-design/icons'
import { Link, useSearchParams, useNavigate } from 'react-router-dom'
import { api, setAuth } from '../api'

const PASSWORD_PLACEHOLDER = 'At least 8 characters, include a letter and number'

function passwordRules() {
  return [
    { required: true, message: 'Password is required' },
    { min: 8, message: 'Password must be at least 8 characters' },
    { pattern: /[A-Za-z]/, message: 'Password must contain at least one letter' },
    { pattern: /[0-9]/, message: 'Password must contain at least one number' },
  ]
}

export default function ResetPassword() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const token = useMemo(() => (params.get('token') || '').trim(), [params])
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)
  const [tab, setTab] = useState(token ? 'link' : 'code')

  const finish = (data) => {
    if (data?.token && data?.user) {
      setAuth(data.api_key || data.token, data.user)
      message.success('Password updated — signed in')
      if (data.user.needs_subscription) {
        nav('/subscribe', { replace: true })
      } else {
        nav('/', { replace: true })
      }
      return
    }
    setDone(true)
    message.success('Password updated')
  }

  const submitLink = async (values) => {
    if (!token) {
      message.error('Missing reset token. Open the link from your email, or use the code tab.')
      return
    }
    setLoading(true)
    try {
      const data = await api('/auth/reset-password', {
        method: 'POST',
        body: { token, password: values.password },
      })
      finish(data)
    } catch (e) {
      message.error(e?.message || 'Could not reset password')
    } finally {
      setLoading(false)
    }
  }

  const submitCode = async (values) => {
    setLoading(true)
    try {
      const data = await api('/auth/reset-password', {
        method: 'POST',
        body: {
          email: (values.email || '').trim(),
          code: String(values.code || '').trim(),
          password: values.password,
        },
      })
      finish(data)
    } catch (e) {
      message.error(e?.message || 'Could not reset password')
    } finally {
      setLoading(false)
    }
  }

  const passwordFields = (
    <>
      <Form.Item
        name="password"
        label="New password"
        rules={passwordRules()}
        extra="Min 8 characters, include a letter and a number"
      >
        <Input.Password placeholder={PASSWORD_PLACEHOLDER} autoComplete="new-password" />
      </Form.Item>
      <Form.Item
        name="confirm"
        label="Confirm password"
        dependencies={['password']}
        rules={[
          { required: true, message: 'Confirm your password' },
          ({ getFieldValue }) => ({
            validator(_, value) {
              if (!value || getFieldValue('password') === value) return Promise.resolve()
              return Promise.reject(new Error('Passwords do not match'))
            },
          }),
        ]}
      >
        <Input.Password placeholder="Re-enter new password" autoComplete="new-password" />
      </Form.Item>
    </>
  )

  return (
    <div className="aba-auth-shell">
      <div className="aba-page-center">
        <div className="aba-page-shell aba-auth-stack">
          <div className="aba-auth-hero" style={{ marginBottom: 28, width: '100%' }}>
            <div className="aba-auth-logo">
              <img
                src={`${import.meta.env.BASE_URL}logo.png`}
                alt="AI Business Assistant"
                width={88}
                height={88}
                style={{ objectFit: 'contain', borderRadius: '22%' }}
              />
            </div>
            <Typography.Title level={2} style={{ color: '#fff', margin: '0 0 8px', letterSpacing: '-0.03em' }}>
              AI Business Assistant
            </Typography.Title>
            <Typography.Paragraph style={{ color: 'rgba(255,255,255,0.88)', maxWidth: 420, margin: '0 auto' }}>
              Verify via email, then choose a new password.
            </Typography.Paragraph>
          </div>

          <div className="aba-page-shell-inner is-narrow aba-auth-form-wrap">
            <Card className="aba-auth-card aba-auth-form-card" bordered>
              <Button
                type="link"
                icon={<ArrowLeftOutlined />}
                onClick={() => nav('/login')}
                style={{ paddingLeft: 0, marginBottom: 8 }}
              >
                Back to sign in
              </Button>

              <Typography.Title level={4} style={{ marginTop: 0, textAlign: 'center' }}>
                <LockOutlined style={{ marginRight: 8 }} />
                Reset password
              </Typography.Title>

              {done ? (
                <>
                  <Alert
                    type="success"
                    showIcon
                    icon={<CheckCircleOutlined />}
                    message="Your password has been reset. You can sign in with the new password."
                    style={{ marginBottom: 16 }}
                  />
                  <Button type="primary" block size="large" onClick={() => nav('/login', { replace: true })}>
                    Go to sign in
                  </Button>
                </>
              ) : (
                <Tabs
                  activeKey={tab}
                  onChange={setTab}
                  centered
                  items={[
                    {
                      key: 'link',
                      label: 'Email link',
                      children: (
                        <>
                          {!token && (
                            <Alert
                              type="info"
                              showIcon
                              style={{ marginBottom: 16 }}
                              message="Open the reset link from your email, or use the Code tab with the 6-digit code."
                            />
                          )}
                          {token && (
                            <Alert
                              type="success"
                              showIcon
                              style={{ marginBottom: 16 }}
                              message="Link verified — set your new password below."
                            />
                          )}
                          <Form layout="vertical" onFinish={submitLink} requiredMark={false} size="large">
                            {passwordFields}
                            <Button type="primary" htmlType="submit" block size="large" loading={loading} disabled={!token}>
                              Update password
                            </Button>
                          </Form>
                        </>
                      ),
                    },
                    {
                      key: 'code',
                      label: 'Email code',
                      children: (
                        <>
                          <Alert
                            type="info"
                            showIcon
                            style={{ marginBottom: 16 }}
                            icon={<MailOutlined />}
                            message="Use the 6-digit code from your reset email"
                            description="Request a code from Sign in → Forgot password if you do not have one."
                          />
                          <Form layout="vertical" onFinish={submitCode} requiredMark={false} size="large">
                            <Form.Item name="email" label="Email" rules={[{ required: true, type: 'email' }]}>
                              <Input placeholder="you@business.com" autoComplete="email" />
                            </Form.Item>
                            <Form.Item
                              name="code"
                              label="Verification code"
                              rules={[
                                { required: true, message: 'Enter the 6-digit code' },
                                { len: 6, message: 'Code is 6 digits' },
                              ]}
                            >
                              <Input
                                placeholder="123456"
                                inputMode="numeric"
                                autoComplete="one-time-code"
                                maxLength={6}
                              />
                            </Form.Item>
                            {passwordFields}
                            <Button type="primary" htmlType="submit" block size="large" loading={loading}>
                              Verify & update password
                            </Button>
                          </Form>
                        </>
                      ),
                    },
                  ]}
                />
              )}

              <Typography.Paragraph
                type="secondary"
                style={{ marginTop: 16, marginBottom: 0, fontSize: 12, textAlign: 'center' }}
              >
                <Link to="/login">Back to sign in</Link>
              </Typography.Paragraph>
            </Card>
          </div>
        </div>
      </div>
    </div>
  )
}
