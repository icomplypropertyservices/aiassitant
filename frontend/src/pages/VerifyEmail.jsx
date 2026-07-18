import React, { useEffect, useState } from 'react'
import { Button, Card, Result, Spin, Typography, message } from 'antd'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, getToken, setAuth, getUser } from '../api'

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
      <div className="aba-auth-shell" style={{ display: 'grid', placeItems: 'center', minHeight: '70vh' }}>
        <Card style={{ maxWidth: 420, width: '100%', textAlign: 'center' }}>
          <Spin size="large" />
          <Typography.Paragraph style={{ marginTop: 16 }}>Verifying your email…</Typography.Paragraph>
        </Card>
      </div>
    )
  }

  if (status === 'ok') {
    return (
      <div className="aba-auth-shell" style={{ display: 'grid', placeItems: 'center', minHeight: '70vh' }}>
        <Result
          status="success"
          title="Email verified"
          subTitle={detail || 'You can continue using the app.'}
          extra={[
            <Button type="primary" key="app" onClick={() => nav(getToken() ? '/' : '/login')}>
              {getToken() ? 'Go to app' : 'Sign in'}
            </Button>,
          ]}
        />
      </div>
    )
  }

  return (
    <div className="aba-auth-shell" style={{ display: 'grid', placeItems: 'center', minHeight: '70vh' }}>
      <Result
        status="error"
        title={status === 'missing' ? 'Missing verification link' : 'Could not verify email'}
        subTitle={detail || 'Open the link from your email, or request a new verification email from Settings.'}
        extra={[
          <Button type="primary" key="login" onClick={() => nav('/login')}>
            Sign in
          </Button>,
          <Link key="home" to="/login">
            <Button>Back</Button>
          </Link>,
        ]}
      />
    </div>
  )
}
