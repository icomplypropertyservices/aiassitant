import React, { useEffect, useState } from 'react'
import {
  Card, Row, Col, Button, Typography, Tag, List, Input, Space, message, Alert,
} from 'antd'
import { CheckOutlined, RobotOutlined, CreditCardOutlined, WalletOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, getToken, getUser, setAuth, clearAuth, IS_NATIVE } from '../api'
import CryptoPay from '../components/CryptoPay'

export default function Subscribe() {
  const nav = useNavigate()
  const [plans, setPlans] = useState({})
  const [busy, setBusy] = useState(null)
  const [cryptoOpen, setCryptoOpen] = useState(false)
  const [cryptoPlan, setCryptoPlan] = useState(null)
  const [cryptoEnabled, setCryptoEnabled] = useState(false)
  const [payOpts, setPayOpts] = useState(null)
  const [companyName, setCompanyName] = useState(
    localStorage.getItem('preferred_company_name') || '',
  )
  const user = getUser()

  useEffect(() => {
    if (!getToken()) {
      nav('/login', { replace: true })
      return
    }
    if (user && !user.needs_subscription && user.subscription_active) {
      nav('/', { replace: true })
      return
    }
    api('/billing/plans').then(setPlans).catch(() => {})
    api('/billing/crypto/options')
      .then((o) => setCryptoEnabled(Boolean(o.enabled && (o.chains || []).length)))
      .catch(() => setCryptoEnabled(false))
    api('/billing/payment-options').then(setPayOpts).catch(() => {})
    const q = new URLSearchParams(window.location.search)
    if (q.get('checkout') === 'success' && q.get('session_id')) {
      api(`/billing/checkout/confirm?session_id=${encodeURIComponent(q.get('session_id'))}`, { method: 'POST' })
        .then(async () => {
          message.success('Payment confirmed')
          const me = await api('/auth/me')
          setAuth(getToken(), me)
          nav('/')
        })
        .catch((e) => message.error(e.message))
    }
  }, [])

  const afterPaid = async (planKey) => {
    const me = await api('/auth/me')
    setAuth(getToken(), me)
    localStorage.removeItem('preferred_company_name')
    message.success(`You're on ${me.plan_name || me.plan || planKey}`)
    nav('/')
  }

  const choose = async (planKey) => {
    if (IS_NATIVE) {
      message.info('Complete subscription on the web for your account, then return to the app.')
      window.open('https://aiassitant-nu.vercel.app/subscribe', '_blank')
      return
    }
    setBusy(planKey)
    try {
      const r = await api('/billing/plan', {
        method: 'POST',
        body: { plan: planKey, company_name: companyName || undefined },
      })
      if (r.checkout_url) {
        window.location.href = r.checkout_url
        return
      }
      await afterPaid(planKey)
    } catch (e) {
      if (String(e.message || '').toLowerCase().includes('crypto') || e.status === 402) {
        setCryptoPlan(planKey)
        setCryptoOpen(true)
      } else {
        message.error(e.message)
      }
    } finally {
      setBusy(null)
    }
  }

  const payCrypto = (planKey) => {
    if (IS_NATIVE) {
      window.open('https://aiassitant-nu.vercel.app/subscribe', '_blank')
      return
    }
    setCryptoPlan(planKey)
    setCryptoOpen(true)
  }

  const entries = Object.entries(plans)

  return (
    <div className="aba-auth-shell">
      <div style={{ maxWidth: 1140, margin: '0 auto' }}>
        <div className="aba-hero" style={{ textAlign: 'center', marginBottom: 28 }}>
          <div
            style={{
              width: 48,
              height: 48,
              borderRadius: 14,
              margin: '0 auto 10px',
              display: 'grid',
              placeItems: 'center',
              background: 'rgba(255,255,255,0.16)',
              fontSize: 22,
            }}
          >
            <RobotOutlined />
          </div>
          <Typography.Title level={2} style={{ margin: '0 0 6px', letterSpacing: '-0.03em' }}>
            Choose your subscription
          </Typography.Title>
          <Typography.Paragraph style={{ margin: '0 auto 12px' }}>
            Signed in as <strong>{user?.email}</strong>. Unlock companies, projects, tasks and AI agents.
          </Typography.Paragraph>
          <Space wrap style={{ justifyContent: 'center' }}>
            <span className="aba-feature-pill">
              <CreditCardOutlined />{' '}
              {payOpts?.stripe?.sandbox ? 'Card (Stripe test)' : 'Card (Stripe)'}
            </span>
            <span className="aba-feature-pill"><WalletOutlined /> Crypto ETH · SOL · XRP</span>
            {payOpts?.stripe?.enabled && <span className="aba-feature-pill">Stripe ready</span>}
            {cryptoEnabled && <span className="aba-feature-pill">Crypto ready</span>}
          </Space>
          <div style={{ marginTop: 16 }}>
            <Space wrap style={{ justifyContent: 'center' }}>
              <Typography.Text style={{ color: 'rgba(255,255,255,0.9)' }}>First company name</Typography.Text>
              <Input
                style={{ width: 280, borderRadius: 10 }}
                placeholder="My company"
                value={companyName}
                onChange={e => setCompanyName(e.target.value)}
                size="large"
              />
            </Space>
          </div>
        </div>

        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 20, borderRadius: 12 }}
          message="Token meter is always visible"
          description="Each plan includes a monthly token pool for VPS/Qwen models. Premium Claude/Grok and overage draw from your credit wallet. Top up anytime — card or crypto."
        />

        <Row gutter={[16, 16]}>
          {entries.map(([key, p]) => (
            <Col xs={24} sm={12} lg={8} xl={6} key={key}>
              <Card
                hoverable
                className={`aba-plan-card${p.highlight ? ' is-highlight' : ''}`}
                style={{ borderRadius: 14 }}
                title={
                  <Space>
                    {p.name}
                    {p.highlight && <Tag color="blue">Popular</Tag>}
                  </Space>
                }
                extra={
                  <Typography.Title level={4} style={{ margin: 0, letterSpacing: '-0.03em' }}>
                    {p.price ? `$${p.price}` : '$0'}
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>/mo</Typography.Text>
                  </Typography.Title>
                }
              >
                <Typography.Paragraph type="secondary" style={{ minHeight: 44 }}>
                  {p.blurb}
                </Typography.Paragraph>
                <Tag color="processing" style={{ marginBottom: 12 }}>
                  {(p.tokens_included || 0).toLocaleString()} tokens / month
                </Tag>
                <List
                  size="small"
                  dataSource={p.features || []}
                  renderItem={f => (
                    <List.Item style={{ padding: '4px 0', border: 'none' }}>
                      <CheckOutlined style={{ color: '#16a34a', marginRight: 8 }} /> {f}
                    </List.Item>
                  )}
                />
                <Button
                  type={p.highlight ? 'primary' : 'default'}
                  block
                  size="large"
                  style={{ marginTop: 12 }}
                  loading={busy === key}
                  onClick={() => choose(key)}
                >
                  {p.price
                    ? `Subscribe with card${payOpts?.stripe?.sandbox ? ' (test)' : ''}`
                    : 'Start free'}
                </Button>
                {p.price > 0 && (
                  <Button
                    block
                    size="large"
                    style={{ marginTop: 8 }}
                    icon={<WalletOutlined />}
                    onClick={() => payCrypto(key)}
                  >
                    Pay with crypto
                  </Button>
                )}
              </Card>
            </Col>
          ))}
        </Row>

        <div style={{ textAlign: 'center', marginTop: 28 }}>
          <Button type="link" onClick={() => { clearAuth(); nav('/login') }}>
            Sign out
          </Button>
        </div>
      </div>

      <CryptoPay
        open={cryptoOpen}
        onClose={() => setCryptoOpen(false)}
        kind="plan"
        plan={cryptoPlan}
        companyName={companyName}
        onPaid={() => afterPaid(cryptoPlan)}
      />
    </div>
  )
}
