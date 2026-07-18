import React, { useEffect, useState } from 'react'
import {
  Card, Form, Input, Button, Tabs, message, Typography, Row, Col, Tag, List, Space, Alert,
} from 'antd'
import {
  RobotOutlined, CheckOutlined, ThunderboltOutlined,
  TeamOutlined, SafetyCertificateOutlined, ArrowLeftOutlined,
} from '@ant-design/icons'
import { useNavigate, Link } from 'react-router-dom'
import { api, setAuth, getToken, getUser } from '../api'

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
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState('login')
  const [plans, setPlans] = useState({})
  const [preorder, setPreorder] = useState(null)
  const [mode, setMode] = useState('auth') // auth | forgot
  const [forgotSent, setForgotSent] = useState(false)
  const [forgotForm] = Form.useForm()

  useEffect(() => {
    const u = getUser()
    if (getToken() && u) {
      nav(u.needs_subscription ? '/subscribe' : '/', { replace: true })
    }
    api('/billing/plans').then(setPlans).catch(() => {})
    api('/billing/preorder').then(setPreorder).catch(() => {
      setPreorder({
        active: true,
        launch_label: '27 July 2026',
        discount_percent: 10,
        early_access: true,
        cta_label: 'Pre-order',
        headline: 'Pre-order now — 10% off + early access',
        blurb: 'Launch 27 July 2026. Pre-orders get 10% off and early access.',
      })
    })
  }, [])

  const preorderOn = preorder?.active !== false

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
      if (!data?.token || !data?.user) {
        throw new Error('Login response missing token — check API deployment')
      }
      setAuth(data.token, data.user)
      if (data.preferred_company_name) {
        localStorage.setItem('preferred_company_name', data.preferred_company_name)
      }
      message.success(
        tab === 'login'
          ? 'Signed in'
          : (preorderOn ? 'Pre-order account created' : 'Account created'),
      )
      if (data.user.needs_subscription) {
        nav('/subscribe', { replace: true })
      } else {
        nav('/', { replace: true })
      }
    } catch (e) {
      message.error(e?.message || 'Sign-in failed')
    } finally {
      setLoading(false)
    }
  }

  const submitForgot = async (values) => {
    setLoading(true)
    try {
      await api('/auth/forgot-password', {
        method: 'POST',
        body: { email: (values.email || '').trim() },
      })
      setForgotSent(true)
    } catch (e) {
      // Always show a generic success message to avoid email enumeration
      setForgotSent(true)
    } finally {
      setLoading(false)
    }
  }

  const planList = Object.entries(plans).filter(
    ([key, p]) => p.public !== false && key !== 'pay_as_you_go' && key !== 'none',
  )

  const unit = (n, singular) => `${n} ${singular}${Number(n) === 1 ? '' : 's'}`

  return (
    <div className="aba-auth-shell">
      <div style={{ maxWidth: 1120, margin: '0 auto' }}>
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: 16,
              margin: '0 auto 12px',
              display: 'grid',
              placeItems: 'center',
              background: 'linear-gradient(135deg,#3b82f6,#1d4ed8)',
              boxShadow: '0 8px 24px rgba(37,99,235,0.35)',
              color: '#fff',
              fontSize: 26,
            }}
          >
            <RobotOutlined />
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
              style={{ maxWidth: 560, margin: '0 auto 14px', textAlign: 'left' }}
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
        </div>

        <Row gutter={[24, 24]} align="stretch">
          <Col xs={24} md={10}>
            <Card className="aba-auth-card" style={{ borderRadius: 16 }}>
              {mode === 'forgot' ? (
                <>
                  <Button
                    type="link"
                    icon={<ArrowLeftOutlined />}
                    onClick={() => { setMode('auth'); setForgotSent(false); forgotForm.resetFields() }}
                    style={{ paddingLeft: 0, marginBottom: 8 }}
                  >
                    Back to sign in
                  </Button>
                  <Typography.Title level={4} style={{ marginTop: 0 }}>Forgot password</Typography.Title>
                  {forgotSent ? (
                    <Alert
                      type="success"
                      showIcon
                      message="If an account exists for that email, you will receive reset instructions shortly."
                    />
                  ) : (
                    <Form form={forgotForm} layout="vertical" onFinish={submitForgot} requiredMark={false} size="large">
                      <Form.Item name="email" label="Email" rules={[{ required: true, type: 'email' }]}>
                        <Input placeholder="you@business.com" autoComplete="email" />
                      </Form.Item>
                      <Button type="primary" htmlType="submit" block size="large" loading={loading}>
                        Send reset link
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
                    <div style={{ textAlign: 'center', marginTop: 12 }}>
                      <Button type="link" onClick={() => { setMode('forgot'); setForgotSent(false) }}>
                        Forgot password?
                      </Button>
                    </div>
                  )}
                  <Typography.Paragraph type="secondary" style={{ marginTop: 16, marginBottom: 0, fontSize: 12, textAlign: 'center' }}>
                    {preorderOn
                      ? 'After pre-order, pick a plan — 10% off until launch. Stripe card or crypto (ETH / SOL / BTC / XRP).'
                      : 'After sign-up, choose a plan. Pay with card or crypto (ETH / SOL / XRP).'}
                  </Typography.Paragraph>
                </>
              )}
            </Card>
          </Col>

          <Col xs={24} md={14}>
            <Card
              className="aba-auth-card aba-soft-card"
              title="Plans"
              extra={<Link to="/subscribe">View plans →</Link>}
              style={{ borderRadius: 16, height: '100%' }}
            >
              <List
                dataSource={planList}
                locale={{ emptyText: 'Loading plans…' }}
                split
                renderItem={([key, p]) => (
                  <List.Item style={{ padding: '14px 0' }}>
                    <List.Item.Meta
                      title={
                        <Space wrap size={6}>
                          <Typography.Text strong>{p.name}</Typography.Text>
                          {p.highlight && <Tag color="blue">Popular</Tag>}
                          {preorderOn && p.price > 0 && (
                            <Tag color="gold">{p.preorder_discount_percent || 10}% off</Tag>
                          )}
                          <Tag color={p.price ? 'geekblue' : 'green'}>
                            {p.price
                              ? (preorderOn && p.price_checkout != null
                                ? <>
                                    <span style={{ textDecoration: 'line-through', opacity: 0.65, marginRight: 6 }}>
                                      ${p.price}
                                    </span>
                                    ${Number(p.price_checkout).toFixed(p.price_checkout % 1 ? 2 : 0)}/mo
                                  </>
                                : `$${p.price}/mo`)
                              : 'Free'}
                          </Tag>
                        </Space>
                      }
                      description={
                        <div>
                          <div style={{ marginBottom: 4, color: '#475569' }}>{p.blurb}</div>
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            {(p.tokens_included || 0).toLocaleString()} tokens/mo
                            {' · '}{unit(p.companies, 'company')}
                            {' · '}{unit(p.projects, 'project')}
                            {' · '}{unit(p.agents, 'agent')}
                          </Typography.Text>
                        </div>
                      }
                    />
                    <div style={{ minWidth: 160 }}>
                      {(p.features || []).slice(0, 2).map(f => (
                        <div key={f} style={{ fontSize: 12, color: '#64748b', lineHeight: 1.55 }}>
                          <CheckOutlined style={{ color: '#16a34a', marginRight: 6 }} />{f}
                        </div>
                      ))}
                    </div>
                  </List.Item>
                )}
              />
            </Card>
          </Col>
        </Row>
      </div>
    </div>
  )
}
