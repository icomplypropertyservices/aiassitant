import React, { useEffect, useState } from 'react'
import {
  Card, Row, Col, Statistic, Button, InputNumber, Space, message, Tag, List, Alert, Table, Typography,
} from 'antd'
import { useSearchParams } from 'react-router-dom'
import { api, IS_NATIVE } from '../api'
import TokenMeter from '../components/TokenMeter'
import CryptoPay from '../components/CryptoPay'
import PageHeader from '../components/PageHeader'

export default function Billing() {
  const [params, setParams] = useSearchParams()
  const [balance, setBalance] = useState(null)
  const [plans, setPlans] = useState({})
  const [usage, setUsage] = useState(null)
  const [rates, setRates] = useState([])
  const [amount, setAmount] = useState(25)
  const [busy, setBusy] = useState(false)
  const [cryptoOpen, setCryptoOpen] = useState(false)
  const [cryptoCtx, setCryptoCtx] = useState({ kind: 'topup' })
  const [payOpts, setPayOpts] = useState(null)

  const load = () => {
    api('/billing/balance').then(setBalance).catch(() => {})
    api('/billing/plans').then(setPlans).catch(() => {})
    api('/billing/usage').then(setUsage).catch(() => {})
    api('/billing/rates').then(r => setRates(r.rates || [])).catch(() => {})
    api('/billing/payment-options').then(setPayOpts).catch(() => {})
  }
  useEffect(() => {
    load()
    api('/billing/payment-options').then(setPayOpts).catch(() => {})
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
    }
  }

  const meter = usage?.meter || balance

  return (
    <div>
      <PageHeader
        title="Billing"
        subtitle="Manage your plan, credit wallet, and crypto or card top-ups. Token usage stays visible in the header."
      />
      {IS_NATIVE && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="Subscriptions & top-ups"
          description="On the iOS app, manage payments on the website. Token meters and usage still work here."
          action={
            <Button size="small" type="primary" onClick={() => window.open('https://aiassitant-nu.vercel.app/billing', '_blank')}>
              Open web billing
            </Button>
          }
        />
      )}
      {(payOpts?.stripe?.sandbox || balance?.stripe_sandbox) && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="Stripe sandbox (test mode) ready"
          description={
            <>
              Card payments use Stripe <strong>test</strong> keys. Test card:{' '}
              <Typography.Text code>4242 4242 4242 4242</Typography.Text>, any future expiry, any CVC.
              No real money is charged.
            </>
          }
        />
      )}
      {payOpts && !payOpts.stripe?.enabled && !payOpts.crypto?.enabled && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="No payment providers configured"
          description="Set STRIPE_SECRET_KEY=sk_test_… for card sandbox, and/or CRYPTO_*_ADDRESS for crypto."
        />
      )}
      {balance && !balance.stripe_live && !balance.stripe_enabled && !balance.crypto_enabled && !payOpts && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="Stripe is not configured — plan changes and top-ups apply instantly in dev mode."
        />
      )}
      {(balance?.crypto_enabled || payOpts?.crypto?.enabled) && (
        <Alert
          type="success"
          showIcon
          style={{ marginBottom: 16 }}
          message="Payment options"
          description={
            <>
              {(balance?.stripe_enabled || payOpts?.stripe?.enabled) && (
                <div>
                  <Tag color="blue">{payOpts?.stripe?.label || 'Card (Stripe)'}</Tag>
                  {payOpts?.stripe?.sandbox && <Tag color="gold">Sandbox</Tag>}
                </div>
              )}
              <div style={{ marginTop: 6 }}>
                <Tag color="purple">Crypto ETH / SOL / XRP</Tag>
                Send from your wallet, then verify the transaction hash.
              </div>
            </>
          }
        />
      )}

      <Card className="aba-soft-card" style={{ marginBottom: 16 }}>
        <TokenMeter meter={meter} compact={false} />
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          <strong>How billing works:</strong> your plan includes a monthly token pool (best for VPS/Qwen).
          Premium Claude &amp; Grok always bill your credit wallet at the public rates below.
          After the pool is used, further VPS usage also draws credits.
        </Typography.Paragraph>
      </Card>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} md={8}>
          <Card className="aba-stat-card" title="Credit wallet">
            <Statistic prefix="$" precision={2} value={balance?.credits ?? 0} />
            <Space style={{ marginTop: 12 }} wrap>
              <InputNumber min={5} max={1000} prefix="$" value={amount} onChange={setAmount} />
              <Button type="primary" onClick={topup} loading={busy} disabled={payOpts && !payOpts.stripe?.enabled}>
                Top up with card{payOpts?.stripe?.sandbox ? ' (test)' : ''}
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
                Top up (crypto)
              </Button>
            </Space>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card title="Lifetime (all time)">
            <Statistic title="Tokens" value={usage?.total_tokens ?? 0} />
            <Statistic title="Billed cost" prefix="$" precision={4} value={usage?.total_cost ?? 0} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card className="aba-stat-card" title="Current plan">
            <Tag color="blue" style={{ fontSize: 14 }}>
              {plans[balance?.plan]?.name || balance?.plan}
            </Tag>
            <div style={{ marginTop: 8 }}>
              <Typography.Text type="secondary">
                {(plans[balance?.plan]?.tokens_included || 0).toLocaleString()} tokens / month included
              </Typography.Text>
            </div>
          </Card>
        </Col>
      </Row>

      <Card title="Subscriptions" style={{ marginBottom: 16 }}>
        <List
          grid={{ gutter: 16, xs: 1, md: 2, lg: 3 }}
          dataSource={Object.entries(plans)}
          renderItem={([key, p]) => (
            <List.Item>
              <Card
                className={`aba-plan-card${p.highlight ? ' is-highlight' : ''}`}
                title={p.name}
                extra={p.price ? `$${p.price}/mo` : 'Free'}
              >
                <p>{p.blurb}</p>
                <Tag color="processing" style={{ marginBottom: 8 }}>
                  {(p.tokens_included || 0).toLocaleString()} tokens/mo
                </Tag>
                <ul style={{ paddingLeft: 18, marginBottom: 12 }}>
                  {(p.features || []).map(f => <li key={f}>{f}</li>)}
                </ul>
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Button
                    type={balance?.plan === key ? 'default' : 'primary'}
                    disabled={balance?.plan === key}
                    onClick={() => choose(key)}
                    block
                  >
                    {balance?.plan === key
                      ? 'Current plan'
                      : (p.price
                        ? `Upgrade with card${payOpts?.stripe?.sandbox ? ' (test)' : ''}`
                        : 'Select')}
                  </Button>
                  {p.price > 0 && balance?.plan !== key && (
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
                      Pay with crypto (ETH / SOL / XRP)
                    </Button>
                  )}
                </Space>
              </Card>
            </List.Item>
          )}
        />
      </Card>

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

      <Card title="Public token rates (USD per 1M tokens)">
        <Table
          size="small"
          pagination={false}
          rowKey="id"
          dataSource={rates}
          columns={[
            { title: 'Model', dataIndex: 'label' },
            { title: 'ID', dataIndex: 'id' },
            {
              title: '$ / 1M tokens',
              dataIndex: 'usd_per_1m',
              render: v => `$${Number(v).toFixed(2)}`,
            },
          ]}
        />
      </Card>
    </div>
  )
}
