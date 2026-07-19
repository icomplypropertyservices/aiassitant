import React, { useEffect, useState, useMemo } from 'react'
import {
  Card, Row, Col, Statistic, Button, InputNumber, Space, message, Tag, Alert, Table, Typography, Progress, Switch, Divider, Segmented,
} from 'antd'
import { ArrowUpOutlined, CrownOutlined, ThunderboltOutlined, CloudServerOutlined } from '@ant-design/icons'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { api, IS_NATIVE, getUser, getToken, setAuth } from '../api'
import { absoluteAppUrl } from '../publicPaths'
import TokenMeter from '../components/TokenMeter'
import CryptoPay from '../components/CryptoPay'
import PageShell from '../components/PageShell'
import PlanCards, { PlansSectionHeader } from '../components/PlanCards'

const WEB_BILLING = () => absoluteAppUrl('/billing')

const PLAN_ORDER = ['trial', 'starter', 'pro', 'business']

function planRank(id) {
  const i = PLAN_ORDER.indexOf(id)
  return i < 0 ? -1 : i
}

export default function Billing() {
  const nav = useNavigate()
  const user = getUser()
  const [params, setParams] = useSearchParams()
  const [balance, setBalance] = useState(null)
  const [plans, setPlans] = useState({})
  const [usage, setUsage] = useState(null)
  const [rates, setRates] = useState([])
  const [ratesNote, setRatesNote] = useState('')
  const [amount, setAmount] = useState(25)
  const [busy, setBusy] = useState(false)
  const [cryptoOpen, setCryptoOpen] = useState(false)
  const [cryptoCtx, setCryptoCtx] = useState({ kind: 'topup' })
  const [payOpts, setPayOpts] = useState(null)
  const [preorder, setPreorder] = useState(null)
  const [autoTopup, setAutoTopup] = useState(null)
  const [autoBusy, setAutoBusy] = useState(false)
  const [storage, setStorage] = useState(null)
  const [storageBusy, setStorageBusy] = useState(null)
  // Live monthly plans only (pre-order UI off unless API forces active + not live)
  const preorderOn = Boolean(preorder?.active) && preorder?.live === false
  const [billingInterval, setBillingInterval] = useState('month')

  const load = () => {
    api('/billing/balance').then((b) => {
      setBalance(b)
      if (b?.storage) setStorage(b.storage)
    }).catch(() => {})
    api('/billing/plans').then(setPlans).catch(() => {})
    api('/billing/usage').then(setUsage).catch(() => {})
    api('/billing/rates').then((r) => {
      setRates(r.rates || [])
      setRatesNote(r.note || '')
    }).catch(() => {})
    api('/billing/payment-options').then((o) => {
      setPayOpts(o)
      if (o?.preorder) setPreorder(o.preorder)
    }).catch(() => {})
    api('/billing/preorder').then(setPreorder).catch(() => {})
    api('/billing/auto-topup').then(setAutoTopup).catch(() => {})
    api('/billing/storage').then(setStorage).catch(() => {})
  }

  const buyStorageAddon = async (addonId) => {
    setStorageBusy(addonId)
    try {
      const r = await api('/billing/storage-addon', {
        method: 'POST',
        body: { addon_id: addonId },
      })
      if (r.checkout_url) {
        window.location.href = r.checkout_url
        return
      }
      message.success(r.message || `Storage expanded: ${r.added_human || ''}`)
      load()
    } catch (e) {
      message.error(e.message || 'Could not start storage upgrade')
    } finally {
      setStorageBusy(null)
    }
  }

  useEffect(() => {
    load()
    const checkout = params.get('checkout')
    const sessionId = params.get('session_id')
    if (checkout === 'success') {
      const finish = async () => {
        try {
          if (sessionId) {
            const r = await api(`/billing/checkout/confirm?session_id=${encodeURIComponent(sessionId)}`, {
              method: 'POST',
            })
            message.success(r?.message || 'Payment received — subscription active')
          } else {
            message.success('Payment received — refreshing your account…')
          }
          // Refresh auth so needs_subscription clears for this user (and after multi-user checkout)
          try {
            const me = await api('/auth/me')
            setAuth(getToken(), me)
          } catch { /* ignore */ }
          load()
        } catch (e) {
          message.warning(e.message || 'Checkout returned but fulfillment needs a moment — refresh Billing')
          try {
            const me = await api('/auth/me')
            setAuth(getToken(), me)
          } catch { /* ignore */ }
          load()
        } finally {
          setParams({})
        }
      }
      finish()
    }
    if (checkout === 'cancelled') {
      message.info('Checkout cancelled — you can subscribe anytime below')
      setParams({})
    }
  }, [])

  const currentPlan = balance?.plan || user?.plan || 'none'
  const expiresAt = balance?.subscription_expires_at || user?.subscription_expires_at || null
  const expiresLabel = useMemo(() => {
    if (!expiresAt) return null
    const d = new Date(expiresAt)
    if (Number.isNaN(d.getTime())) return null
    const days = Math.ceil((d.getTime() - Date.now()) / 86400000)
    return { date: d, days }
  }, [expiresAt])
  const nextTeaserPlan = useMemo(() => {
    const p = plans[currentPlan]
    const next = p?.next_plan
    return next && plans[next] ? { key: next, ...plans[next] } : null
  }, [plans, currentPlan])

  const orderedPlans = useMemo(() => {
    const entries = Object.entries(plans)
    entries.sort((a, b) => (a[1].sort ?? 50) - (b[1].sort ?? 50))
    return entries
  }, [plans])

  const topup = async () => {
    if (IS_NATIVE) {
      message.info('On iOS, open Billing on the website to top up (App Store rules).')
      window.open(WEB_BILLING(), '_blank')
      return
    }
    setBusy(true)
    try {
      const r = await api('/billing/topup', { method: 'POST', body: { amount } })
      if (r.checkout_url) {
        window.location.href = r.checkout_url
        return
      }
      message.success(`Added $${amount} credit${r.dev_mode ? ' (dev mode)' : ''}`)
      load()
    } catch (e) {
      message.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  const choose = async (plan, intervalArg) => {
    if (IS_NATIVE) {
      message.info('Change plans on the website to comply with App Store rules.')
      window.open(WEB_BILLING(), '_blank')
      return
    }
    const interval = (intervalArg === 'year' || billingInterval === 'year') && plans[plan]?.price > 0
      ? 'year'
      : 'month'
    setBusy(true)
    try {
      const r = await api('/billing/plan', {
        method: 'POST',
        body: { plan, interval },
      })
      if (r.checkout_url) {
        message.loading({
          content: interval === 'year' ? 'Opening annual Stripe checkout…' : 'Opening monthly Stripe checkout…',
          key: 'stripe',
          duration: 2,
        })
        window.location.href = r.checkout_url
        return
      }
      message.success(`Plan set to ${plan}${r.dev_mode ? ' (dev mode)' : ''}`)
      try {
        const me = await api('/auth/me')
        setAuth(getToken(), me)
      } catch { /* ignore */ }
      load()
    } catch (e) {
      const msg = String(e.message || '')
      if (msg.toLowerCase().includes('crypto') || e.status === 402) {
        setCryptoCtx({ kind: 'plan', plan })
        setCryptoOpen(true)
      } else {
        message.error(msg || 'Could not start subscription')
      }
    } finally {
      setBusy(false)
    }
  }

  const openPortal = async () => {
    if (IS_NATIVE) {
      message.info('Manage subscription on the website.')
      window.open(WEB_BILLING(), '_blank')
      return
    }
    setBusy(true)
    try {
      const r = await api('/billing/portal', { method: 'POST', body: {} })
      if (r?.url) {
        window.location.href = r.url
        return
      }
      message.error('Portal URL missing')
    } catch (e) {
      message.error(e.message || 'Could not open billing portal')
    } finally {
      setBusy(false)
    }
  }

  const meter = usage?.meter || balance
  const ctaFor = (key, p) => {
    if (currentPlan === key) return { label: 'Current plan', disabled: true, type: 'default' }
    // Free trial: one-click POST /billing/plan { plan: 'trial' } — obvious for users not on a paid tier
    if (key === 'trial' || !(p.price > 0)) {
      const eligible =
        !currentPlan || ['none', 'pay_as_you_go', ''].includes(String(currentPlan).toLowerCase())
      return {
        label: eligible ? 'Start free trial — no card' : 'Free trial unavailable',
        disabled: !eligible,
        type: eligible ? 'primary' : 'default',
      }
    }
    const iv = billingInterval === 'year' && p.price > 0 ? 'year' : 'month'
    const annual = p.price_annual != null ? p.price_annual : (p.price > 0 ? p.price * 10 : 0)
    const amount = iv === 'year' ? annual : p.price
    const unit = iv === 'year' ? '/yr' : '/mo'
    const price = p.price > 0
      ? ` · $${Number(amount) % 1 ? Number(amount).toFixed(2) : amount}${unit}`
      : ''
    const sandbox = payOpts?.stripe?.sandbox ? ' (test)' : ''
    const upgrading = planRank(key) > planRank(currentPlan)
    if (upgrading) {
      return {
        label: `${iv === 'year' ? 'Upgrade annually' : (p.cta_upgrade || p.cta || `Upgrade to ${p.name}`)}${price}${sandbox}`,
        disabled: false,
        type: 'primary',
      }
    }
    return {
      label: `${iv === 'year' ? 'Pay annually' : `Subscribe to ${p.name}`}${price}${sandbox}`,
      disabled: false,
      type: 'default',
    }
  }

  return (
    <PageShell
      title="Billing & plans"
      subtitle="Included monthly tokens, credit wallet, and upgrades. Token usage stays in the header meter."
      extra={
        payOpts?.stripe?.ready ? (
          <Button loading={busy} onClick={openPortal}>
            Manage subscription
          </Button>
        ) : null
      }
    >
      {IS_NATIVE && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16, borderRadius: 12 }}
          message="Subscriptions & top-ups"
          description="On the iOS app, manage payments on the website. Token meters still work here."
          action={
            <Button size="small" type="primary" onClick={() => window.open(WEB_BILLING(), '_blank')}>
              Open web billing
            </Button>
          }
        />
      )}

      {preorderOn && (
        <Alert
          type="success"
          showIcon
          style={{ marginBottom: 16, borderRadius: 12 }}
          message={`Pre-order · ${preorder?.discount_percent || 10}% off · early access`}
          description={
            <>
              Launch {preorder?.launch_label || '27 July 2026'}. Paid plans are discounted until launch.
              Checkout accepts <strong>Stripe (card)</strong> and <strong>crypto (ETH / SOL / BTC / XRP)</strong>.
            </>
          }
        />
      )}

      {payOpts?.stripe?.sandbox && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16, borderRadius: 12 }}
          message="Stripe sandbox (test mode)"
          description={
            <>
              Test card: <Typography.Text code>4242 4242 4242 4242</Typography.Text>, any future expiry, any CVC.
            </>
          }
        />
      )}

      {/* Upgrade teaser banner */}
      {nextTeaserPlan && currentPlan !== 'business' && (
        <Alert
          type="success"
          showIcon
          icon={<CrownOutlined />}
          style={{ marginBottom: 16, borderRadius: 12 }}
          message={
            <span>
              <strong>{plans[currentPlan]?.upgrade_teaser || `Upgrade to ${nextTeaserPlan.name}`}</strong>
            </span>
          }
          description={
            <Space wrap style={{ marginTop: 8 }}>
              <Tag color="blue">{(nextTeaserPlan.tokens_included || 0).toLocaleString()} tokens/mo</Tag>
              {nextTeaserPlan.price > 0 && <Tag>${nextTeaserPlan.price}/mo</Tag>}
              {nextTeaserPlan.value_line && <Typography.Text type="secondary">{nextTeaserPlan.value_line}</Typography.Text>}
              <Button
                type="primary"
                size="small"
                icon={<ArrowUpOutlined />}
                loading={busy}
                onClick={() => choose(nextTeaserPlan.key)}
              >
                {nextTeaserPlan.cta_upgrade || `Upgrade to ${nextTeaserPlan.name}`}
              </Button>
            </Space>
          }
        />
      )}

      {/* Training storage monitor + upgrade */}
      {storage && (
        <Card
          className="aba-soft-card aba-billing-meter-card"
          style={{ marginBottom: 16, borderRadius: 16 }}
          styles={{
            header: { textAlign: 'center', borderBottom: '1px solid var(--aba-border, #e2e8f0)' },
            body: { paddingTop: 20, paddingBottom: 20 },
          }}
          title={
            <Space>
              <CloudServerOutlined />
              Training storage
            </Space>
          }
        >
          {(storage.hard_block || storage.warn) && (
            <Alert
              type={storage.hard_block ? 'error' : 'warning'}
              showIcon
              style={{ marginBottom: 16, textAlign: 'left' }}
              message={storage.hard_block ? 'Storage full' : 'Storage running low'}
              description={
                storage.upgrade_hint
                || 'Free space by deleting files, upgrade your plan, or buy a permanent storage pack.'
              }
            />
          )}
          <Row gutter={[16, 16]} justify="center">
            <Col xs={24} sm={8}>
              <Statistic title="Used" value={storage.used_human || '0 B'} />
            </Col>
            <Col xs={24} sm={8}>
              <Statistic title="Limit" value={storage.limit_human || '—'} />
            </Col>
            <Col xs={24} sm={8}>
              <Statistic title="Bonus packs" value={storage.bonus_human || '0 B'} />
            </Col>
          </Row>
          {!storage.unlimited && (
            <div style={{ marginTop: 16, maxWidth: 480, marginLeft: 'auto', marginRight: 'auto' }}>
              <Progress
                percent={Math.min(100, storage.usage_percent || 0)}
                status={storage.hard_block ? 'exception' : storage.warn ? 'active' : 'normal'}
                format={() => `${(storage.usage_percent || 0).toFixed(0)}% used`}
              />
              <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, textAlign: 'center' }}>
                Plan includes {storage.plan_human || '—'}
                {storage.bonus_bytes > 0 ? ` + ${storage.bonus_human} purchased` : ''}.
                {' '}Counts training notes &amp; uploads (local + indexed cloud imports).
              </Typography.Paragraph>
            </div>
          )}
          <Divider style={{ margin: '20px 0 12px' }} />
          <Typography.Text strong style={{ display: 'block', textAlign: 'center', marginBottom: 12 }}>
            Expand storage
          </Typography.Text>
          <Row gutter={[12, 12]} justify="center">
            {(storage.addons || []).map((a) => (
              <Col key={a.id} xs={24} sm={8}>
                <Card size="small" className="aba-soft-card" styles={{ body: { textAlign: 'center' } }}>
                  <Typography.Text strong>{a.name}</Typography.Text>
                  <div style={{ margin: '8px 0', fontSize: 22, fontWeight: 700 }}>
                    ${Number(a.price_usd || 0).toFixed(0)}
                  </div>
                  <Typography.Paragraph type="secondary" style={{ fontSize: 12, minHeight: 40 }}>
                    {a.blurb}
                  </Typography.Paragraph>
                  <Button
                    type="primary"
                    block
                    loading={storageBusy === a.id}
                    onClick={() => buyStorageAddon(a.id)}
                  >
                    {a.cta || `Add ${a.gb} GB`}
                  </Button>
                </Card>
              </Col>
            ))}
          </Row>
          {nextTeaserPlan && (
            <div style={{ textAlign: 'center', marginTop: 16 }}>
              <Button type="link" icon={<ArrowUpOutlined />} onClick={() => {
                const el = document.getElementById('aba-plans')
                if (el) el.scrollIntoView({ behavior: 'smooth' })
              }}>
                Or upgrade plan to {nextTeaserPlan.name} for more included storage
              </Button>
            </div>
          )}
        </Card>
      )}

      {/* Token meter — centered Ant Design Card container */}
      <Card
        className="aba-soft-card aba-billing-meter-card"
        style={{ marginBottom: 16, borderRadius: 16 }}
        styles={{
          header: { textAlign: 'center', borderBottom: '1px solid var(--aba-border, #e2e8f0)' },
          body: { paddingTop: 20, paddingBottom: 20 },
        }}
        title={
          <Space>
            <ThunderboltOutlined />
            Token meter
          </Space>
        }
      >
        <div className="aba-billing-meter-body">
          <TokenMeter
            meter={
              meter
                ? {
                    ...meter,
                    plan: meter.plan || currentPlan,
                    subscription_expires_at:
                      meter.subscription_expires_at || expiresAt,
                  }
                : meter
            }
            compact={false}
          />
          <Typography.Paragraph type="secondary" className="aba-billing-meter-blurb">
            <strong>How billing works:</strong> your plan includes a monthly token pool for managed chat
            (Fast / Quality / Reasoning / Large). When the pool is used, usage draws from your credit wallet
            at the public rates below. Image and video are always wallet events.
          </Typography.Paragraph>
          {meter?.tokens_included > 0 && (
            <div className="aba-billing-meter-progress">
              <Progress
                percent={Math.min(100, meter.usage_percent || 0)}
                status={meter.hard_block ? 'exception' : meter.warn ? 'active' : 'normal'}
                format={() => `${(meter.usage_percent || 0).toFixed(0)}% of included tokens`}
              />
            </div>
          )}
        </div>
      </Card>

      <Card
        className="aba-soft-card aba-billing-section-card"
        style={{ marginBottom: 16, borderRadius: 16 }}
        title={<Space><ThunderboltOutlined /> Auto top-up — never stall mid-deal</Space>}
        extra={
          <Switch
            checked={!!autoTopup?.enabled}
            loading={autoBusy}
            onChange={async (v) => {
              setAutoBusy(true)
              try {
                const r = await api('/billing/auto-topup', {
                  method: 'PUT',
                  body: {
                    enabled: v,
                    amount: autoTopup?.amount ?? 25,
                    threshold_credits: autoTopup?.threshold_credits ?? 5,
                    token_pct: autoTopup?.token_pct ?? 85,
                  },
                })
                message.success(r.message || (v ? 'Auto top-up on' : 'Auto top-up off'))
                setAutoTopup((prev) => ({ ...(prev || {}), ...r, enabled: v }))
              } catch (e) {
                message.error(e.message)
              } finally {
                setAutoBusy(false)
              }
            }}
          />
        }
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
          When your wallet dips or tokens hit the red zone, we open a one-click Stripe refill for the amount you choose.
          You still confirm checkout — no surprise charges without a card session.
        </Typography.Paragraph>
        <Space wrap size="middle">
          <span>
            Refill amount{' '}
            <InputNumber
              min={5}
              max={500}
              prefix="$"
              value={autoTopup?.amount ?? 25}
              onChange={(v) => setAutoTopup((p) => ({ ...(p || {}), amount: v }))}
              onBlur={async () => {
                if (!autoTopup) return
                try {
                  await api('/billing/auto-topup', {
                    method: 'PUT',
                    body: {
                      enabled: !!autoTopup.enabled,
                      amount: autoTopup.amount ?? 25,
                      threshold_credits: autoTopup.threshold_credits ?? 5,
                      token_pct: autoTopup.token_pct ?? 85,
                    },
                  })
                } catch { /* ignore */ }
              }}
            />
          </span>
          <span>
            When credits below{' '}
            <InputNumber
              min={0}
              max={200}
              prefix="$"
              value={autoTopup?.threshold_credits ?? 5}
              onChange={(v) => setAutoTopup((p) => ({ ...(p || {}), threshold_credits: v }))}
            />
          </span>
          <span>
            Or tokens used ≥{' '}
            <InputNumber
              min={50}
              max={99}
              addonAfter="%"
              value={autoTopup?.token_pct ?? 85}
              onChange={(v) => setAutoTopup((p) => ({ ...(p || {}), token_pct: v }))}
            />
          </span>
          <Button
            type="primary"
            ghost
            loading={autoBusy}
            onClick={async () => {
              setAutoBusy(true)
              try {
                await api('/billing/auto-topup', {
                  method: 'PUT',
                  body: {
                    enabled: true,
                    amount: autoTopup?.amount ?? 25,
                    threshold_credits: autoTopup?.threshold_credits ?? 5,
                    token_pct: autoTopup?.token_pct ?? 85,
                  },
                })
                const r = await api('/billing/auto-topup/trigger', { method: 'POST', body: {} })
                if (r.checkout_url) window.location.href = r.checkout_url
                else message.info(r.message || (r.skipped ? 'Not needed yet' : 'Done'))
                load()
              } catch (e) {
                message.error(e.message)
              } finally {
                setAutoBusy(false)
              }
            }}
          >
            Save &amp; test auto top-up
          </Button>
        </Space>
      </Card>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }} justify="center">
        <Col xs={24} md={8}>
          <Card className="aba-stat-card aba-soft-card" title="Credit wallet" style={{ height: '100%' }}>
            <Statistic prefix="$" precision={2} value={balance?.credits ?? 0} />
            <Space style={{ marginTop: 12 }} wrap>
              <InputNumber min={5} max={1000} prefix="$" value={amount} onChange={setAmount} />
              <Button type="primary" onClick={topup} loading={busy} disabled={payOpts && !payOpts.stripe?.enabled}>
                Top up card{payOpts?.stripe?.sandbox ? ' (test)' : ''}
              </Button>
              <Button
                onClick={() => {
                  if (IS_NATIVE) {
                    window.open(WEB_BILLING(), '_blank')
                    return
                  }
                  setCryptoCtx({ kind: 'topup', amount })
                  setCryptoOpen(true)
                }}
              >
                Top up crypto
              </Button>
            </Space>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card className="aba-soft-card" title="This period" style={{ height: '100%' }}>
            <Statistic title="Tokens used" value={meter?.tokens_used_period ?? usage?.total_tokens ?? 0} />
            <Statistic
              title="Included remaining"
              value={meter?.tokens_remaining_included ?? 0}
            />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card className="aba-stat-card aba-soft-card" title="Current plan" style={{ height: '100%' }}>
            <Tag color="blue" style={{ fontSize: 14 }}>
              {plans[currentPlan]?.name || currentPlan}
            </Tag>
            <div style={{ marginTop: 8 }}>
              <Typography.Text type="secondary">
                {(plans[currentPlan]?.tokens_included || 0).toLocaleString()} tokens / month included
              </Typography.Text>
            </div>
            {expiresLabel && (
              <div style={{ marginTop: 8 }}>
                {expiresLabel.days < 0 ? (
                  <Tag color="error">Expired {expiresLabel.date.toLocaleDateString()}</Tag>
                ) : expiresLabel.days === 0 ? (
                  <Tag color="warning">Expires today · {expiresLabel.date.toLocaleString()}</Tag>
                ) : (
                  <Tag color={expiresLabel.days <= 3 ? 'warning' : 'default'}>
                    {currentPlan === 'trial' ? 'Trial ends' : 'Renews / expires'}{' '}
                    {expiresLabel.date.toLocaleDateString()}
                    {expiresLabel.days <= 14 ? ` · ${expiresLabel.days}d left` : ''}
                  </Tag>
                )}
              </div>
            )}
            {plans[currentPlan]?.value_line && (
              <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}>
                {plans[currentPlan].value_line}
              </Typography.Paragraph>
            )}
          </Card>
        </Col>
      </Row>

      {/* Plans — centered aba-box + Ant Design Card shell + tier Cards */}
      <div className="aba-box aba-billing-plans-box">
        <Card
          className="aba-soft-card aba-billing-plans-card"
          bordered={false}
          styles={{ body: { padding: '8px 4px 12px' } }}
        >
          <PlansSectionHeader
            title="Live subscriptions — monthly or annual"
            subtitle="Annual = 10× monthly (2 months free). Same features. Card via Stripe or crypto."
            centered
          />
          <div style={{ textAlign: 'center', marginBottom: 16 }}>
            <Segmented
              size="large"
              value={billingInterval}
              onChange={setBillingInterval}
              options={[
                { label: 'Pay monthly', value: 'month' },
                { label: 'Pay annually · 2 mo free', value: 'year' },
              ]}
            />
          </div>
          {payOpts && !payOpts.ready_for_payments && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16, maxWidth: 640, marginInline: 'auto' }}
              message="Payments not configured"
              description="Set STRIPE_SECRET_KEY on the server (sk_test_… for sandbox or sk_live_… for real charges) so you and other customers can subscribe."
            />
          )}
          {payOpts?.stripe?.sandbox && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16, maxWidth: 640, marginInline: 'auto' }}
              message="Stripe test mode — use card 4242 4242 4242 4242"
            />
          )}
          <div className="aba-billing-plans-inner">
            <PlanCards
              plans={orderedPlans}
              preorderOn={false}
              billingInterval={billingInterval}
              currentPlan={currentPlan}
              busy={busy}
              stripeSandbox={!!payOpts?.stripe?.sandbox}
              showCrypto
              ctaFor={ctaFor}
              onChoose={choose}
              onCrypto={(key) => {
                if (IS_NATIVE) {
                  window.open(WEB_BILLING(), '_blank')
                  return
                }
                setCryptoCtx({ kind: 'plan', plan: key })
                setCryptoOpen(true)
              }}
            />
          </div>
        </Card>
      </div>

      <CryptoPay
        open={cryptoOpen}
        onClose={() => setCryptoOpen(false)}
        kind={cryptoCtx.kind}
        plan={cryptoCtx.plan}
        amount={cryptoCtx.amount ?? amount}
        onPaid={() => {
          message.success('Crypto payment applied')
          load()
        }}
      />

      <Card
        className="aba-soft-card aba-billing-section-card"
        style={{ borderRadius: 16 }}
        title="Token rates (wallet / overage)"
        extra={<Button type="link" onClick={() => nav('/subscribe')}>Compare on subscribe page</Button>}
      >
        {ratesNote && (
          <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
            {ratesNote}
          </Typography.Paragraph>
        )}
        <Table
          size="small"
          pagination={false}
          rowKey="id"
          dataSource={rates}
          columns={[
            { title: 'Tier', dataIndex: 'label', width: 140 },
            {
              title: 'Best for',
              dataIndex: 'blurb',
              ellipsis: true,
              render: (v, r) => v || (r.flat_usd != null ? `$${Number(r.flat_usd).toFixed(2)} each` : '—'),
            },
            {
              title: 'Wallet rate',
              dataIndex: 'usd_per_1m',
              width: 140,
              render: (v, r) => (
                r.flat_usd != null
                  ? `$${Number(r.flat_usd).toFixed(2)} / use`
                  : `$${Number(v).toFixed(2)} / 1M tokens`
              ),
            },
          ]}
        />
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0, fontSize: 12 }}>
          Included pool tokens are not charged again while remaining. After the pool is empty, chat uses wallet credits
          at the rates above. Media always uses the wallet.
        </Typography.Paragraph>
      </Card>
    </PageShell>
  )
}
