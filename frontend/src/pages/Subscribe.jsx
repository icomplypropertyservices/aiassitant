import React, { useEffect, useState, useMemo } from 'react'
import {
  Card, Row, Col, Button, Typography, Tag, Input, Space, message, Alert,
} from 'antd'
import {
  RobotOutlined, CreditCardOutlined, WalletOutlined, CrownOutlined,
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
              background: 'transparent',
              overflow: 'hidden',
              boxShadow: '0 8px 24px rgba(15,23,42,0.35)',
            }}
          >
            <img
              src={`${import.meta.env.BASE_URL}logo-256.png`}
              alt="AI Business Assistant"
              width={48}
              height={48}
              style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
            />
          </div>
          <Typography.Title level={2} style={{ margin: '0 0 6px', letterSpacing: '-0.03em' }}>
            {trialEnded
              ? 'Pick a paid plan to continue'
              : (preorderOn ? (preorder?.headline || 'Pre-order your plan') : 'Choose your plan')}
          </Typography.Title>
          <Typography.Paragraph style={{ margin: '0 auto 12px', maxWidth: 560, textAlign: 'center' }}>
            Signed in as <strong>{user?.email}</strong>.
            {trialEnded
              ? ' Your free trial has ended — choose Starter or higher to keep agents, tokens, and workspace access.'
              : preorderOn
                ? ` Pre-order before launch (${preorder?.launch_label || '27 July 2026'}) for ${preorder?.discount_percent || 10}% off + early access. Pay with Stripe or crypto.`
                : ' Start free, then upgrade when you need more agents and tokens. Managed models stay simple: Fast, Quality, Reasoning, Large.'}
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
            <span className="aba-feature-pill"><CrownOutlined /> Early access for pre-orders</span>
          </Space>
          <div style={{ marginTop: 16, width: '100%', maxWidth: 400, marginLeft: 'auto', marginRight: 'auto' }}>
            <div className="aba-subscribe-company-row" style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', alignItems: 'center', gap: 10 }}>
              <Typography.Text style={{ color: 'rgba(255,255,255,0.9)' }}>First company name</Typography.Text>
              <Input
                className="aba-subscribe-company"
                style={{ width: '100%', maxWidth: 320, borderRadius: 10 }}
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
            style={{ marginBottom: 16, borderRadius: 12, maxWidth: 720, marginLeft: 'auto', marginRight: 'auto' }}
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
            style={{ marginBottom: 16, borderRadius: 12, maxWidth: 720, marginLeft: 'auto', marginRight: 'auto' }}
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

        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 24, borderRadius: 12, maxWidth: 720, marginLeft: 'auto', marginRight: 'auto' }}
          message="How tokens work"
          description={
            <>
              Each plan includes a monthly token pool for managed chat. When the pool is used, usage
              draws from your credit wallet at transparent rates. Image/video always use the wallet.
            </>
          }
        />

        <PlansSectionHeader
          title={preorderOn ? 'Pre-order plans' : 'Choose a plan'}
          subtitle={preorderOn
            ? 'Centered pricing — 10% off until launch. Pick the tier that fits your team.'
            : 'Pick the tier that fits your team. Upgrade anytime from Billing.'}
        />

        <PlanCards
          plans={entries}
          preorderOn={preorderOn}
          busy={busy}
          stripeSandbox={!!payOpts?.stripe?.sandbox}
          showCrypto
          onChoose={choose}
          onCrypto={payCrypto}
        />

        <Card
          size="small"
          style={{ marginTop: 28, borderRadius: 14, maxWidth: 720, marginLeft: 'auto', marginRight: 'auto' }}
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
