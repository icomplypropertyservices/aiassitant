import React, { useEffect, useState } from 'react'
import {
  Card, Form, Input, Button, Tabs, message, Typography, Row, Col, Tag, List, Space,
} from 'antd'
import { RobotOutlined, CheckOutlined } from '@ant-design/icons'
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
      const data = await api(`/auth/${tab === 'login' ? 'login' : 'register'}`, {
        method: 'POST',
        body: values,
      })
      setAuth(data.token, data.user)
      if (data.preferred_company_name) {
        localStorage.setItem('preferred_company_name', data.preferred_company_name)
      }
      if (data.user.needs_subscription) {
        message.success('Account ready — choose a plan to continue')
        nav('/subscribe')
      } else {
        nav('/')
      }
    } catch (e) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  const planList = Object.entries(plans).filter(([, p]) => p.public !== false)

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(160deg,#0b1f3a 0%,#1668dc 55%,#f0f2f5 55%)', padding: '32px 16px' }}>
      <div style={{ maxWidth: 1100, margin: '0 auto' }}>
        <div style={{ textAlign: 'center', color: '#fff', marginBottom: 28 }}>
          <RobotOutlined style={{ fontSize: 40 }} />
          <Typography.Title level={2} style={{ color: '#fff', marginTop: 8 }}>
            AI Business Assistant
          </Typography.Title>
          <Typography.Paragraph style={{ color: 'rgba(255,255,255,0.85)', maxWidth: 560, margin: '0 auto' }}>
            Subscribers organise work as <strong>Company → Projects → Tasks</strong>,
            with a clear monthly token meter and fair public pricing.
          </Typography.Paragraph>
        </div>

        <Row gutter={[24, 24]} align="stretch">
          <Col xs={24} md={10}>
            <Card style={{ borderRadius: 12 }}>
              <Tabs
                activeKey={tab}
                onChange={setTab}
                centered
                items={[
                  { key: 'login', label: 'Sign in' },
                  { key: 'register', label: 'Create account' },
                ]}
              />
              <Form layout="vertical" onFinish={submit}>
                {tab === 'register' && (
                  <>
                    <Form.Item name="name" label="Your name">
                      <Input placeholder="Jane Smith" />
                    </Form.Item>
                    <Form.Item name="company_name" label="Company name">
                      <Input placeholder="Acme Electrical Ltd" />
                    </Form.Item>
                  </>
                )}
                <Form.Item name="email" label="Email" rules={[{ required: true, type: 'email' }]}>
                  <Input placeholder="you@business.com" />
                </Form.Item>
                <Form.Item name="password" label="Password" rules={[{ required: true, min: 6 }]}>
                  <Input.Password placeholder="At least 6 characters" />
                </Form.Item>
                <Button type="primary" htmlType="submit" block size="large" loading={loading}>
                  {tab === 'login' ? 'Sign in' : 'Create account & choose plan'}
                </Button>
              </Form>
              <Typography.Paragraph type="secondary" style={{ marginTop: 16, marginBottom: 0, fontSize: 12 }}>
                After sign-up you’ll pick a subscription (trial, starter, pro…). Demo admin: admin@local / admin123
              </Typography.Paragraph>
            </Card>
          </Col>

          <Col xs={24} md={14}>
            <Card
              title="Plans for public launch"
              extra={<Link to="/subscribe">Compare →</Link>}
              style={{ borderRadius: 12, height: '100%' }}
            >
              <List
                dataSource={planList}
                locale={{ emptyText: 'Loading plans…' }}
                renderItem={([key, p]) => (
                  <List.Item>
                    <List.Item.Meta
                      title={
                        <Space>
                          <span>{p.name}</span>
                          {p.highlight && <Tag color="blue">Popular</Tag>}
                          <Tag color="green">
                            {p.price ? `$${p.price}/mo` : 'Free'}
                          </Tag>
                        </Space>
                      }
                      description={
                        <div>
                          <div>{p.blurb}</div>
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            {(p.tokens_included || 0).toLocaleString()} tokens/mo · {p.companies} company · {p.projects} projects · {p.agents} agents
                          </Typography.Text>
                        </div>
                      }
                    />
                    <div>
                      {(p.features || []).slice(0, 2).map(f => (
                        <div key={f} style={{ fontSize: 12, color: '#595959' }}>
                          <CheckOutlined style={{ color: '#52c41a', marginRight: 6 }} />{f}
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
