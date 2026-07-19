import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Card, Tabs, Form, Input, Select, Button, Space, Typography, Tag, Alert, List,
  Empty, Spin, message, Switch, Divider, Row, Col, Statistic,
} from 'antd'
import {
  PhoneOutlined, MessageOutlined, MailOutlined, ThunderboltOutlined,
  UserOutlined, RobotOutlined, ShoppingOutlined, HistoryOutlined,
  CheckCircleOutlined, WarningOutlined, PlayCircleOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import PageShell from '../components/PageShell'
import PageHeader from '../components/PageHeader'

const { Text, Paragraph, Title } = Typography
const { TextArea } = Input

const CHANNELS = [
  { key: 'call', label: 'Calls', icon: <PhoneOutlined />, color: 'purple' },
  { key: 'sms', label: 'SMS', icon: <MessageOutlined />, color: 'blue' },
  { key: 'email', label: 'Email', icon: <MailOutlined />, color: 'green' },
]

/**
 * Train Call / SMS / Email agents with a product pitch + human practice partner.
 * Practice = draft only (train). Live = real Twilio/email (credits).
 */
export default function CommsPractice() {
  const nav = useNavigate()
  const [channel, setChannel] = useState('call')
  const [status, setStatus] = useState(null)
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [live, setLive] = useState(false)
  const [result, setResult] = useState(null)
  const [catalogProducts, setCatalogProducts] = useState([])
  const [form] = Form.useForm()

  const applyCatalogProduct = (productId) => {
    const p = catalogProducts.find((x) => x.id === productId)
    if (!p) return
    form.setFieldsValue({
      catalog_product_id: p.id,
      product_name: p.name,
      price: p.price != null ? `${p.currency || 'USD'} ${p.price}` : form.getFieldValue('price'),
      benefits: p.benefits || p.description || form.getFieldValue('benefits'),
      audience: p.audience || form.getFieldValue('audience'),
      offer: p.offer || form.getFieldValue('offer'),
    })
  }

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      api('/comms/status'),
      api('/comms/history?limit=20'),
      api('/business/products?status=active&limit=50').catch(() => ({ products: [] })),
    ])
      .then(([s, h, prods]) => {
        setStatus(s)
        setHistory(h.items || [])
        const list = prods.products || []
        setCatalogProducts(list)
        const agents = s.agents || []
        const prefer = agents.find((a) => /sales|outreach|support/i.test(`${a.template_type} ${a.name}`))
          || agents[0]
        const firstProd = list[0]
        form.setFieldsValue({
          agent_id: prefer?.id,
          human_id: s.default_human_id,
          catalog_product_id: firstProd?.id,
          product_name: form.getFieldValue('product_name') || firstProd?.name || 'AI Business Assistant Pro',
          price: form.getFieldValue('price') || (firstProd ? `${firstProd.currency || 'USD'} ${firstProd.price}` : '$99/mo'),
          benefits: form.getFieldValue('benefits') || firstProd?.benefits || firstProd?.description || '10 agents, pipeline CRM, SMS/email/call automation',
          audience: form.getFieldValue('audience') || firstProd?.audience || 'Small business owners',
          offer: form.getFieldValue('offer') || firstProd?.offer || '14-day free trial, then Pro',
          objection: form.getFieldValue('objection') || 'Too expensive / already using another tool',
        })
      })
      .catch((e) => message.error(e?.message || 'Failed to load comms'))
      .finally(() => setLoading(false))
  }, [form])

  useEffect(() => { load() }, [load])

  const chStatus = status?.channels || {}
  const readyHint = useMemo(() => {
    if (channel === 'email') return chStatus.email
    return chStatus.twilio
  }, [channel, chStatus])

  const run = async () => {
    let values
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    if (live && !window.confirm(
      channel === 'call'
        ? 'Place a LIVE phone call via Twilio? This uses credits.'
        : channel === 'sms'
          ? 'Send a LIVE SMS via Twilio? This uses credits.'
          : 'Send a LIVE email? This uses credits.',
    )) {
      return
    }
    setRunning(true)
    setResult(null)
    try {
      const body = {
        channel,
        mode: live ? 'live' : 'practice',
        live_confirm: !!live,
        agent_id: values.agent_id || null,
        human_id: values.human_id || null,
        to: values.to || null,
        goal: values.goal || '',
        product: {
          name: values.product_name,
          price: values.price || '',
          benefits: values.benefits || '',
          audience: values.audience || '',
          offer: values.offer || '',
          objection: values.objection || '',
        },
      }
      const r = await api('/comms/practice/run', { method: 'POST', body })
      setResult(r)
      message.success(
        live
          ? (r.delivery?.ok ? 'Live delivery succeeded' : 'Draft ready — live delivery failed (check Twilio/email)')
          : 'Practice script ready — saved to agent training',
      )
      api('/comms/history?limit=20').then((h) => setHistory(h.items || [])).catch(() => {})
    } catch (e) {
      message.error(e?.message || 'Practice run failed')
    } finally {
      setRunning(false)
    }
  }

  if (loading && !status) {
    return (
      <PageShell>
        <Card className="aba-soft-card"><Spin tip="Loading Calls / SMS / Email…" /></Card>
      </PageShell>
    )
  }

  const agentOpts = (status?.agents || []).map((a) => ({
    value: a.id,
    label: `${a.name} (${a.template_type || a.hierarchy_role || 'agent'})`,
  }))
  const humanOpts = (status?.humans || []).map((h) => ({
    value: h.id,
    label: `${h.name}${h.is_my_human ? ' · My Human' : ''}${h.phone ? ` · ${h.phone}` : ''}${h.email ? ` · ${h.email}` : ''}`,
  }))

  return (
    <PageShell>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Card className="aba-soft-card" styles={{ body: { paddingBlock: 16 } }}>
          <PageHeader
            title={(
              <Space wrap>
                <PhoneOutlined />
                Calls · SMS · Email
              </Space>
            )}
            subtitle="Train sales agents with a product pitch. Practice with a human partner, then go live when ready."
            style={{ marginBottom: 0 }}
            extra={(
              <Space wrap>
                <Button onClick={() => nav('/humans')}>Team / Humans</Button>
                <Button onClick={() => nav('/settings')}>Keys (Twilio / Email)</Button>
                <Button onClick={() => nav('/console')}>Console</Button>
              </Space>
            )}
          />
        </Card>

        <Row gutter={[12, 12]}>
          <Col xs={24} sm={8}>
            <Card size="small" className="aba-soft-card aba-stat-card">
              <Statistic
                title="Twilio (SMS / Calls)"
                value={chStatus.twilio?.ready ? 'Ready' : 'Not set'}
                prefix={chStatus.twilio?.ready ? <CheckCircleOutlined style={{ color: '#16a34a' }} /> : <WarningOutlined style={{ color: '#d97706' }} />}
              />
            </Card>
          </Col>
          <Col xs={24} sm={8}>
            <Card size="small" className="aba-soft-card aba-stat-card">
              <Statistic
                title="Email (SMTP / Resend)"
                value={chStatus.email?.ready ? 'Ready' : 'Not set'}
                prefix={chStatus.email?.ready ? <CheckCircleOutlined style={{ color: '#16a34a' }} /> : <WarningOutlined style={{ color: '#d97706' }} />}
              />
            </Card>
          </Col>
          <Col xs={24} sm={8}>
            <Card size="small" className="aba-soft-card aba-stat-card">
              <Statistic
                title="Practice mode"
                value="Free draft"
                prefix={<ThunderboltOutlined style={{ color: '#1668dc' }} />}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>Live mode uses credits</Text>
            </Card>
          </Col>
        </Row>

        {!chStatus.twilio?.ready && (channel === 'call' || channel === 'sms') && (
          <Alert
            type="warning"
            showIcon
            message="Twilio not configured for live SMS/calls"
            description={chStatus.twilio?.hint || 'Add keys in Settings. Practice mode still works.'}
            action={<Button size="small" onClick={() => nav('/settings')}>Settings</Button>}
          />
        )}
        {!chStatus.email?.ready && channel === 'email' && (
          <Alert
            type="warning"
            showIcon
            message="Email not configured for live send"
            description={chStatus.email?.hint || 'Add RESEND_API_KEY or SMTP. Practice drafts still work.'}
            action={<Button size="small" onClick={() => nav('/settings')}>Settings</Button>}
          />
        )}

        <Card className="aba-soft-card" styles={{ body: { paddingTop: 8 } }}>
          <Tabs
            activeKey={channel}
            onChange={setChannel}
            centered
            items={CHANNELS.map((c) => ({
              key: c.key,
              label: (
                <span>
                  {c.icon} {c.label}
                </span>
              ),
            }))}
          />

          <Form
            form={form}
            layout="vertical"
            requiredMark="optional"
            style={{ marginTop: 8 }}
          >
            <Row gutter={[12, 0]}>
              <Col xs={24} md={12}>
                <Form.Item
                  name="agent_id"
                  label={<Space><RobotOutlined /> Training agent</Space>}
                  rules={[{ required: true, message: 'Pick an agent' }]}
                >
                  <Select
                    showSearch
                    optionFilterProp="label"
                    options={agentOpts}
                    placeholder="Sales / support agent"
                    notFoundContent={<Empty description="No agents — set up Core Team" />}
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item
                  name="human_id"
                  label={<Space><UserOutlined /> Practice with human</Space>}
                  rules={[{ required: true, message: 'Pick a human' }]}
                  extra="My Human or teammate — set phone/email on Team for live delivery"
                >
                  <Select
                    showSearch
                    optionFilterProp="label"
                    options={humanOpts}
                    placeholder="My Human"
                  />
                </Form.Item>
              </Col>
            </Row>

            <Card
              size="small"
              className="aba-soft-card"
              title={<Space><ShoppingOutlined /> Product to sell</Space>}
              style={{ marginBottom: 16 }}
            >
              <Row gutter={[12, 0]}>
                {catalogProducts.length > 0 && (
                  <Col xs={24}>
                    <Form.Item
                      name="catalog_product_id"
                      label="From your catalogue (company-linked)"
                      extra="Business → Products — picks name, price, tags context"
                    >
                      <Select
                        allowClear
                        showSearch
                        optionFilterProp="label"
                        placeholder="Select a product"
                        onChange={applyCatalogProduct}
                        options={catalogProducts.map((p) => ({
                          value: p.id,
                          label: `${p.name}${p.company_name ? ` · ${p.company_name}` : ''}${(p.tags || []).length ? ` · ${(p.tags || []).join(', ')}` : ''}`,
                        }))}
                      />
                    </Form.Item>
                  </Col>
                )}
                <Col xs={24} sm={12}>
                  <Form.Item name="product_name" label="Product name" rules={[{ required: true }]}>
                    <Input placeholder="e.g. AI Business Assistant Pro" />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item name="price" label="Price">
                    <Input placeholder="$99/mo" />
                  </Form.Item>
                </Col>
                <Col xs={24}>
                  <Form.Item name="benefits" label="Benefits">
                    <TextArea rows={2} placeholder="Key benefits for the pitch" />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item name="audience" label="Audience">
                    <Input placeholder="Who is this for?" />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item name="offer" label="Offer / CTA">
                    <Input placeholder="Trial, discount, book a demo…" />
                  </Form.Item>
                </Col>
                <Col xs={24}>
                  <Form.Item name="objection" label="Objection to practice">
                    <Input placeholder="Too expensive, using competitor…" />
                  </Form.Item>
                </Col>
              </Row>
            </Card>

            <Form.Item name="goal" label="Extra coaching goal (optional)">
              <Input placeholder="e.g. Book a demo this week; keep under 30 seconds for SMS" />
            </Form.Item>

            <Form.Item
              name="to"
              label={channel === 'email' ? 'Override email (optional)' : 'Override phone E.164 (optional)'}
              extra="Leave blank to use the human’s phone/email"
            >
              <Input placeholder={channel === 'email' ? 'you@example.com' : '+15551234567'} />
            </Form.Item>

            <Card size="small" className="aba-soft-card" style={{ marginBottom: 16 }}>
              <Space wrap style={{ width: '100%', justifyContent: 'space-between' }}>
                <div>
                  <Text strong>Mode: </Text>
                  <Tag color={live ? 'red' : 'blue'}>{live ? 'LIVE (credits)' : 'Practice (train only)'}</Tag>
                  <Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
                    {live
                      ? 'Real Twilio call/SMS or email. Confirm before send.'
                      : 'Generates script, saves to agent memory — no delivery charge.'}
                  </Paragraph>
                </div>
                <Space>
                  <Text>Practice</Text>
                  <Switch checked={live} onChange={setLive} checkedChildren="Live" unCheckedChildren="Draft" />
                  <Text>Live</Text>
                </Space>
              </Space>
            </Card>

            <Space wrap style={{ width: '100%' }}>
              <Button
                type="primary"
                size="large"
                icon={live ? <ThunderboltOutlined /> : <PlayCircleOutlined />}
                loading={running}
                onClick={run}
                className="aba-spawn-agent-btn"
                block={false}
                style={{ minWidth: 200 }}
              >
                {live
                  ? (channel === 'call' ? 'Draft + place call' : channel === 'sms' ? 'Draft + send SMS' : 'Draft + send email')
                  : (channel === 'call' ? 'Train call script' : channel === 'sms' ? 'Train SMS' : 'Train email')}
              </Button>
              <Button size="large" onClick={() => { form.resetFields(); load() }}>
                Reset
              </Button>
              {!agentOpts.length && (
                <Button type="link" onClick={() => nav('/console')}>Set up Core Team first</Button>
              )}
            </Space>
          </Form>
        </Card>

        {result && (
          <Card
            className="aba-soft-card"
            title={(
              <Space wrap>
                <CheckCircleOutlined style={{ color: '#16a34a' }} />
                Result · {result.channel} · {result.mode}
                {result.delivery && (
                  <Tag color={result.delivery.ok ? 'success' : 'error'}>
                    Live: {result.delivery.ok ? 'delivered' : 'failed'}
                  </Tag>
                )}
              </Space>
            )}
          >
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Text type="secondary">
                Agent <Text strong>{result.agent?.name}</Text>
                {' · '}
                Human <Text strong>{result.human?.name}</Text>
                {result.product?.name ? ` · Product ${result.product.name}` : ''}
              </Text>
              {result.draft?.subject && channel === 'email' && (
                <div>
                  <Text type="secondary">Subject</Text>
                  <Title level={5} style={{ marginTop: 0 }}>{result.draft.subject}</Title>
                </div>
              )}
              <div>
                <Text type="secondary">
                  {channel === 'call' ? 'Call script' : channel === 'sms' ? 'SMS body' : 'Email body'}
                </Text>
                <Card size="small" style={{ marginTop: 6, background: '#f8fafc' }}>
                  <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                    {channel === 'sms'
                      ? (result.draft?.short_version || result.draft?.script)
                      : result.draft?.script}
                  </Paragraph>
                </Card>
              </div>
              {!!(result.draft?.talking_points || []).length && (
                <div>
                  <Text type="secondary">Talking points</Text>
                  <ul style={{ marginTop: 6, paddingLeft: 18 }}>
                    {result.draft.talking_points.map((t, i) => (
                      <li key={i}>{t}</li>
                    ))}
                  </ul>
                </div>
              )}
              {result.draft?.objection_reply && (
                <Alert type="info" showIcon message="Objection reply" description={result.draft.objection_reply} />
              )}
              {result.draft?.cta && (
                <Tag color="blue">CTA: {result.draft.cta}</Tag>
              )}
              {result.delivery?.detail && (
                <Alert
                  type={result.delivery.ok ? 'success' : 'error'}
                  showIcon
                  message="Delivery"
                  description={result.delivery.detail}
                />
              )}
              {result.hint && <Alert type="info" showIcon message={result.hint} />}
              {result.usage && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  Usage: {result.usage.tokens} tokens · {result.usage.bill_source}
                  {result.usage.cost != null ? ` · $${Number(result.usage.cost).toFixed(4)}` : ''}
                </Text>
              )}
              <Space wrap>
                <Button
                  type="primary"
                  onClick={() => result.agent?.id && nav(`/console/${result.agent.id}`)}
                >
                  Open agent chat
                </Button>
                <Button onClick={() => nav('/humans')}>Open human inbox</Button>
              </Space>
            </Space>
          </Card>
        )}

        <Card
          className="aba-soft-card"
          title={<Space><HistoryOutlined /> Recent practice</Space>}
          extra={<Button type="link" size="small" onClick={load}>Refresh</Button>}
        >
          {history.length === 0 ? (
            <Empty description="No practice runs yet — train a call, SMS, or email above" />
          ) : (
            <List
              dataSource={history}
              renderItem={(item) => (
                <List.Item className="aba-click-row">
                  <List.Item.Meta
                    avatar={
                      item.channel === 'call' ? <PhoneOutlined />
                        : item.channel === 'sms' ? <MessageOutlined />
                          : <MailOutlined />
                    }
                    title={(
                      <Space wrap>
                        <Text strong>{item.title}</Text>
                        <Tag>{item.channel}</Tag>
                        <Tag color={item.mode === 'live' ? 'red' : 'blue'}>{item.mode}</Tag>
                        {item.delivery_ok === true && <Tag color="success">sent</Tag>}
                        {item.delivery_ok === false && <Tag color="error">failed</Tag>}
                      </Space>
                    )}
                    description={item.preview || item.product || '—'}
                  />
                </List.Item>
              )}
            />
          )}
        </Card>
      </Space>
    </PageShell>
  )
}
