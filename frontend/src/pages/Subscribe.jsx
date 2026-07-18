import React, { useEffect, useState, useMemo } from 'react'
import {
  Card, Row, Col, Button, Typography, Tag, List, Input, Space, message, Alert,
} from 'antd'
import {
  CheckOutlined, RobotOutlined, CreditCardOutlined, WalletOutlined, ArrowUpOutlined, CrownOutlined,
} from '@ant-design/icons'
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
  const [preorder, setPreorder] = useState(null)
  const [companyName, setCompanyName] = useState(
    localStorage.getItem('preferred_company_name') || '',
  )
  // Default to pre-order messaging until API says the window closed
  const preorderOn = preorder == null ? true : Boolean(preorder.active)
  const user = getUser()
  const expiresAt = user?.subscription_expires_at || null
  const trialEnded = Boolean(user?.needs_subscription)
  const expiresMeta = useMemo(() => {
    if (!expiresAt) return null
    const d = new Date(expiresAt)
    if (Number.isNaN(d.getTime())) return null
    const days = Math.ceil((d.getTime() - Date.now()) / 86400000)
    return { date: d, days }
  }, [expiresAt])

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
    api('/billing/payment-options').then((o) => {
      setPayOpts(o)
      if (o?.preorder) setPreorder(o.preorder)
    }).catch(() => {})
    api('/billing/preorder').then(setPreorder).catch(() => {
      setPreorder({
        active: true,
        launch_label: '27 July 2026',
        discount_percent: 10,
        early_access: true,
        headline: 'Pre-order now — 10% off + early access',
      })
    })
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

  const entries = useMemo(() => {
    const e = Object.entries(plans)
    e.sort((a, b) => (a[1].sort ?? 50) - (b[1].sort ?? 50))
    return e
  }, [plans])

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
            {trialEnded
              ? 'Pick a paid plan to continue'
              : (preorderOn ? (preorder?.headline || 'Pre-order your plan') : 'Choose your plan')}
          </Typography.Title>
          <Typography.Paragraph style={{ margin: '0 auto 12px', maxWidth: 560 }}>
            Signed in as <strong>{user?.email}</strong>.
            {trialEnded
              ? ' Your free trial has ended — choose Starter or higher to keep agents, tokens, and workspace access.'
              : preorderOn
                ? ` Pre-order before launch (${preorder?.launch_label || '27 July 2026'}) for ${preorder?.discount_percent || 10}% off + early access. Pay with Stripe or crypto.`
                : ' Start free, then upgrade when you need more agents and tokens. Managed models stay simple: Fast, Quality, Reasoning, Large.'}
          </Typography.Paragraph>
          {expiresMeta && (
            <div style={{ marginBottom: 12 }}>
              {expiresMeta.days < 0 || trialEnded ? (
                <Tag color="error">
                  Trial / access expired {expiresMeta.date.toLocaleDateString()}
                </Tag>
              ) : expiresMeta.days === 0 ? (
                <Tag color="warning">Expires today · {expiresMeta.date.toLocaleString()}</Tag>
              ) : (
                <Tag color={expiresMeta.days <= 3 ? 'warning' : 'blue'}>
                  Access through {expiresMeta.date.toLocaleDateString()}
                  {expiresMeta.days <= 14 ? ` · ${expiresMeta.days} day${expiresMeta.days === 1 ? '' : 's'} left` : ''}
                </Tag>
              )}
            </div>
          )}
          <Space wrap style={{ justifyContent: 'center' }}>
            {preorderOn && (
              <span className="aba-feature-pill">
                <CrownOutlined /> {preorder?.discount_percent || 10}% off pre-order
              </span>
            )}
            <span className="aba-feature-pill">
              <CreditCardOutlined />{' '}
              {payOpts?.stripe?.sandbox ? 'Card (Stripe test)' : 'Card (Stripe)'}
              {payOpts?.stripe?.ready === false ? ' · setup pending' : ''}
            </span>
            <span className="aba-feature-pill">
              <WalletOutlined /> Crypto ETH · SOL · BTC · XRP
              {payOpts?.crypto?.ready === false && !cryptoEnabled ? ' · setup pending' : ''}
            </span>
            <span className="aba-feature-pill"><CrownOutlined /> Early access for pre-orders</span>
          </Space>
          <div style={{ marginTop: 16 }}>
            <Space wrap style={{ justifyContent: 'center' }}>
              <Typography.Text style={{ color: 'rgba(255,255,255,0.9)' }}>First company name</Typography.Text>
              <Input
                style={{ width: 280, borderRadius: 10 }}
                placeholder="My company"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                size="large"
              />
            </Space>
          </div>
        </div>

        {trialEnded && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16, borderRadius: 12 }}
            message="Subscription required"
            description={
              <>
                Free trial access is no longer active
                {expiresMeta ? ` (ended ${expiresMeta.date.toLocaleDateString()})` : ''}.
                Select a paid plan below (card or crypto) to restore full access. Trial free tier is
                not available again after expiry.
              </>
            }
          />
        )}

        {preorderOn && (
          <Alert
            type="success"
            showIcon
            style={{ marginBottom: 16, borderRadius: 12 }}
            message={`Pre-order open · launch ${preorder?.launch_label || '27 July 2026'}`}
            description={
              <>
                Pre-orders get <strong>{preorder?.discount_percent || 10}% off</strong> paid plans and{' '}
                <strong>early access</strong> before public open. Checkout is ready for{' '}
                <strong>Stripe (card)</strong> and <strong>crypto (ETH / SOL / BTC / XRP)</strong>.
                Grok is API-only; Claude and VPS small models are marked Coming soon.
              </>
            }
          />
        )}

        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 20, borderRadius: 12 }}
          message="How tokens work"
          description={
            <>
              Each plan includes a monthly token pool for managed chat. When the pool is used, usage
              draws from your credit wallet at transparent rates. Image/video always use the wallet.
              You can upgrade or top up anytime from Billing.
            </>
          }
        />

        <Row gutter={[16, 16]}>
          {entries.map(([key, p]) => (
            <Col xs={24} sm={12} lg={6} key={key}>
              <Card
                hoverable
                className={`aba-plan-card${p.highlight ? ' is-highlight' : ''}`}
                style={{
                  borderRadius: 14,
                  height: '100%',
                  border: p.highlight ? '2px solid #1677ff' : undefined,
                }}
                title={
                  <Space wrap>
                    {p.name}
                    {p.badge && <Tag color={p.highlight ? 'blue' : 'default'}>{p.badge}</Tag>}
                  </Space>
                }
                extra={
                  <Typography.Title level={4} style={{ margin: 0, letterSpacing: '-0.03em' }}>
                    {p.price ? (
                      preorderOn && p.price_checkout != null && p.price_checkout < p.price ? (
                        <>
                          <Typography.Text delete type="secondary" style={{ fontSize: 14, marginRight: 6 }}>
                            ${p.price}
                          </Typography.Text>
                          ${Number(p.price_checkout).toFixed(p.price_checkout % 1 ? 2 : 0)}
                        </>
                      ) : `$${p.price}`
                    ) : '$0'}
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>/mo</Typography.Text>
                  </Typography.Title>
                }
              >
                <Typography.Paragraph type="secondary" style={{ minHeight: 48, fontSize: 13 }}>
                  {p.blurb}
                </Typography.Paragraph>
                {preorderOn && p.price > 0 && (
                  <Tag color="gold" style={{ marginBottom: 8 }}>
                    Pre-order · {p.preorder_discount_percent || 10}% off · early access
                  </Tag>
                )}
                <Tag color="processing" style={{ marginBottom: 8 }}>
                  {(p.tokens_included || 0).toLocaleString()} tokens / month
                </Tag>
                {p.value_line && (
                  <div style={{ marginBottom: 10, fontSize: 12, color: '#16a34a' }}>
                    {p.value_line}
                  </div>
                )}
                <List
                  size="small"
                  dataSource={p.features || []}
                  renderItem={(f) => (
                    <List.Item style={{ padding: '4px 0', border: 'none', fontSize: 13 }}>
                      <CheckOutlined style={{ color: '#16a34a', marginRight: 8 }} /> {f}
                    </List.Item>
                  )}
                />
                {(p.teasers || []).slice(0, 1).map((t) => (
                  <Alert
                    key={t}
                    type="info"
                    showIcon={false}
                    style={{ marginTop: 8, marginBottom: 4, fontSize: 12 }}
                    message={t}
                  />
                ))}
                <Button
                  type={p.highlight ? 'primary' : 'default'}
                  block
                  size="large"
                  style={{ marginTop: 12 }}
                  loading={busy === key}
                  icon={p.price > 0 ? <ArrowUpOutlined /> : null}
                  onClick={() => choose(key)}
                >
                  {p.price
                    ? `${p.cta || (preorderOn ? `Pre-order ${p.name}` : `Get ${p.name}`)} · $${
                        preorderOn && p.price_checkout != null ? Number(p.price_checkout).toFixed(p.price_checkout % 1 ? 2 : 0) : p.price
                      }/mo${payOpts?.stripe?.sandbox ? ' (test)' : ''}`
                    : (p.cta || 'Start free')}
                </Button>
                {p.price > 0 && (
                  <Button
                    block
                    size="large"
                    style={{ marginTop: 8 }}
                    icon={<WalletOutlined />}
                    onClick={() => payCrypto(key)}
                  >
                    {preorderOn ? 'Pre-order with crypto' : 'Pay with crypto'}
                  </Button>
                )}
                {p.upgrade_teaser && p.next_plan && (
                  <Typography.Paragraph type="secondary" style={{ marginTop: 10, marginBottom: 0, fontSize: 11 }}>
                    {p.upgrade_teaser}
                  </Typography.Paragraph>
                )}
              </Card>
            </Col>
          ))}
        </Row>

        <Card size="small" style={{ marginTop: 24, borderRadius: 12 }} title="Quick rate guide (wallet / overage)">
          <Row gutter={[12, 8]}>
            {[
              ['Fast', '$1.50 / 1M'],
              ['Quality', '$3.50 / 1M'],
              ['Reasoning', '$6.00 / 1M'],
              ['Large', '$5.00 / 1M'],
            ].map(([label, rate]) => (
              <Col xs={12} sm={6} key={label}>
                <Tag>{label}</Tag>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>{rate}</Typography.Text>
              </Col>
            ))}
          </Row>
          <Typography.Paragraph type="secondary" style={{ marginTop: 10, marginBottom: 0, fontSize: 12 }}>
            Included pool covers managed chat first. Overage uses your credit wallet at these rates.
          </Typography.Paragraph>
        </Card>

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
