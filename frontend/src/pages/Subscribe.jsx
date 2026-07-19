import React, { useEffect, useState, useMemo } from 'react'
import {
  Card, Row, Col, Button, Typography, Tag, Input, Space, message, Alert,
} from 'antd'
import {
  CreditCardOutlined, WalletOutlined, CrownOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, getToken, getUser, setAuth, clearAuth, IS_NATIVE } from '../api'
import CryptoPay from '../components/CryptoPay'
import PlanCards, { PlansSectionHeader } from '../components/PlanCards'

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
  // Live subscriptions by default; pre-order only when API says active
  const preorderOn = Boolean(preorder?.active)
  const user = getUser()
  const expiresAt = user?.subscription_expires_at || null
  const planKey = String(user?.plan || 'none').toLowerCase()
  const expiresMeta = useMemo(() => {
    if (!expiresAt) return null
    const d = new Date(expiresAt)
    if (Number.isNaN(d.getTime())) return null
    const days = Math.ceil((d.getTime() - Date.now()) / 86400000)
    return { date: d, days }
  }, [expiresAt])
  // One-shot free trial: available only when never activated (no expiry stamp, plan none).
  // needs_subscription alone is NOT enough — new users may land here before trial starts.
  const trialEnded = useMemo(() => {
    if (expiresMeta && expiresMeta.days < 0) return true
    if (expiresAt) return true // expiry window was stamped = trial already used
    if (planKey === 'trial') return true
    if (planKey && !['none', '', 'pay_as_you_go'].includes(planKey)) return true
    return false
  }, [expiresAt, expiresMeta, planKey])

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
        active: false,
        live: true,
        launch_label: 'Live now',
        discount_percent: 0,
        early_access: false,
        headline: 'Subscribe — live monthly plans',
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

  const trialPlan = plans.trial || null

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
      // Free trial and paid plans both use POST /billing/plan { plan }
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
      const msg = String(e.message || '')
      const isFreePlan = planKey === 'trial' || !(plans[planKey]?.price > 0)
      // 402 on free trial means trial used/ended — not "pay with crypto"
      if (!isFreePlan && (msg.toLowerCase().includes('crypto') || e.status === 402)) {
        setCryptoPlan(planKey)
        setCryptoOpen(true)
      } else {
        message.error(msg || 'Could not activate plan')
      }
    } finally {
      setBusy(null)
    }
  }

  const ctaFor = (key, p) => {
    if (key === 'trial' && trialEnded) {
      return { label: 'Trial no longer available', disabled: true, type: 'default' }
    }
    if (key === 'trial' || !(p.price > 0)) {
      return {
        label: 'Start free trial — no card',
        disabled: false,
        type: 'primary',
      }
    }
    const checkout = preorderOn && p.price_checkout != null ? p.price_checkout : p.price
    const priceLabel = Number(checkout) % 1 ? Number(checkout).toFixed(2) : String(checkout)
    return {
      label: `${p.cta || (preorderOn ? `Pre-order ${p.name}` : `Subscribe to ${p.name}`)} · $${priceLabel}/mo${payOpts?.stripe?.sandbox ? ' (test)' : ''}`,
      disabled: false,
      type: p.highlight ? 'primary' : 'default',
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
      {/* Same centering rail as Login: aba-page-center → aba-page-shell */}
      <div className="aba-page-center">
        <div className="aba-page-shell aba-auth-stack">
          {/* Hero */}
          <div className="aba-auth-hero aba-hero" style={{ marginBottom: 28, width: '100%' }}>
            <div className="aba-auth-logo">
              <img
                src={`${import.meta.env.BASE_URL}logo.png`}
                alt="AI Business Assistant"
                width={88}
                height={88}
                style={{ objectFit: 'contain', borderRadius: '22%' }}
              />
            </div>
            <Typography.Title level={2} style={{ color: '#fff', margin: '0 0 6px', letterSpacing: '-0.03em' }}>
              {trialEnded
                ? 'Pick a paid plan to continue'
                : 'Start free — or subscribe'}
            </Typography.Title>
            <Typography.Paragraph style={{ color: 'rgba(255,255,255,0.88)', margin: '0 auto 12px', maxWidth: 560 }}>
              Signed in as <strong>{user?.email}</strong>.
              {trialEnded
                ? ' Your free trial has ended — choose Starter or higher to keep agents, tokens, and workspace access.'
                : preorderOn
                  ? ` Start the free trial with one click (no card), or pre-order before launch (${preorder?.launch_label || '27 July 2026'}) for ${preorder?.discount_percent || 10}% off + early access.`
                  : ' Start free with one click (no card), or subscribe to a monthly plan (card or crypto). Access starts when payment confirms.'}
            </Typography.Paragraph>
            {expiresMeta && (
              <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'center', flexWrap: 'wrap', gap: 8 }}>
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
            <Space wrap style={{ justifyContent: 'center', width: '100%' }}>
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
              <span className="aba-feature-pill"><CrownOutlined /> Live monthly subscriptions</span>
            </Space>
            <div className="aba-subscribe-company-wrap">
              <div className="aba-subscribe-company-row">
                <Typography.Text style={{ color: 'rgba(255,255,255,0.9)' }}>First company name</Typography.Text>
                <Input
                  className="aba-subscribe-company"
                  placeholder="My company"
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  size="large"
                />
              </div>
            </div>
          </div>

          {trialEnded && (
            <Alert
              type="warning"
              showIcon
              className="aba-auth-alert"
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

          {/* Primary free-trial CTA — centered Ant Design Card */}
          {!trialEnded && (
            <Card
              className="aba-soft-card aba-auth-card aba-trial-cta-card"
              styles={{ body: { padding: '22px 24px' } }}
            >
              <div className="aba-trial-cta-inner">
                <Tag color="success" className="aba-trial-cta-tag">Recommended to start</Tag>
                <Typography.Title level={4} className="aba-trial-cta-title">
                  <ThunderboltOutlined className="aba-trial-cta-icon" />
                  Free trial — one click, no card
                </Typography.Title>
                <Typography.Paragraph type="secondary" className="aba-trial-cta-blurb">
                  {trialPlan
                    ? `${(trialPlan.tokens_included || 50000).toLocaleString()} tokens · up to ${trialPlan.agents || 10} agents · ${trialPlan.companies || 2} companies. Activate instantly — upgrade anytime from Billing.`
                    : '50,000 tokens · up to 10 agents · 2 companies. Activate instantly — upgrade anytime from Billing.'}
                </Typography.Paragraph>
                <Button
                  type="primary"
                  size="large"
                  loading={busy === 'trial'}
                  onClick={() => choose('trial')}
                  className="aba-trial-cta-btn"
                  icon={<ThunderboltOutlined />}
                >
                  Start free trial — no card
                </Button>
                <Typography.Paragraph type="secondary" className="aba-trial-cta-foot">
                  Or pick a paid plan below (card or crypto)
                </Typography.Paragraph>
              </div>
            </Card>
          )}

          {preorderOn && (
            <Alert
              type="success"
              showIcon
              className="aba-auth-alert"
              message={`Pre-order open · launch ${preorder?.launch_label || '27 July 2026'}`}
              description={
                <>
                  Pre-orders get <strong>{preorder?.discount_percent || 10}% off</strong> paid plans and{' '}
                  <strong>early access</strong> before public open. Checkout is ready for{' '}
                  <strong>Stripe (card)</strong> and <strong>crypto (ETH / SOL / BTC / XRP)</strong>.
                </>
              }
            />
          )}

          {payOpts?.stripe?.sandbox && (
            <Alert
              type="info"
              showIcon
              className="aba-auth-alert"
              message="Stripe sandbox (test mode)"
              description={
                <>
                  Test card: <Typography.Text code>4242 4242 4242 4242</Typography.Text>, any future expiry, any CVC.
                </>
              }
            />
          )}

          <Alert
            type="info"
            showIcon
            className="aba-auth-alert aba-auth-alert--last"
            message="How tokens work"
            description={
              <>
                Each plan includes a monthly token pool for managed chat. When the pool is used, usage
                draws from your credit wallet at transparent rates. Image/video always use the wallet.
              </>
            }
          />

          {/* Centered plan boxes — aba-box + Ant Design Card shell + tier Cards (same as Billing) */}
          <div className="aba-box aba-billing-plans-box">
            <Card
              className="aba-soft-card aba-auth-card aba-billing-plans-card"
              bordered={false}
              styles={{ body: { padding: '12px 4px 16px' } }}
            >
              <PlansSectionHeader
                title={
                  trialEnded
                    ? 'Choose a paid plan'
                    : (preorderOn ? 'Pre-order plans' : 'Live subscription plans')
                }
                subtitle={
                  trialEnded
                    ? 'Starter, Pro, or Business — pay with Stripe or crypto to restore access.'
                    : preorderOn
                      ? 'Centered pricing — 10% off until launch. Free trial is highlighted; paid tiers unlock more capacity.'
                      : 'Real monthly subscriptions at list price. Free trial is highlighted; paid tiers unlock more capacity.'
                }
                centered
              />
              <div className="aba-billing-plans-inner">
                <PlanCards
                  plans={entries}
                  preorderOn={preorderOn}
                  busy={busy}
                  stripeSandbox={!!payOpts?.stripe?.sandbox}
                  showCrypto
                  ctaFor={ctaFor}
                  onChoose={choose}
                  onCrypto={payCrypto}
                />
              </div>
            </Card>
          </div>

          <Card
            className="aba-soft-card aba-auth-card aba-subscribe-rates-card"
            size="small"
            title={<div style={{ textAlign: 'center' }}>Quick rate guide (wallet / overage)</div>}
          >
            <Row gutter={[12, 12]} justify="center">
              {[
                ['Fast', '$1.50 / 1M'],
                ['Quality', '$3.50 / 1M'],
                ['Reasoning', '$6.00 / 1M'],
                ['Large', '$5.00 / 1M'],
              ].map(([label, rate]) => (
                <Col xs={12} sm={6} key={label} style={{ textAlign: 'center' }}>
                  <Tag>{label}</Tag>
                  <div>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>{rate}</Typography.Text>
                  </div>
                </Col>
              ))}
            </Row>
            <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0, fontSize: 12, textAlign: 'center' }}>
              Included pool covers managed chat first. Overage uses your credit wallet at these rates.
              Full rate table on Billing after you subscribe.
            </Typography.Paragraph>
          </Card>

          <div style={{ textAlign: 'center', marginTop: 28, width: '100%' }}>
            <Button type="link" onClick={() => { clearAuth(); nav('/login') }}>
              Sign out
            </Button>
          </div>
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
