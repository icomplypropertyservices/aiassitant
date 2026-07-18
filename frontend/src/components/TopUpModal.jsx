import React, { useEffect, useState } from 'react'
import { Modal, Button, Space, Typography, Tag, InputNumber, Alert, Row, Col } from 'antd'
import {
  ThunderboltOutlined, RocketOutlined, CrownOutlined, WalletOutlined, FireOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, IS_NATIVE } from '../api'
import { hapticWarning, hapticMedium, notifyLocal } from '../native'

const { Title, Paragraph, Text } = Typography

/**
 * Salesy low-balance / auto-top-up modal.
 */
export default function TopUpModal({ open, meter, onClose, onTopped }) {
  const nav = useNavigate()
  const [amount, setAmount] = useState(25)
  const [busy, setBusy] = useState(false)
  const [autoOn, setAutoOn] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!open || !meter) return
    const sug = meter.auto_topup?.amount || meter.suggested_amounts?.[1] || 25
    setAmount(sug)
    setAutoOn(!!meter.auto_topup?.enabled)
    setErr('')
    hapticWarning()
    notifyLocal({
      title: meter.headline || 'Power up your agents',
      body: meter.sales_message || 'Token pool running low — top up to stay live.',
    })
  }, [open, meter])

  if (!meter) return null

  const urgency = meter.urgency || (meter.hard_block ? 'critical' : meter.warn ? 'medium' : 'ok')
  const colors = {
    critical: { border: '#dc2626', tag: 'error', icon: <FireOutlined /> },
    high: { border: '#ea580c', tag: 'orange', icon: <ThunderboltOutlined /> },
    medium: { border: '#d97706', tag: 'gold', icon: <RocketOutlined /> },
    ok: { border: '#1668dc', tag: 'blue', icon: <WalletOutlined /> },
  }
  const theme = colors[urgency] || colors.medium

  const topup = async (amt) => {
    const a = Number(amt || amount)
    if (IS_NATIVE) {
      window.open('https://aiassitant-nu.vercel.app/billing', '_blank')
      return
    }
    setBusy(true)
    setErr('')
    hapticMedium()
    try {
      if (autoOn && !meter.auto_topup?.enabled) {
        await api('/billing/auto-topup', {
          method: 'PUT',
          body: {
            enabled: true,
            amount: a,
            threshold_credits: meter.auto_topup?.threshold_credits ?? 5,
            token_pct: meter.auto_topup?.token_pct ?? 85,
          },
        })
      }
      const r = await api('/billing/topup', { method: 'POST', body: { amount: a } })
      if (r.checkout_url) {
        window.location.href = r.checkout_url
        return
      }
      onTopped?.(r)
      onClose?.()
    } catch (e) {
      setErr(e.message || 'Top-up failed')
    } finally {
      setBusy(false)
    }
  }

  const enableAutoAndPay = async () => {
    setBusy(true)
    setErr('')
    try {
      await api('/billing/auto-topup', {
        method: 'PUT',
        body: {
          enabled: true,
          amount,
          threshold_credits: 5,
          token_pct: 85,
        },
      })
      setAutoOn(true)
      const t = await api('/billing/auto-topup/trigger', { method: 'POST', body: {} })
      if (t.checkout_url) {
        window.location.href = t.checkout_url
        return
      }
      if (t.dev_mode) {
        onTopped?.(t)
        onClose?.()
      } else if (t.skipped) {
        await topup(amount)
      }
    } catch (e) {
      // Fall back to manual top-up checkout
      try {
        await topup(amount)
      } catch (e2) {
        setErr(e2.message || e.message)
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={480}
      centered
      destroyOnClose
      styles={{
        content: { borderTop: `4px solid ${theme.border}`, borderRadius: 16 },
      }}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 36, color: theme.border, marginBottom: 8 }}>{theme.icon}</div>
          <Tag color={theme.tag} style={{ marginBottom: 8 }}>
            {urgency === 'critical' ? 'AGENTS OFFLINE RISK' : urgency === 'high' ? 'ALMOST EMPTY' : 'RUNNING LOW'}
          </Tag>
          <Title level={3} style={{ margin: '0 0 8px', letterSpacing: '-0.02em' }}>
            {meter.headline || "Don't let your agents go quiet"}
          </Title>
          <Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 15 }}>
            {meter.sales_message || meter.message || 'Top up credits to keep chat, agents, and media running.'}
          </Paragraph>
        </div>

        <Row gutter={12} style={{ textAlign: 'center' }}>
          <Col span={12}>
            <div style={{ background: '#f8fafc', borderRadius: 12, padding: 12 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>Tokens used</Text>
              <div style={{ fontWeight: 700, fontSize: 18 }}>
                {Math.round(meter.usage_percent || 0)}%
              </div>
            </div>
          </Col>
          <Col span={12}>
            <div style={{ background: '#f8fafc', borderRadius: 12, padding: 12 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>Wallet</Text>
              <div style={{ fontWeight: 700, fontSize: 18 }}>
                ${Number(meter.credits || 0).toFixed(2)}
              </div>
            </div>
          </Col>
        </Row>

        <div>
          <Text strong>Quick top-up</Text>
          <Space wrap style={{ marginTop: 8, width: '100%' }}>
            {(meter.suggested_amounts || [10, 25, 50, 100]).map((a) => (
              <Button
                key={a}
                type={amount === a ? 'primary' : 'default'}
                size="large"
                onClick={() => setAmount(a)}
              >
                ${a}
              </Button>
            ))}
            <InputNumber
              min={5}
              max={1000}
              prefix="$"
              value={amount}
              onChange={setAmount}
              size="large"
            />
          </Space>
        </div>

        {err && <Alert type="error" showIcon message={err} />}

        {meter.auto_checkout_url && (
          <Button
            type="primary"
            size="large"
            block
            icon={<ThunderboltOutlined />}
            onClick={() => { window.location.href = meter.auto_checkout_url }}
            style={{ height: 48, fontWeight: 600, background: '#16a34a' }}
          >
            Complete auto top-up checkout →
          </Button>
        )}

        <Button
          type="primary"
          size="large"
          block
          loading={busy}
          icon={<RocketOutlined />}
          onClick={() => topup(amount)}
          style={{ height: 48, fontWeight: 600 }}
        >
          {meter.cta || `Power up — add $${amount} credits`}
        </Button>

        <Button
          size="large"
          block
          loading={busy}
          icon={<ThunderboltOutlined />}
          onClick={enableAutoAndPay}
        >
          Enable auto top-up (${amount}) &amp; refill now
        </Button>

        {meter.upgrade_teaser && (
          <Alert
            type="success"
            showIcon
            icon={<CrownOutlined />}
            message="Or upgrade your plan"
            description={
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <span>{meter.upgrade_teaser}</span>
                <Button
                  type="link"
                  style={{ padding: 0 }}
                  onClick={() => {
                    onClose?.()
                    nav('/billing')
                  }}
                >
                  See plans &amp; upgrade →
                </Button>
              </Space>
            }
          />
        )}

        <Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12, textAlign: 'center' }}>
          Card checkout is secure via Stripe. Crypto top-ups available on Billing.
          Auto top-up starts a checkout when you run low — you confirm each refill.
        </Paragraph>

        <Button type="text" block onClick={onClose} disabled={meter.hard_block && urgency === 'critical'}>
          {meter.hard_block ? 'I understand — continue to Billing' : 'Not now'}
        </Button>
        {meter.hard_block && (
          <Button type="link" block onClick={() => { onClose?.(); nav('/billing') }}>
            Open Billing
          </Button>
        )}
      </Space>
    </Modal>
  )
}
