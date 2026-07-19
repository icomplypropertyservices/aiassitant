import React, { useEffect, useState } from 'react'
import {
  Modal, Button, Space, Typography, Tag, InputNumber, Alert, Row, Col, Divider, Statistic,
} from 'antd'
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
    critical: { border: '#dc2626', soft: '#fef2f2', tag: 'error', icon: <FireOutlined /> },
    high: { border: '#ea580c', soft: '#fff7ed', tag: 'orange', icon: <ThunderboltOutlined /> },
    medium: { border: '#d97706', soft: '#fffbeb', tag: 'gold', icon: <RocketOutlined /> },
    ok: { border: '#1668dc', soft: '#e8f1fc', tag: 'blue', icon: <WalletOutlined /> },
  }
  const theme = colors[urgency] || colors.medium

  const urgencyLabel =
    urgency === 'critical' ? 'Agents offline risk'
      : urgency === 'high' ? 'Almost empty'
        : 'Running low'

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
      className="aba-topup-modal"
      styles={{
        content: {
          borderTop: `4px solid ${theme.border}`,
          borderRadius: 16,
          overflow: 'hidden',
        },
        body: {
          padding: 0,
        },
      }}
    >
      <div className="aba-topup-body">
        {/* Header */}
        <header className="aba-topup-header">
          <div
            className="aba-topup-icon"
            style={{ background: theme.soft, color: theme.border }}
            aria-hidden
          >
            {theme.icon}
          </div>
          <Tag color={theme.tag} bordered={false} className="aba-topup-urgency">
            {urgencyLabel}
          </Tag>
          <Title level={3} className="aba-topup-title">
            {meter.headline || "Don't let your agents go quiet"}
          </Title>
          <Paragraph type="secondary" className="aba-topup-sub">
            {meter.sales_message || meter.message || 'Top up credits to keep chat, agents, and media running.'}
          </Paragraph>
        </header>

        {/* Stats */}
        <Row gutter={[12, 12]} className="aba-topup-stats">
          <Col span={12}>
            <div className="aba-topup-stat">
              <Statistic
                title="Tokens used"
                value={Math.round(meter.usage_percent || 0)}
                suffix="%"
                valueStyle={{ fontSize: 22, fontWeight: 700, color: theme.border }}
              />
            </div>
          </Col>
          <Col span={12}>
            <div className="aba-topup-stat">
              <Statistic
                title="Wallet"
                prefix="$"
                value={Number(meter.credits || 0).toFixed(2)}
                valueStyle={{ fontSize: 22, fontWeight: 700 }}
              />
            </div>
          </Col>
        </Row>

        {/* Amount picker */}
        <section className="aba-topup-amounts" aria-label="Top-up amount">
          <Text strong className="aba-topup-section-label">
            Quick top-up
          </Text>
          <div className="aba-topup-amount-row">
            {(meter.suggested_amounts || [10, 25, 50, 100]).map((a) => (
              <Button
                key={a}
                type={amount === a ? 'primary' : 'default'}
                size="large"
                className="aba-topup-amount-btn"
                onClick={() => setAmount(a)}
              >
                ${a}
              </Button>
            ))}
          </div>
          <InputNumber
            min={5}
            max={1000}
            prefix="$"
            value={amount}
            onChange={setAmount}
            size="large"
            className="aba-topup-custom"
            aria-label="Custom top-up amount"
          />
        </section>

        {err ? (
          <Alert
            type="error"
            showIcon
            message={err}
            className="aba-topup-alert"
          />
        ) : null}

        {/* Primary actions */}
        <Space direction="vertical" size={10} className="aba-topup-actions">
          {meter.auto_checkout_url && (
            <Button
              type="primary"
              size="large"
              block
              icon={<ThunderboltOutlined />}
              onClick={() => { window.location.href = meter.auto_checkout_url }}
              className="aba-topup-btn-success"
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
            className="aba-topup-btn-primary"
          >
            {meter.cta || `Power up — add $${amount} credits`}
          </Button>

          <Button
            size="large"
            block
            loading={busy}
            icon={<ThunderboltOutlined />}
            onClick={enableAutoAndPay}
            className="aba-topup-btn-secondary"
          >
            Enable auto top-up (${amount}) &amp; refill now
          </Button>
        </Space>

        {meter.upgrade_teaser ? (
          <Alert
            type="success"
            showIcon
            icon={<CrownOutlined />}
            className="aba-topup-upgrade"
            message="Or upgrade your plan"
            description={
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <span>{meter.upgrade_teaser}</span>
                <Button
                  type="link"
                  className="aba-topup-upgrade-link"
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
        ) : null}

        <Divider className="aba-topup-divider" />

        <footer className="aba-topup-footer">
          <Paragraph type="secondary" className="aba-topup-footnote">
            Card checkout is secure via Stripe. Crypto top-ups available on Billing.
            Auto top-up starts a checkout when you run low — you confirm each refill.
          </Paragraph>

          <Space direction="vertical" size={4} className="aba-topup-dismiss">
            <Button
              type="text"
              block
              onClick={onClose}
              disabled={meter.hard_block && urgency === 'critical'}
              className="aba-topup-dismiss-btn"
            >
              {meter.hard_block ? 'I understand — continue to Billing' : 'Not now'}
            </Button>
            {meter.hard_block && (
              <Button
                type="link"
                block
                onClick={() => { onClose?.(); nav('/billing') }}
              >
                Open Billing
              </Button>
            )}
          </Space>
        </footer>
      </div>
    </Modal>
  )
}
