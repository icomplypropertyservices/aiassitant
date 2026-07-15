import React, { useEffect, useState } from 'react'
import {
  Card, Row, Col, Button, Typography, Tag, List, Input, Space, message, Alert,
} from 'antd'
import { CheckOutlined, RobotOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, getToken, getUser, setAuth, clearAuth, IS_NATIVE } from '../api'

export default function Subscribe() {
  const nav = useNavigate()
  const [plans, setPlans] = useState({})
  const [busy, setBusy] = useState(null)
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
  }, [])

  const choose = async (planKey) => {
    if (IS_NATIVE) {
      // App Store guideline 3.1: digital subscriptions — prefer web account management for multi-platform SaaS
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
      const me = await api('/auth/me')
      setAuth(getToken(), me)
      localStorage.removeItem('preferred_company_name')
      message.success(`You're on ${me.plan_name || me.plan || planKey}`)
      nav('/')
    } catch (e) {
      message.error(e.message)
    } finally {
      setBusy(null)
    }
  }

  const entries = Object.entries(plans)

  return (
    <div style={{ minHeight: '100vh', background: '#f5f7fb', padding: '40px 16px' }}>
      <div style={{ maxWidth: 1100, margin: '0 auto' }}>
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <RobotOutlined style={{ fontSize: 36, color: '#1668dc' }} />
          <Typography.Title level={2} style={{ marginTop: 8 }}>Choose your subscription</Typography.Title>
          <Typography.Paragraph type="secondary">
            Signed in as <strong>{user?.email}</strong>. Pick a plan to unlock
            companies, projects, tasks and AI agents. You can change later on Billing.
          </Typography.Paragraph>
          <Space style={{ marginBottom: 8 }}>
            <Typography.Text>First company name</Typography.Text>
            <Input
              style={{ width: 280 }}
              placeholder="My company"
              value={companyName}
              onChange={e => setCompanyName(e.target.value)}
            />
          </Space>
        </div>

        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 20 }}
          message="Token meter is always visible"
          description="Each plan includes a monthly token pool for VPS/Qwen models. When the pool runs out (or you use Claude/Grok), usage draws from your credit wallet. Top up anytime."
        />

        <Row gutter={[16, 16]}>
          {entries.map(([key, p]) => (
            <Col xs={24} sm={12} lg={8} xl={6} key={key}>
              <Card
                hoverable
                style={{
                  height: '100%',
                  border: p.highlight ? '2px solid #1668dc' : undefined,
                  borderRadius: 12,
                }}
                title={
                  <Space>
                    {p.name}
                    {p.highlight && <Tag color="blue">Popular</Tag>}
                  </Space>
                }
                extra={
                  <Typography.Title level={4} style={{ margin: 0 }}>
                    {p.price ? `$${p.price}` : '$0'}
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>/mo</Typography.Text>
                  </Typography.Title>
                }
              >
                <Typography.Paragraph type="secondary">{p.blurb}</Typography.Paragraph>
                <Tag color="processing" style={{ marginBottom: 12 }}>
                  {(p.tokens_included || 0).toLocaleString()} tokens / month
                </Tag>
                <List
                  size="small"
                  dataSource={p.features || []}
                  renderItem={f => (
                    <List.Item style={{ padding: '4px 0', border: 'none' }}>
                      <CheckOutlined style={{ color: '#52c41a', marginRight: 8 }} /> {f}
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
                  {p.price ? 'Subscribe' : 'Start free'}
                </Button>
              </Card>
            </Col>
          ))}
        </Row>

        <div style={{ textAlign: 'center', marginTop: 24 }}>
          <Button type="link" onClick={() => { clearAuth(); nav('/login') }}>
            Sign out
          </Button>
        </div>
      </div>
    </div>
  )
}
