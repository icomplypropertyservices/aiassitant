import React, { useEffect, useState } from 'react'
import {
  Card, Row, Col, Statistic, Button, InputNumber, Space, message, Tag, List, Alert, Table, Typography,
} from 'antd'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import TokenMeter from '../components/TokenMeter'

export default function Billing() {
  const [params, setParams] = useSearchParams()
  const [balance, setBalance] = useState(null)
  const [plans, setPlans] = useState({})
  const [usage, setUsage] = useState(null)
  const [rates, setRates] = useState([])
  const [amount, setAmount] = useState(25)
  const [busy, setBusy] = useState(false)

  const load = () => {
    api('/billing/balance').then(setBalance).catch(() => {})
    api('/billing/plans').then(setPlans).catch(() => {})
    api('/billing/usage').then(setUsage).catch(() => {})
    api('/billing/rates').then(r => setRates(r.rates || [])).catch(() => {})
  }
  useEffect(() => {
    load()
    const checkout = params.get('checkout')
    if (checkout === 'success') {
      message.success('Payment received — your account has been updated')
      setParams({})
    }
    if (checkout === 'cancelled') {
      message.info('Checkout cancelled')
      setParams({})
    }
  }, [])

  const topup = async () => {
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
      {balance && !balance.stripe_live && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="Stripe is not configured — plan changes and top-ups apply instantly in dev mode."
        />
      )}

      <Card style={{ marginBottom: 16 }}>
        <TokenMeter meter={meter} compact={false} />
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          <strong>How billing works:</strong> your plan includes a monthly token pool (best for VPS/Qwen).
          Premium Claude &amp; Grok always bill your credit wallet at the public rates below.
          After the pool is used, further VPS usage also draws credits.
        </Typography.Paragraph>
      </Card>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={24} md={8}>
          <Card title="Credit wallet">
            <Statistic prefix="$" precision={2} value={balance?.credits ?? 0} />
            <Space style={{ marginTop: 12 }}>
              <InputNumber min={5} max={1000} prefix="$" value={amount} onChange={setAmount} />
              <Button type="primary" onClick={topup} loading={busy}>Top up</Button>
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
          <Card title="Current plan">
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
                title={p.name}
                extra={p.price ? `$${p.price}/mo` : 'Free'}
                style={p.highlight ? { borderColor: '#1668dc' } : undefined}
              >
                <p>{p.blurb}</p>
                <Tag color="processing" style={{ marginBottom: 8 }}>
                  {(p.tokens_included || 0).toLocaleString()} tokens/mo
                </Tag>
                <ul style={{ paddingLeft: 18, marginBottom: 12 }}>
                  {(p.features || []).map(f => <li key={f}>{f}</li>)}
                </ul>
                <Button
                  type={balance?.plan === key ? 'default' : 'primary'}
                  disabled={balance?.plan === key}
                  onClick={() => choose(key)}
                  block
                >
                  {balance?.plan === key ? 'Current plan' : (p.price ? 'Upgrade' : 'Select')}
                </Button>
              </Card>
            </List.Item>
          )}
        />
      </Card>

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
