import React, { useEffect, useState } from 'react'
import {
  Card, Form, Input, Button, Tabs, message, Typography, Tag, Space, Alert, Divider,
} from 'antd'
import {
  ThunderboltOutlined,
  TeamOutlined, SafetyCertificateOutlined, ArrowLeftOutlined, GoogleOutlined,
} from '@ant-design/icons'
import { useNavigate, Link, useSearchParams } from 'react-router-dom'
import { api, setAuth, getToken, getUser } from '../api'
import PlanCards from '../components/PlanCards'
import BrandLogo from '../components/BrandLogo'
import { goBay, goMarketing } from '../publicPaths'

const PASSWORD_PLACEHOLDER = 'At least 8 characters, include a letter and number'

function passwordRules(required = true) {
  return [
    ...(required ? [{ required: true, message: 'Password is required' }] : []),
    { min: 8, message: 'Password must be at least 8 characters' },
    {
      pattern: /[A-Za-z]/,
      message: 'Password must contain at least one letter',
    },
    {
      pattern: /[0-9]/,
      message: 'Password must contain at least one number',
    },
  ]
}

export default function Login() {
  const nav = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [loading, setLoading] = useState(false)
  const [googleLoading, setGoogleLoading] = useState(false)
  const [tab, setTab] = useState('login')
  const [plans, setPlans] = useState({})
  const [preorder, setPreorder] = useState(null)
  const [mode, setMode] = useState('auth') // auth | forgot | twofa
  const [forgotSent, setForgotSent] = useState(false)
  const [forgotForm] = Form.useForm()
  const [twofaEmail, setTwofaEmail] = useState('')
  const [twofaHint, setTwofaHint] = useState('')
  const [twofaForm] = Form.useForm()
  const [googleEnabled, setGoogleEnabled] = useState(true)

  // Handle Google OAuth return: ?oauth=success&api_key=aba_… or error
  useEffect(() => {
    const oauth = searchParams.get('oauth')
    if (!oauth) return
    if (oauth === 'success') {
      const apiKey = searchParams.get('api_key') || searchParams.get('token')
      const isNew = searchParams.get('is_new') === '1'
      const nextPath = searchParams.get('next')
      if (!apiKey) {
        message.error('Google sign-in returned no session key')
        setSearchParams({}, { replace: true })
        return
      }
      setLoading(true)
      // Clear sensitive params from URL before storing session
      setSearchParams({}, { replace: true })
      ;(async () => {
        try {
          setAuth(apiKey, { id: 0, email: '' })
          const me = await api('/auth/me')
          const user = me?.user || me
          if (!user?.id && !user?.email) {
            throw new Error('Could not load profile after Google sign-in')
          }
          setAuth(apiKey, user)
          message.success(isNew ? 'Account created with Google' : 'Signed in with Google')
          if (user.needs_subscription) {
            nav('/subscribe', { replace: true })
          } else if (nextPath && nextPath.startsWith('/')) {
            nav(nextPath, { replace: true })
          } else {
            nav('/', { replace: true })
          }
        } catch (e) {
          message.error(e?.message || 'Google sign-in failed')
        } finally {
          setLoading(false)
        }
      })()
      return
    }
    if (oauth === 'error') {
      const raw = searchParams.get('message') || 'Google sign-in failed'
      let friendly = raw
      try { friendly = decodeURIComponent(raw) } catch { /* keep */ }
      if (/redirect_uri/i.test(friendly)) {
        friendly = (
          'Google redirect URI mismatch — in Google Cloud Console add: '
          + 'https://aibusinessagent.xyz/api/auth/google/callback'
        )
      }
      message.error(friendly, 12)
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, setSearchParams, nav])

  useEffect(() => {
    const u = getUser()
    if (getToken() && u && u.id && !searchParams.get('oauth')) {
      nav(u.needs_subscription ? '/subscribe' : '/', { replace: true })
    }
    api('/billing/plans').then(setPlans).catch(() => {})
    api('/billing/preorder').then(setPreorder).catch(() => {
      setPreorder({
        active: false,
        live: true,
        launch_label: 'Live now',
        discount_percent: 0,
        early_access: false,
        cta_label: 'Create account',
        headline: 'Subscribe — live monthly plans',
        blurb: 'Live subscriptions at full list price. Pay monthly with Stripe or crypto.',
      })
    })
    api('/auth/oauth/providers')
      .then((r) => setGoogleEnabled(r?.google?.enabled !== false))
      .catch(() => setGoogleEnabled(true))
  }, [nav, searchParams])

  const preorderOn = Boolean(preorder?.active)

  const finishAuth = (data, isRegister) => {
    const sessionKey = data?.api_key || data?.token
    if (!sessionKey || !data?.user) {
      throw new Error('Login response missing API key — check API deployment')
    }
    setAuth(sessionKey, data.user)
    if (data.preferred_company_name) {
      localStorage.setItem('preferred_company_name', data.preferred_company_name)
    }
    message.success(
      isRegister
        ? (preorderOn ? 'Pre-order account created' : 'Account created')
        : 'Signed in',
    )
    if (data.user.needs_subscription) {
      nav('/subscribe', { replace: true })
    } else {
      nav('/', { replace: true })
    }
  }

  const submit = async (values) => {
    setLoading(true)
    try {
      const payload = {
        email: (values.email || '').trim(),
        password: values.password,
      }
      if (tab === 'register') {
        payload.name = (values.name || '').trim()
        payload.company_name = (values.company_name || '').trim()
      }
      const data = await api(`/auth/${tab === 'login' ? 'login' : 'register'}`, {
        method: 'POST',
        body: payload,
      })
      if (tab === 'login' && data?.requires_2fa) {
        setTwofaEmail(payload.email)
        setTwofaHint(data.email_hint || payload.email)
        setMode('twofa')
        twofaForm.resetFields()
        if (data.dev_otp_code) {
          message.info(`Dev code: ${data.dev_otp_code}`)
        } else {
          message.success(data.message || 'Check your email for a verification code')
        }
        return
      }
      finishAuth(data, tab === 'register')
    } catch (e) {
      message.error(e?.message || 'Sign-in failed')
    } finally {
      setLoading(false)
    }
  }

  const submitTwofa = async (values) => {
    setLoading(true)
    try {
      const data = await api('/auth/2fa/login/verify', {
        method: 'POST',
        body: {
          email: twofaEmail,
          code: String(values.code || '').trim(),
        },
      })
      finishAuth(data, false)
    } catch (e) {
      message.error(e?.message || 'Invalid code')
    } finally {
      setLoading(false)
    }
  }

  const resendTwofa = async () => {
    setLoading(true)
    try {
      const r = await api('/auth/2fa/login/resend', {
        method: 'POST',
        body: { email: twofaEmail },
      })
      if (r.dev_otp_code) message.info(`Dev code: ${r.dev_otp_code}`)
      else message.success('If a code was pending, a new one was sent')
    } catch (e) {
      message.error(e?.message || 'Could not resend')
    } finally {
      setLoading(false)
    }
  }

  const submitForgot = async (values) => {
    setLoading(true)
    try {
      const r = await api('/auth/forgot-password', {
        method: 'POST',
        body: { email: (values.email || '').trim() },
      })
      setForgotSent(true)
      if (r?.dev_otp_code) {
        message.info(`Dev code: ${r.dev_otp_code}`)
      }
    } catch (e) {
      // Always show a generic success message to avoid email enumeration
      setForgotSent(true)
    } finally {
      setLoading(false)
    }
  }

  const startGoogle = async () => {
    setGoogleLoading(true)
    try {
      const intent = tab === 'register' ? 'register' : 'login'
      const r = await api(`/auth/google/start?intent=${encodeURIComponent(intent)}`)
      if (r?.authorize_url) {
        window.location.href = r.authorize_url
        return
      }
      message.error(r?.message || 'Google sign-in is not available')
    } catch (e) {
      const msg = e?.message || String(e)
      if (/redirect_uri|not configured|503/i.test(msg)) {
        message.error(
          msg.includes('redirect')
            ? msg
            : 'Google sign-in is not configured on the server yet.',
          10,
        )
      } else {
        message.error(msg)
      }
    } finally {
      setGoogleLoading(false)
    }
  }

  const planList = Object.entries(plans)
    .filter(([key, p]) => p.public !== false && key !== 'pay_as_you_go' && key !== 'none')
    .sort((a, b) => (a[1].sort ?? 50) - (b[1].sort ?? 50))

  return (
    <div className="aba-auth-shell">
      {/* Same centering rail as AppLayout: aba-page-center → aba-page-shell */}
      <div className="aba-page-center">
        <div className="aba-page-shell aba-auth-stack">
          {/* Hero */}
          <div className="aba-auth-hero" style={{ marginBottom: 28, width: '100%' }}>
            <div className="aba-auth-logo">
              <BrandLogo size="lg" alt="AI Business Assistant" />
            </div>
            <Typography.Title level={2} style={{ color: '#fff', margin: '0 0 8px', letterSpacing: '-0.03em' }}>
              AI Business Assistant
            </Typography.Title>
            <Typography.Paragraph style={{ color: 'rgba(255,255,255,0.88)', maxWidth: 560, margin: '0 auto 14px' }}>
              Run companies, projects and AI agents in one workspace — with a clear token meter
              and fair public pricing.
            </Typography.Paragraph>
            {preorderOn && (
              <Alert
                type="success"
                showIcon
                className="aba-auth-hero-alert"
                message={preorder?.headline || 'Pre-order — 10% off + early access'}
                description={
                  preorder?.blurb
                  || 'Launch 27 July 2026. Pre-order now for 10% off paid plans and early access. Pay with Stripe or crypto.'
                }
              />
            )}
            {import.meta.env.VITE_SANDBOX === '1' && (
              <Tag color="gold" style={{ marginBottom: 8 }}>Sandbox build · test payments only</Tag>
            )}
            <Space wrap style={{ justifyContent: 'center' }}>
              {preorderOn && (
                <span className="aba-feature-pill">
                  <ThunderboltOutlined /> Launch {preorder?.launch_label || '27 July 2026'}
                </span>
              )}
              <span className="aba-feature-pill"><TeamOutlined /> Company → Projects → Tasks</span>
              <span className="aba-feature-pill"><ThunderboltOutlined /> Live token meter</span>
              <span className="aba-feature-pill"><SafetyCertificateOutlined /> Stripe + crypto</span>
            </Space>
            <Space wrap style={{ justifyContent: 'center', marginTop: 14 }}>
              <Button
                type="link"
                style={{ color: 'rgba(255,255,255,0.92)' }}
                onClick={() => goMarketing('/')}
              >
                ← Website
              </Button>
              <Button
                type="link"
                style={{ color: 'rgba(255,255,255,0.92)' }}
                onClick={() => goBay('/browse')}
              >
                AgentBay →
              </Button>
            </Space>
          </div>

          {/* Auth form — narrow centered Ant Design Card */}
          <div className="aba-page-shell-inner is-narrow aba-auth-form-wrap">
            <Card className="aba-auth-card aba-auth-form-card" bordered>
              {mode === 'twofa' ? (
                <>
                  <Button
                    type="link"
                    icon={<ArrowLeftOutlined />}
                    onClick={() => { setMode('auth'); twofaForm.resetFields() }}
                    style={{ paddingLeft: 0, marginBottom: 8 }}
                  >
                    Back to sign in
                  </Button>
                  <Typography.Title level={4} className="aba-auth-form-title">
                    Email verification
                  </Typography.Title>
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginBottom: 16 }}
                    message="Two-factor authentication"
                    description={`We sent a 6-digit code to ${twofaHint || 'your email'}. Enter it below to finish signing in.`}
                  />
                  <Form form={twofaForm} layout="vertical" onFinish={submitTwofa} requiredMark={false} size="large">
                    <Form.Item
                      name="code"
                      label="Verification code"
                      rules={[
                        { required: true, message: 'Enter the code from your email' },
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
                    <Button type="primary" htmlType="submit" block size="large" loading={loading}>
                      Verify & sign in
                    </Button>
                    <Button type="link" block onClick={resendTwofa} disabled={loading} style={{ marginTop: 8 }}>
                      Resend code
                    </Button>
                  </Form>
                </>
              ) : mode === 'forgot' ? (
                <>
                  <Button
                    type="link"
                    icon={<ArrowLeftOutlined />}
                    onClick={() => { setMode('auth'); setForgotSent(false); forgotForm.resetFields() }}
                    style={{ paddingLeft: 0, marginBottom: 8 }}
                  >
                    Back to sign in
                  </Button>
                  <Typography.Title level={4} className="aba-auth-form-title">
                    Forgot password
                  </Typography.Title>
                  {forgotSent ? (
                    <Alert
                      type="success"
                      showIcon
                      message="Check your email"
                      description="If an account exists, we sent a reset link and a 6-digit code. Open the link or go to Reset password and enter your email + code."
                      action={(
                        <Button size="small" type="primary" onClick={() => nav('/reset-password')}>
                          Enter code
                        </Button>
                      )}
                    />
                  ) : (
                    <Form form={forgotForm} layout="vertical" onFinish={submitForgot} requiredMark={false} size="large">
                      <Form.Item name="email" label="Email" rules={[{ required: true, type: 'email' }]}>
                        <Input placeholder="you@business.com" autoComplete="email" />
                      </Form.Item>
                      <Button type="primary" htmlType="submit" block size="large" loading={loading}>
                        Email me a reset link & code
                      </Button>
                    </Form>
                  )}
                </>
              ) : (
                <>
                  <Tabs
                    activeKey={tab}
                    onChange={setTab}
                    centered
                    items={[
                      { key: 'login', label: 'Sign in' },
                      { key: 'register', label: preorderOn ? 'Pre-order' : 'Create account' },
                    ]}
                  />
                  {tab === 'register' && preorderOn && (
                    <Alert
                      type="info"
                      showIcon
                      style={{ marginBottom: 12 }}
                      message={`${preorder?.discount_percent || 10}% off · early access`}
                      description={`Reserve your plan before launch (${preorder?.launch_label || '27 July 2026'}). Pay by Stripe card or crypto.`}
                    />
                  )}
                  {googleEnabled && (
                    <>
                      <Button
                        block
                        size="large"
                        icon={<GoogleOutlined />}
                        loading={googleLoading}
                        onClick={startGoogle}
                        style={{
                          marginBottom: 4,
                          height: 44,
                          fontWeight: 600,
                          borderColor: 'rgba(0,0,0,0.15)',
                        }}
                      >
                        {tab === 'login' ? 'Sign in with Google' : 'Sign up with Google'}
                      </Button>
                      <Divider plain style={{ margin: '14px 0 12px', fontSize: 12 }}>
                        or continue with email
                      </Divider>
                    </>
                  )}
                  <Form layout="vertical" onFinish={submit} requiredMark={false} size="large">
                    {tab === 'register' && (
                      <>
                        <Form.Item name="name" label="Your name">
                          <Input placeholder="Jane Smith" autoComplete="name" />
                        </Form.Item>
                        <Form.Item name="company_name" label="Company name">
                          <Input placeholder="Acme Electrical Ltd" autoComplete="organization" />
                        </Form.Item>
                      </>
                    )}
                    <Form.Item name="email" label="Email" rules={[{ required: true, type: 'email' }]}>
                      <Input placeholder="you@business.com" autoComplete="email" />
                    </Form.Item>
                    <Form.Item
                      name="password"
                      label="Password"
                      rules={
                        tab === 'register'
                          ? passwordRules(true)
                          : [{ required: true, message: 'Password is required' }, { min: 8, message: 'Password must be at least 8 characters' }]
                      }
                      extra={tab === 'register' ? 'Min 8 characters, include a letter and a number' : undefined}
                    >
                      <Input.Password
                        placeholder={PASSWORD_PLACEHOLDER}
                        autoComplete={tab === 'login' ? 'current-password' : 'new-password'}
                      />
                    </Form.Item>
                    <Button type="primary" htmlType="submit" block size="large" loading={loading}>
                      {tab === 'login'
                        ? 'Sign in'
                        : (preorderOn ? 'Pre-order & choose plan' : 'Create account & choose plan')}
                    </Button>
                  </Form>
                  {tab === 'login' && (
                    <div className="aba-auth-form-footer">
                      <Button type="link" onClick={() => { setMode('forgot'); setForgotSent(false) }}>
                        Forgot password?
                      </Button>
                    </div>
                  )}
                  <Typography.Paragraph type="secondary" className="aba-auth-form-note">
                    {preorderOn
                      ? 'After pre-order, pick a plan — 10% off until launch. Stripe card or crypto (ETH / SOL / BTC / XRP).'
                      : 'After sign-up, choose a plan. Live monthly subscriptions via Stripe card or crypto (ETH / SOL / XRP).'}
                  </Typography.Paragraph>
                </>
              )}
            </Card>
          </div>

          {/* Plans — centered Ant Design Card with compact tier cards */}
          <section className="aba-auth-plans">
            <Card
              className="aba-auth-card aba-soft-card aba-auth-plans-card"
              title={
                <div className="aba-auth-plans-head">
                  <span className="aba-auth-plans-card-title">
                    {preorderOn ? 'Pre-order plans' : 'Live subscription plans'}
                  </span>
                  <Typography.Text type="secondary" className="aba-auth-plans-sub">
                    {preorderOn
                      ? '10% off · early access · launch 27 July 2026'
                      : 'Monthly at list price · Stripe or crypto'}
                  </Typography.Text>
                </div>
              }
              extra={<Link to="/subscribe">Full plans →</Link>}
              styles={{
                header: { borderBottom: '1px solid var(--aba-border)' },
                body: { padding: '16px 16px 12px' },
              }}
            >
              <PlanCards
                plans={planList}
                preorderOn={preorderOn}
                compact
              />
              <div className="aba-auth-plans-foot">
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {preorderOn
                    ? 'Create an account above to reserve a plan before launch.'
                    : 'Sign up above to choose a plan at checkout.'}
                </Typography.Text>
              </div>
            </Card>
          </section>
        </div>
      </div>
    </div>
  )
}
