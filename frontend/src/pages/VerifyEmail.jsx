import React, { useEffect, useState } from 'react'
import { Button, Card, Result, Spin, Typography } from 'antd'
import { MailOutlined } from '@ant-design/icons'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, getToken, setAuth, getUser } from '../api'

function AuthFrame({ children }) {
  return (
    <div className="aba-auth-shell">
      {/* Same centering rail as Login: aba-page-center → aba-page-shell */}
      <div className="aba-page-center">
        <div className="aba-page-shell aba-auth-stack">
          {/* Hero */}
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
              Confirm your email to secure your account.
            </Typography.Paragraph>
          </div>

          {/* Auth form — narrow centered Card (aba-page-shell-inner is-narrow) */}
          <div className="aba-page-shell-inner is-narrow aba-auth-form-wrap">
            <Card className="aba-auth-card aba-auth-form-card" bordered>
              {children}
            </Card>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function VerifyEmail() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const token = (params.get('token') || '').trim()
  const [status, setStatus] = useState(token ? 'loading' : 'missing')
  const [detail, setDetail] = useState('')

  useEffect(() => {
    if (!token) return
    let cancelled = false
    ;(async () => {
      try {
        const data = await api('/auth/verify-email', {
          method: 'POST',
          body: { token },
        })
        if (cancelled) return
        setStatus('ok')
        setDetail(data?.message || 'Email verified')
        // Refresh /auth/me if already logged in
        if (getToken()) {
          try {
            const me = await api('/auth/me')
            setAuth(getToken(), { ...getUser(), ...me })
          } catch {
            /* ignore */
          }
        }
      } catch (e) {
        if (cancelled) return
        setStatus('fail')
        setDetail(e?.message || 'Verification failed')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token])

  if (status === 'loading') {
    return (
      <AuthFrame>
        <div style={{ textAlign: 'center', padding: '12px 0 4px' }}>
          <Spin size="large" />
          <Typography.Title level={4} style={{ marginTop: 20, marginBottom: 8 }}>
            <MailOutlined style={{ marginRight: 8 }} />
            Verifying email
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            Please wait while we confirm your address…
          </Typography.Paragraph>
        </div>
      </AuthFrame>
    )
  }

  if (status === 'ok') {
    return (
      <AuthFrame>
        <Result
          status="success"
          title="Email verified"
          subTitle={detail || 'You can continue using the app.'}
          style={{ padding: '8px 0 0' }}
          extra={[
            <Button type="primary" key="app" size="large" block onClick={() => nav(getToken() ? '/' : '/login')}>
              {getToken() ? 'Go to app' : 'Sign in'}
            </Button>,
          ]}
        />
      </AuthFrame>
    )
  }

  return (
    <AuthFrame>
      <Result
        status="error"
        title={status === 'missing' ? 'Missing verification link' : 'Could not verify email'}
        subTitle={detail || 'Open the link from your email, or request a new verification email from Settings.'}
        style={{ padding: '8px 0 0' }}
        extra={[
          <Button type="primary" key="login" size="large" block onClick={() => nav('/login')}>
            Sign in
          </Button>,
          <div key="back" style={{ textAlign: 'center', width: '100%' }}>
            <Link to="/login">
              <Button type="link">Back to sign in</Button>
            </Link>
          </div>,
        ]}
      />
    </AuthFrame>
  )
}
