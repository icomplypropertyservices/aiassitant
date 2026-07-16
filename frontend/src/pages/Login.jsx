import React, { useEffect, useState } from 'react'
import {
  Card, Form, Input, Button, Tabs, message, Typography, Row, Col, Tag, List, Space,
} from 'antd'
import {
  RobotOutlined, CheckOutlined, ThunderboltOutlined,
  TeamOutlined, SafetyCertificateOutlined,
} from '@ant-design/icons'
import { useNavigate, Link } from 'react-router-dom'
import { api, setAuth, getToken, getUser } from '../api'

export default function Login() {
  const nav = useNavigate()
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState('login')
  const [plans, setPlans] = useState({})

  useEffect(() => {
    const u = getUser()
    if (getToken() && u) {
      nav(u.needs_subscription ? '/subscribe' : '/', { replace: true })
    }
    api('/billing/plans').then(setPlans).catch(() => {})
  }, [])

  const submit = async (values) => {
    setLoading(true)
    try {
      const payload = {
        email: (values.email || '').trim(),
        password: values.password,
      }
      if (tab === 'register') {
        payload.name = (values.name || '').trim()
        payload.company_name = (values.company_name || '').trim()
      }
      const data = await api(`/auth/${tab === 'login' ? 'login' : 'register'}`, {
        method: 'POST',
        body: payload,
      })
      if (!data?.token || !data?.user) {
        throw new Error('Login response missing token — check API deployment')
      }
      setAuth(data.token, data.user)
      if (data.preferred_company_name) {
        localStorage.setItem('preferred_company_name', data.preferred_company_name)
      }
      message.success(tab === 'login' ? 'Signed in' : 'Account created')
      if (data.user.needs_subscription) {
        nav('/subscribe', { replace: true })
      } else {
        nav('/', { replace: true })
      }
    } catch (e) {
      message.error(e?.message || 'Sign-in failed')
    } finally {
      setLoading(false)
    }
  }

  const planList = Object.entries(plans).filter(
    ([key, p]) => p.public !== false && key !== 'pay_as_you_go' && key !== 'none',
  )

  const unit = (n, singular) => `${n} ${singular}${Number(n) === 1 ? '' : 's'}`

  return (
    <div className="aba-auth-shell">
      <div style={{ maxWidth: 1120, margin: '0 auto' }}>
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: 16,
              margin: '0 auto 12px',
              display: 'grid',
              placeItems: 'center',
              background: 'linear-gradient(135deg,#3b82f6,#1d4ed8)',
              boxShadow: '0 8px 24px rgba(37,99,235,0.35)',
              color: '#fff',
              fontSize: 26,
            }}
          >
            <RobotOutlined />
          </div>
          <Typography.Title level={2} style={{ color: '#fff', margin: '0 0 8px', letterSpacing: '-0.03em' }}>
            AI Business Assistant
          </Typography.Title>
          <Typography.Paragraph style={{ color: 'rgba(255,255,255,0.88)', maxWidth: 560, margin: '0 auto 14px' }}>
            Run companies, projects and AI agents in one workspace — with a clear token meter
            and fair public pricing.
          </Typography.Paragraph>
          {import.meta.env.VITE_SANDBOX === '1' && (
            <Tag color="gold" style={{ marginBottom: 8 }}>Sandbox build · test payments only</Tag>
          )}
          <Space wrap style={{ justifyContent: 'center' }}>
            <span className="aba-feature-pill"><TeamOutlined /> Company → Projects → Tasks</span>
            <span className="aba-feature-pill"><ThunderboltOutlined /> Live token meter</span>
            <span className="aba-feature-pill"><SafetyCertificateOutlined /> Card &amp; crypto pay</span>
          </Space>
        </div>

        <Row gutter={[24, 24]} align="stretch">
          <Col xs={24} md={10}>
            <Card className="aba-auth-card" style={{ borderRadius: 16 }}>
              <Tabs
                activeKey={tab}
                onChange={setTab}
                centered
                items={[
                  { key: 'login', label: 'Sign in' },
                  { key: 'register', label: 'Create account' },
                ]}
              />
              <Form layout="vertical" onFinish={submit} requiredMark={false} size="large">
                {tab === 'register' && (
                  <>
                    <Form.Item name="name" label="Your name">
                      <Input placeholder="Jane Smith" autoComplete="name" />
                    </Form.Item>
                    <Form.Item name="company_name" label="Company name">
                      <Input placeholder="Acme Electrical Ltd" autoComplete="organization" />
                    </Form.Item>
                  </>
                )}
                <Form.Item name="email" label="Email" rules={[{ required: true, type: 'email' }]}>
                  <Input placeholder="you@business.com" autoComplete="email" />
                </Form.Item>
                <Form.Item name="password" label="Password" rules={[{ required: true, min: 6 }]}>
                  <Input.Password placeholder="At least 6 characters" autoComplete={tab === 'login' ? 'current-password' : 'new-password'} />
                </Form.Item>
                <Button type="primary" htmlType="submit" block size="large" loading={loading}>
                  {tab === 'login' ? 'Sign in' : 'Create account & choose plan'}
                </Button>
              </Form>
              <Typography.Paragraph type="secondary" style={{ marginTop: 16, marginBottom: 0, fontSize: 12, textAlign: 'center' }}>
                After sign-up, choose a plan. Pay with card or crypto (ETH / SOL / XRP).
              </Typography.Paragraph>
            </Card>
          </Col>

          <Col xs={24} md={14}>
            <Card
              className="aba-auth-card aba-soft-card"
              title="Plans"
              extra={<Link to="/subscribe">View plans →</Link>}
              style={{ borderRadius: 16, height: '100%' }}
            >
              <List
                dataSource={planList}
                locale={{ emptyText: 'Loading plans…' }}
                split
                renderItem={([key, p]) => (
                  <List.Item style={{ padding: '14px 0' }}>
                    <List.Item.Meta
                      title={
                        <Space wrap size={6}>
                          <Typography.Text strong>{p.name}</Typography.Text>
                          {p.highlight && <Tag color="blue">Popular</Tag>}
                          <Tag color={p.price ? 'geekblue' : 'green'}>
                            {p.price ? `$${p.price}/mo` : 'Free'}
                          </Tag>
                        </Space>
                      }
                      description={
                        <div>
                          <div style={{ marginBottom: 4, color: '#475569' }}>{p.blurb}</div>
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            {(p.tokens_included || 0).toLocaleString()} tokens/mo
                            {' · '}{unit(p.companies, 'company')}
                            {' · '}{unit(p.projects, 'project')}
                            {' · '}{unit(p.agents, 'agent')}
                          </Typography.Text>
                        </div>
                      }
                    />
                    <div style={{ minWidth: 160 }}>
                      {(p.features || []).slice(0, 2).map(f => (
                        <div key={f} style={{ fontSize: 12, color: '#64748b', lineHeight: 1.55 }}>
                          <CheckOutlined style={{ color: '#16a34a', marginRight: 6 }} />{f}
                        </div>
                      ))}
                    </div>
                  </List.Item>
                )}
              />
            </Card>
          </Col>
        </Row>
      </div>
    </div>
  )
}
