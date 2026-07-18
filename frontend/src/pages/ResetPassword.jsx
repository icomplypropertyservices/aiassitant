import React, { useMemo, useState } from 'react'
import { Card, Form, Input, Button, message, Typography, Alert } from 'antd'
import { LockOutlined, CheckCircleOutlined } from '@ant-design/icons'
import { Link, useSearchParams, useNavigate } from 'react-router-dom'
import { api, setAuth } from '../api'

const PASSWORD_PLACEHOLDER = 'At least 8 characters, include a letter and number'

export default function ResetPassword() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const token = useMemo(() => (params.get('token') || '').trim(), [params])
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)

  const submit = async (values) => {
    if (!token) {
      message.error('Missing reset token. Open the link from your email.')
      return
    }
    setLoading(true)
    try {
      const data = await api('/auth/reset-password', {
        method: 'POST',
        body: {
          token,
          password: values.password,
        },
      })
      if (data?.token && data?.user) {
        setAuth(data.token, data.user)
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
    } catch (e) {
      message.error(e?.message || 'Could not reset password')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="aba-auth-shell">
      <div style={{ maxWidth: 440, margin: '0 auto' }}>
        <Card className="aba-auth-card" style={{ borderRadius: 16 }}>
          <Typography.Title level={3} style={{ marginTop: 0 }}>
            <LockOutlined /> Reset password
          </Typography.Title>
          {!token && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message="No reset token found"
              description="Use the link from your password-reset email, or request a new one from the sign-in page."
            />
          )}
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
            <Form layout="vertical" onFinish={submit} requiredMark={false} size="large">
              <Form.Item
                name="password"
                label="New password"
                rules={[
                  { required: true, message: 'Password is required' },
                  { min: 8, message: 'Password must be at least 8 characters' },
                  { pattern: /[A-Za-z]/, message: 'Password must contain at least one letter' },
                  { pattern: /[0-9]/, message: 'Password must contain at least one number' },
                ]}
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
              <Button type="primary" htmlType="submit" block size="large" loading={loading} disabled={!token}>
                Update password
              </Button>
            </Form>
          )}
          <Typography.Paragraph type="secondary" style={{ marginTop: 16, marginBottom: 0, textAlign: 'center' }}>
            <Link to="/login">Back to sign in</Link>
          </Typography.Paragraph>
        </Card>
      </div>
    </div>
  )
}
