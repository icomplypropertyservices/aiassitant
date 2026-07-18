import React, { useEffect, useState, useMemo } from 'react'
import {
  Card, Row, Col, Statistic, Button, InputNumber, Space, message, Tag, Alert, Table, Typography, Progress, Switch,
} from 'antd'
import { CheckOutlined, ArrowUpOutlined, CrownOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { api, IS_NATIVE, getUser } from '../api'
import TokenMeter from '../components/TokenMeter'
import CryptoPay from '../components/CryptoPay'
import PageHeader from '../components/PageHeader'

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
  const preorderOn = preorder == null ? true : Boolean(preorder.active)

  const load = () => {
    api('/billing/balance').then(setBalance).catch(() => {})
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
  }

  useEffect(() => {
    load()
    const checkout = params.get('checkout')
    const sessionId = params.get('session_id')
    if (checkout === 'success') {
      const finish = async () => {
        try {
          if (sessionId) {
            await api(`/billing/checkout/confirm?session_id=${encodeURIComponent(sessionId)}`, {
              method: 'POST',
            })
          }
          message.success('Payment received — your account has been updated')
          load()
        } catch (e) {
          message.warning(e.message || 'Checkout returned but fulfillment needs a moment — refresh Billing')
          load()
        } finally {
          setParams({})
        }
      }
      finish()
    }
    if (checkout === 'cancelled') {
      message.info('Checkout cancelled')
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
      window.open('https://aiassitant-nu.vercel.app/billing', '_blank')
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

  const choose = async (plan) => {
    if (IS_NATIVE) {
      message.info('Change plans on the website to comply with App Store rules.')
      window.open('https://aiassitant-nu.vercel.app/billing', '_blank')
      return
    }
    setBusy(true)
    try {
      const r = await api('/billing/plan', { method: 'POST', body: { plan } })
      if (r.checkout_url) {
        window.location.href = r.checkout_url
        return
      }
      message.success(`Plan set to ${plan}${r.dev_mode ? ' (dev mode)' : ''}`)
      load()
    } catch (e) {
      message.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  const openPortal = async () => {
    if (IS_NATIVE) {
      message.info('Manage subscription on the website.')
      window.open('https://aiassitant-nu.vercel.app/billing', '_blank')
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
    const upgrading = planRank(key) > planRank(currentPlan)
    if (upgrading) {
      return {
        label: p.cta_upgrade || p.cta || `Upgrade to ${p.name}`,
        disabled: false,
        type: 'primary',
      }
    }
    return {
      label: p.price ? `Switch to ${p.name}` : (p.cta || 'Select'),
      disabled: false,
      type: 'default',
    }
  }

  return (
    <div>
      <PageHeader
        title="Billing & plans"
        subtitle="Included monthly tokens, credit wallet, and upgrades. Token usage stays in the header meter."
        extra={
          payOpts?.stripe?.ready ? (
            <Button loading={busy} onClick={openPortal}>
              Manage subscription
            </Button>
          ) : null
        }
      />

      {IS_NATIVE && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="Subscriptions & top-ups"
          description="On the iOS app, manage payments on the website. Token meters still work here."
          action={
            <Button size="small" type="primary" onClick={() => window.open('https://aiassitant-nu.vercel.app/billing', '_blank')}>
              Open web billing
            </Button>
          }
        />
      )}

      {preorderOn && (
        <Alert
          type="success"
          showIcon
          style={{ marginBottom: 16 }}
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
          style={{ marginBottom: 16 }}
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
          style={{ marginBottom: 16 }}
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

      <Card className="aba-soft-card" style={{ marginBottom: 16 }}>
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
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          <strong>How billing works:</strong> your plan includes a monthly token pool for managed chat
          (Fast / Quality / Reasoning / Large). When the pool is used, usage draws from your credit wallet
          at the public rates below. Image and video are always wallet events.
        </Typography.Paragraph>
        {meter?.tokens_included > 0 && (
          <div style={{ marginTop: 12 }}>
            <Progress
              percent={Math.min(100, meter.usage_percent || 0)}
              status={meter.hard_block ? 'exception' : meter.warn ? 'active' : 'normal'}
              format={() => `${(meter.usage_percent || 0).toFixed(0)}% of included tokens`}
            />
          </div>
        )}
      </Card>

      <Card
        className="aba-soft-card"
        style={{ marginBottom: 16 }}
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

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} md={8}>
          <Card className="aba-stat-card" title="Credit wallet">
            <Statistic prefix="$" precision={2} value={balance?.credits ?? 0} />
            <Space style={{ marginTop: 12 }} wrap>
              <InputNumber min={5} max={1000} prefix="$" value={amount} onChange={setAmount} />
              <Button type="primary" onClick={topup} loading={busy} disabled={payOpts && !payOpts.stripe?.enabled}>
                Top up card{payOpts?.stripe?.sandbox ? ' (test)' : ''}
              </Button>
              <Button
                onClick={() => {
                  if (IS_NATIVE) {
                    window.open('https://aiassitant-nu.vercel.app/billing', '_blank')
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
          <Card title="This period">
            <Statistic title="Tokens used" value={meter?.tokens_used_period ?? usage?.total_tokens ?? 0} />
            <Statistic
              title="Included remaining"
              value={meter?.tokens_remaining_included ?? 0}
            />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card className="aba-stat-card" title="Current plan">
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

      <Typography.Title level={4} style={{ marginTop: 8 }}>
        Subscription tiers
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        Upgrade anytime. Higher tiers unlock more agents, companies, and included tokens.
      </Typography.Paragraph>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        {orderedPlans.map(([key, p]) => {
          const cta = ctaFor(key, p)
          const isCurrent = currentPlan === key
          const isUpgrade = planRank(key) > planRank(currentPlan)
          return (
            <Col xs={24} sm={12} lg={6} key={key}>
              <Card
                className={`aba-plan-card${p.highlight ? ' is-highlight' : ''}${isCurrent ? ' is-current' : ''}`}
                style={{
                  height: '100%',
                  border: isCurrent ? '2px solid #1668dc' : p.highlight ? '2px solid #1677ff' : undefined,
                  borderRadius: 14,
                }}
                title={
                  <Space wrap>
                    <span>{p.name}</span>
                    {p.badge && <Tag color={p.highlight ? 'blue' : 'default'}>{p.badge}</Tag>}
                    {isCurrent && <Tag color="success">You</Tag>}
                  </Space>
                }
                extra={
                  <Typography.Text strong style={{ fontSize: 18 }}>
                    {p.price ? (
                      preorderOn && p.price_checkout != null && p.price_checkout < p.price ? (
                        <>
                          <Typography.Text delete type="secondary" style={{ fontSize: 13, marginRight: 6 }}>
                            ${p.price}
                          </Typography.Text>
                          ${Number(p.price_checkout).toFixed(p.price_checkout % 1 ? 2 : 0)}
                        </>
                      ) : `$${p.price}`
                    ) : '$0'}
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>/mo</Typography.Text>
                  </Typography.Text>
                }
              >
                <Typography.Paragraph type="secondary" style={{ minHeight: 48, fontSize: 13 }}>
                  {p.blurb}
                </Typography.Paragraph>
                {preorderOn && p.price > 0 && (
                  <Tag color="gold" style={{ marginBottom: 8 }}>
                    Pre-order · {p.preorder_discount_percent || 10}% off
                  </Tag>
                )}
                <Tag color="processing" style={{ marginBottom: 8 }}>
                  {(p.tokens_included || 0).toLocaleString()} tokens/mo
                </Tag>
                {p.value_line && (
                  <div style={{ marginBottom: 10, fontSize: 12, color: '#16a34a' }}>
                    {p.value_line}
                  </div>
                )}
                <ul style={{ paddingLeft: 18, marginBottom: 12, fontSize: 13 }}>
                  {(p.features || []).slice(0, 6).map((f) => (
                    <li key={f} style={{ marginBottom: 4 }}>
                      <CheckOutlined style={{ color: '#16a34a', marginRight: 6 }} />
                      {f}
                    </li>
                  ))}
                </ul>
                {(p.teasers || []).length > 0 && !isCurrent && (
                  <Alert
                    type="info"
                    showIcon={false}
                    style={{ marginBottom: 12, fontSize: 12 }}
                    message={(p.teasers || [])[0]}
                  />
                )}
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Button
                    type={cta.type}
                    icon={isUpgrade ? <ArrowUpOutlined /> : null}
                    disabled={cta.disabled}
                    loading={busy}
                    onClick={() => choose(key)}
                    block
                    size="large"
                  >
                    {cta.label}
                    {p.price > 0 && isUpgrade
                      ? ` · $${preorderOn && p.price_checkout != null ? Number(p.price_checkout).toFixed(p.price_checkout % 1 ? 2 : 0) : p.price}/mo`
                      : ''}
                  </Button>
                  {p.price > 0 && !isCurrent && (
                    <Button
                      block
                      onClick={() => {
                        if (IS_NATIVE) {
                          window.open('https://aiassitant-nu.vercel.app/billing', '_blank')
                          return
                        }
                        setCryptoCtx({ kind: 'plan', plan: key })
                        setCryptoOpen(true)
                      }}
                    >
                      {preorderOn ? 'Pre-order with crypto' : 'Pay with crypto'}
                    </Button>
                  )}
                </Space>
              </Card>
            </Col>
          )
        })}
      </Row>

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
    </div>
  )
}
