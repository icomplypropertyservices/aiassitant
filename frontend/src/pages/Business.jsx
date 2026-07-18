import React, { useEffect, useMemo, useState } from 'react'
import {
  Card, Tabs, Table, Button, Space, Tag, Typography, Statistic, Row, Col, Input, Select,
  Modal, Form, InputNumber, message, Empty, Spin, Badge, Popconfirm, Tooltip,
} from 'antd'
import {
  ShopOutlined, TeamOutlined, PlusOutlined, ReloadOutlined, DollarOutlined,
  FunnelPlotOutlined, SearchOutlined, UserOutlined, HolderOutlined, CalendarOutlined,
} from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'

const { Title, Text } = Typography
const { TextArea } = Input

const STATUS_COLOR = {
  active: 'green', inactive: 'default', churned: 'red',
  open: 'processing', won: 'success', lost: 'error',
}

export default function Business() {
  const nav = useNavigate()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') || 'overview'
  const setTab = (k) => {
    const n = new URLSearchParams(params)
    n.set('tab', k)
    setParams(n)
  }

  const [loading, setLoading] = useState(true)
  const [overview, setOverview] = useState(null)
  const [customers, setCustomers] = useState([])
  const [total, setTotal] = useState(0)
  const [pipelines, setPipelines] = useState([])
  const [board, setBoard] = useState(null)
  const [pipelineId, setPipelineId] = useState(null)
  const [q, setQ] = useState('')
  const [statusFilter, setStatusFilter] = useState(undefined)
  const [humans, setHumans] = useState([])
  const [agents, setAgents] = useState([])
  const [companies, setCompanies] = useState([])

  const [custOpen, setCustOpen] = useState(false)
  const [dealOpen, setDealOpen] = useState(false)
  const [pipeOpen, setPipeOpen] = useState(false)
  const [diaryOpen, setDiaryOpen] = useState(false)
  const [selectedCustForDiary, setSelectedCustForDiary] = useState(null)
  const [custForm] = Form.useForm()
  const [dealForm] = Form.useForm()
  const [pipeForm] = Form.useForm()
  const [diaryForm] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [dragDeal, setDragDeal] = useState(null)
  const [upcomingDiary, setUpcomingDiary] = useState([])

  const loadOverview = async () => {
    const o = await api('/business/overview')
    setOverview(o)
    setPipelines(o.pipelines || [])
    if (!pipelineId && o.pipelines?.length) {
      const def = o.pipelines.find((p) => p.is_default) || o.pipelines[0]
      setPipelineId(def.id)
    }
  }

  const loadCustomers = async () => {
    const qs = new URLSearchParams()
    if (q) qs.set('q', q)
    if (statusFilter) qs.set('status', statusFilter)
    const r = await api(`/business/customers?${qs.toString()}`)
    setCustomers(r.customers || [])
    setTotal(r.total || 0)
  }

  const loadBoard = async (pid) => {
    const id = pid || pipelineId
    if (!id) return
    const r = await api(`/business/pipelines/${id}`)
    setBoard(r)
  }

  const load = async () => {
    setLoading(true)
    try {
      await loadOverview()
      await Promise.all([
        loadCustomers(),
        api('/humans/').then((r) => setHumans(r.humans || [])).catch(() => {}),
        api('/agents/').then((a) => setAgents(Array.isArray(a) ? a : [])).catch(() => {}),
        api('/org/companies').then((c) => setCompanies(Array.isArray(c) ? c : c.companies || [])).catch(() => {}),
        api('/business/diary?upcoming=true').then((d) => setUpcomingDiary(d.diary || [])).catch(() => {}),
      ])
    } catch (e) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])
  useEffect(() => {
    if (pipelineId) loadBoard(pipelineId)
  }, [pipelineId])

  const createCustomer = async (values) => {
    setSaving(true)
    try {
      const c = await api('/business/customers', { method: 'POST', body: values })
      message.success('Customer created')
      setCustOpen(false)
      custForm.resetFields()
      await loadCustomers()
      await loadOverview()
      nav(`/business/customers/${c.id}`)
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const createDeal = async (values) => {
    setSaving(true)
    try {
      await api('/business/deals', {
        method: 'POST',
        body: { ...values, pipeline_id: pipelineId },
      })
      message.success('Deal created')
      setDealOpen(false)
      dealForm.resetFields()
      loadBoard()
      loadOverview()
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const createPipeline = async (values) => {
    setSaving(true)
    try {
      const p = await api('/business/pipelines', { method: 'POST', body: values })
      message.success('Pipeline created')
      setPipeOpen(false)
      pipeForm.resetFields()
      await loadOverview()
      setPipelineId(p.id)
      setTab('pipeline')
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const onDropDeal = async (stageId) => {
    if (!dragDeal || dragDeal.stage_id === stageId) {
      setDragDeal(null)
      return
    }
    try {
      await api(`/business/deals/${dragDeal.id}/move`, {
        method: 'PUT',
        body: { stage_id: stageId },
      })
      message.success('Deal moved')
      loadBoard()
      loadOverview()
    } catch (e) {
      message.error(e.message)
    } finally {
      setDragDeal(null)
    }
  }

  const customerColumns = [
    {
      title: 'Customer',
      key: 'name',
      render: (_, r) => (
        <Button type="link" style={{ padding: 0, height: 'auto' }} onClick={() => nav(`/business/customers/${r.id}`)}>
          <Space>
            <UserOutlined />
            <div style={{ textAlign: 'left' }}>
              <div><strong>{r.name}</strong></div>
              <Text type="secondary" style={{ fontSize: 12 }}>{r.account_name || r.email || '—'}</Text>
            </div>
          </Space>
        </Button>
      ),
    },
    { title: 'Email', dataIndex: 'email', render: (v) => v || '—' },
    { title: 'Phone', dataIndex: 'phone', render: (v) => v || '—' },
    {
      title: 'Status',
      dataIndex: 'status',
      render: (s) => <Tag color={STATUS_COLOR[s] || 'default'}>{s}</Tag>,
    },
    {
      title: 'Tags',
      dataIndex: 'tags',
      render: (tags) => (tags || []).map((t) => <Tag key={t}>{t}</Tag>),
    },
    {
      title: 'Open deals',
      dataIndex: 'open_deals',
      width: 100,
    },
    {
      title: 'Pipeline $',
      dataIndex: 'pipeline_value',
      render: (v) => `$${Number(v || 0).toLocaleString()}`,
    },
    {
      title: 'Owner',
      render: (_, r) => r.owner_human_name || r.owner_agent_name || '—',
    },
  ]

  if (loading && !overview) {
    return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" tip="Loading business…" /></div>
  }

  const counts = overview?.counts || {}

  return (
    <div>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }} wrap>
        <div>
          <Title level={3} style={{ margin: 0 }}><ShopOutlined /> Business</Title>
          <Text type="secondary">Pipelines, customers, diary &amp; full records — your agents run this</Text>
        </div>
        <Space wrap>
          <Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button>
          <Button icon={<PlusOutlined />} onClick={() => setPipeOpen(true)}>New pipeline</Button>
          <Button icon={<CalendarOutlined />} onClick={() => { setSelectedCustForDiary(null); setDiaryOpen(true) }}>Arrange diary</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCustOpen(true)}>Add customer</Button>
        </Space>
      </Space>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}><Card><Statistic title="Customers" value={counts.customers || 0} prefix={<TeamOutlined />} suffix={<Text type="secondary" style={{ fontSize: 13 }}>/ {counts.customers_active || 0} active</Text>} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="Open deals" value={counts.deals_open || 0} prefix={<FunnelPlotOutlined />} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="Pipeline value" value={counts.pipeline_value || 0} prefix={<DollarOutlined />} precision={0} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="Won value" value={counts.won_value || 0} prefix={<DollarOutlined />} precision={0} valueStyle={{ color: '#52c41a' }} /></Card></Col>
      </Row>

      <Card>
        <Tabs
          activeKey={tab}
          onChange={setTab}
          items={[
            {
              key: 'overview',
              label: 'Overview',
              children: (
                <Row gutter={[16, 16]}>
                  <Col xs={24} md={12}>
                    <Card type="inner" title="Recent customers" extra={<Button type="link" onClick={() => setTab('customers')}>View all</Button>}>
                      <Table
                        size="small"
                        rowKey="id"
                        pagination={false}
                        dataSource={overview?.recent_customers || []}
                        columns={[
                          {
                            title: 'Name',
                            render: (_, r) => (
                              <Button type="link" style={{ padding: 0 }} onClick={() => nav(`/business/customers/${r.id}`)}>
                                {r.name}
                              </Button>
                            ),
                          },
                          { title: 'Account', dataIndex: 'account_name' },
                          { title: 'Status', dataIndex: 'status', render: (s) => <Tag color={STATUS_COLOR[s]}>{s}</Tag> },
                        ]}
                        locale={{ emptyText: 'No customers yet' }}
                      />
                    </Card>
                  </Col>
                  <Col xs={24} md={12}>
                    <Card type="inner" title="Pipelines" extra={<Button type="link" onClick={() => setTab('pipeline')}>Open board</Button>}>
                      {(overview?.pipelines || []).map((p) => (
                        <Card
                          key={p.id}
                          size="small"
                          hoverable
                          style={{ marginBottom: 8 }}
                          onClick={() => { setPipelineId(p.id); setTab('pipeline') }}
                        >
                          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                            <span>
                              <FunnelPlotOutlined /> <strong>{p.name}</strong>
                              {p.is_default && <Tag color="blue" style={{ marginLeft: 8 }}>Default</Tag>}
                            </span>
                            <span>
                              <Tag>{p.deal_count} deals</Tag>
                              <Tag color="gold">${Number(p.open_value || 0).toLocaleString()}</Tag>
                            </span>
                          </Space>
                        </Card>
                      ))}
                      {!overview?.pipelines?.length && <Empty description="No pipelines" />}
                    </Card>
                  </Col>
                  <Col xs={24} md={24}>
                    <Card type="inner" title="Upcoming diary / meetings" extra={<Button type="link" icon={<CalendarOutlined />} onClick={() => { setSelectedCustForDiary(null); setDiaryOpen(true) }}>Arrange new</Button>}>
                      {(upcomingDiary || []).length ? (
                        <Table
                          size="small"
                          rowKey="id"
                          pagination={false}
                          dataSource={upcomingDiary}
                          columns={[
                            { title: 'When', dataIndex: 'start_at', render: (v) => v ? new Date(v).toLocaleString() : 'TBD' },
                            { title: 'Customer', render: (_, r) => <Button type="link" style={{padding:0}} onClick={() => nav(`/business/customers/${r.customer_id}`)}>{r.customer_name}</Button> },
                            { title: 'Title', dataIndex: 'title' },
                            { title: 'Location', dataIndex: 'location', render: (v) => v || '—' },
                            { title: 'Owner', render: (_, r) => r.owner_human_name || r.owner_agent_name || '—' },
                          ]}
                          onRow={(r) => ({ onClick: () => nav(`/business/customers/${r.customer_id}`), style: { cursor: 'pointer' } })}
                        />
                      ) : <Text type="secondary">No upcoming diary items. Use “Arrange diary” to schedule meetings/calls for customers.</Text>}
                    </Card>
                  </Col>
                </Row>
              ),
            },
            {
              key: 'customers',
              label: <Badge count={total} offset={[12, 0]} size="small" color="#1668dc">Customers</Badge>,
              children: (
                <div>
                  <Space style={{ marginBottom: 12, width: '100%', justifyContent: 'space-between' }} wrap>
                    <Space wrap>
                      <Input
                        allowClear
                        prefix={<SearchOutlined />}
                        placeholder="Search name, email, account, tags…"
                        style={{ width: 280 }}
                        value={q}
                        onChange={(e) => setQ(e.target.value)}
                        onPressEnter={loadCustomers}
                      />
                      <Select
                        allowClear
                        placeholder="Status"
                        style={{ width: 140 }}
                        value={statusFilter}
                        onChange={setStatusFilter}
                        options={[
                          { value: 'active', label: 'Active' },
                          { value: 'inactive', label: 'Inactive' },
                          { value: 'churned', label: 'Churned' },
                        ]}
                      />
                      <Button onClick={loadCustomers}>Search</Button>
                    </Space>
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => setCustOpen(true)}>Add customer</Button>
                  </Space>
                  <Table
                    rowKey="id"
                    loading={loading}
                    dataSource={customers}
                    columns={customerColumns}
                    pagination={{ pageSize: 15, total }}
                    onRow={(r) => ({
                      onClick: () => nav(`/business/customers/${r.id}`),
                      style: { cursor: 'pointer' },
                    })}
                    locale={{ emptyText: 'No customers — add your first record' }}
                  />
                </div>
              ),
            },
            {
              key: 'pipeline',
              label: 'Pipeline',
              children: (
                <div>
                  <Space style={{ marginBottom: 12, width: '100%', justifyContent: 'space-between' }} wrap>
                    <Space wrap>
                      <Select
                        style={{ minWidth: 220 }}
                        value={pipelineId}
                        onChange={setPipelineId}
                        options={(overview?.pipelines || pipelines || []).map((p) => ({
                          value: p.id,
                          label: `${p.name}${p.is_default ? ' (default)' : ''}`,
                        }))}
                      />
                      <Button icon={<PlusOutlined />} onClick={() => {
                        dealForm.setFieldsValue({})
                        setDealOpen(true)
                      }} disabled={!pipelineId}>
                        Add deal
                      </Button>
                    </Space>
                    <Text type="secondary">
                      Drag deals between columns · click deal for customer
                    </Text>
                  </Space>

                  {!board ? (
                    <Spin />
                  ) : (
                    <div
                      style={{
                        display: 'flex',
                        gap: 12,
                        overflowX: 'auto',
                        paddingBottom: 12,
                        minHeight: 420,
                      }}
                    >
                      {(board.board || []).map((stage) => (
                        <div
                          key={stage.id}
                          onDragOver={(e) => e.preventDefault()}
                          onDrop={() => onDropDeal(stage.id)}
                          style={{
                            minWidth: 260,
                            maxWidth: 280,
                            background: '#f5f5f5',
                            borderRadius: 10,
                            borderTop: `4px solid ${stage.color || '#1668dc'}`,
                            display: 'flex',
                            flexDirection: 'column',
                          }}
                        >
                          <div style={{ padding: '10px 12px', borderBottom: '1px solid #e8e8e8' }}>
                            <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                              <strong>{stage.name}</strong>
                              <Tag>{stage.count || 0}</Tag>
                            </Space>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              ${Number(stage.value || 0).toLocaleString()}
                              {stage.stage_type !== 'open' && ` · ${stage.stage_type}`}
                            </Text>
                          </div>
                          <div style={{ padding: 8, flex: 1, minHeight: 200 }}>
                            {(stage.deals || []).map((d) => (
                              <Card
                                key={d.id}
                                size="small"
                                draggable
                                onDragStart={() => setDragDeal(d)}
                                onDragEnd={() => setDragDeal(null)}
                                style={{
                                  marginBottom: 8,
                                  cursor: 'grab',
                                  borderLeft: d.status === 'won' ? '3px solid #52c41a' : d.status === 'lost' ? '3px solid #ff4d4f' : undefined,
                                }}
                                styles={{ body: { padding: 10 } }}
                              >
                                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 4 }}>
                                  <HolderOutlined style={{ color: '#bfbfbf' }} />
                                  <div style={{ flex: 1 }}>
                                    <Button
                                      type="link"
                                      style={{ padding: 0, height: 'auto', fontWeight: 600 }}
                                      onClick={() => nav(`/business/customers/${d.customer_id}`)}
                                    >
                                      {d.title}
                                    </Button>
                                    <div>
                                      <Text type="secondary" style={{ fontSize: 12 }}>
                                        {d.customer_name}
                                        {d.account_name ? ` · ${d.account_name}` : ''}
                                      </Text>
                                    </div>
                                    <Space size={4} style={{ marginTop: 4 }} wrap>
                                      <Tag color="gold">${Number(d.value || 0).toLocaleString()}</Tag>
                                      <Tag>{d.priority}</Tag>
                                      {d.status !== 'open' && <Tag color={STATUS_COLOR[d.status]}>{d.status}</Tag>}
                                    </Space>
                                  </div>
                                </div>
                              </Card>
                            ))}
                            {!stage.deals?.length && (
                              <div style={{ textAlign: 'center', color: '#bfbfbf', padding: 16, fontSize: 12 }}>
                                Drop deals here
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ),
            },
          ]}
        />
      </Card>

      {/* New customer */}
      <Modal title="Add customer" open={custOpen} onCancel={() => setCustOpen(false)} footer={null} destroyOnClose width={640}>
        <Form form={custForm} layout="vertical" onFinish={createCustomer} initialValues={{ status: 'active', source: 'manual' }}>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="name" label="Contact name" rules={[{ required: true }]}><Input placeholder="Jane Smith" /></Form.Item></Col>
            <Col span={12}><Form.Item name="account_name" label="Account / company"><Input placeholder="Acme Ltd" /></Form.Item></Col>
            <Col span={12}><Form.Item name="email" label="Email"><Input placeholder="jane@acme.com" /></Form.Item></Col>
            <Col span={12}><Form.Item name="phone" label="Phone"><Input placeholder="+1…" /></Form.Item></Col>
            <Col span={12}><Form.Item name="job_title" label="Job title"><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="industry" label="Industry"><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="status" label="Status">
              <Select options={[
                { value: 'active', label: 'Active' },
                { value: 'inactive', label: 'Inactive' },
                { value: 'churned', label: 'Churned' },
              ]} />
            </Form.Item></Col>
            <Col span={12}><Form.Item name="source" label="Source">
              <Select options={[
                { value: 'manual', label: 'Manual' },
                { value: 'website', label: 'Website' },
                { value: 'referral', label: 'Referral' },
                { value: 'cold', label: 'Cold outreach' },
                { value: 'agent', label: 'Agent' },
                { value: 'import', label: 'Import' },
              ]} />
            </Form.Item></Col>
            <Col span={12}><Form.Item name="owner_human_id" label="Owner (human)">
              <Select allowClear options={humans.map((h) => ({ value: h.id, label: h.name }))} />
            </Form.Item></Col>
            <Col span={12}><Form.Item name="owner_agent_id" label="Owner (agent)">
              <Select allowClear options={agents.map((a) => ({ value: a.id, label: a.name }))} />
            </Form.Item></Col>
            <Col span={12}><Form.Item name="company_id" label="Workspace company">
              <Select allowClear options={companies.map((c) => ({ value: c.id, label: c.name }))} />
            </Form.Item></Col>
            <Col span={12}><Form.Item name="annual_value" label="Annual value"><InputNumber style={{ width: '100%' }} min={0} /></Form.Item></Col>
            <Col span={12}><Form.Item name="city" label="City"><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="country" label="Country"><Input /></Form.Item></Col>
            <Col span={24}><Form.Item name="tags" label="Tags"><Input placeholder="vip, enterprise, renewing" /></Form.Item></Col>
            <Col span={24}><Form.Item name="notes" label="Notes"><TextArea rows={2} /></Form.Item></Col>
          </Row>
          <Button type="primary" htmlType="submit" loading={saving} block>Create customer</Button>
        </Form>
      </Modal>

      {/* New deal */}
      <Modal title="Add deal" open={dealOpen} onCancel={() => setDealOpen(false)} footer={null} destroyOnClose>
        <Form form={dealForm} layout="vertical" onFinish={createDeal} initialValues={{ priority: 'medium', currency: 'USD', value: 0 }}>
          <Form.Item name="title" label="Deal title" rules={[{ required: true }]}>
            <Input placeholder="Acme annual subscription" />
          </Form.Item>
          <Form.Item name="customer_id" label="Customer" rules={[{ required: true }]}>
            <Select
              showSearch
              optionFilterProp="label"
              options={customers.map((c) => ({
                value: c.id,
                label: `${c.name}${c.account_name ? ` · ${c.account_name}` : ''}`,
              }))}
              placeholder="Select customer"
            />
          </Form.Item>
          <Form.Item name="value" label="Value">
            <InputNumber style={{ width: '100%' }} min={0} />
          </Form.Item>
          <Form.Item name="priority" label="Priority">
            <Select options={[
              { value: 'low', label: 'Low' },
              { value: 'medium', label: 'Medium' },
              { value: 'high', label: 'High' },
              { value: 'urgent', label: 'Urgent' },
            ]} />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <TextArea rows={2} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving} block>Create deal</Button>
        </Form>
      </Modal>

      {/* New pipeline */}
      <Modal title="New pipeline" open={pipeOpen} onCancel={() => setPipeOpen(false)} footer={null} destroyOnClose>
        <Form form={pipeForm} layout="vertical" onFinish={createPipeline} initialValues={{ kind: 'sales' }}>
          <Form.Item name="name" label="Name" rules={[{ required: true }]}>
            <Input placeholder="Enterprise sales" />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <TextArea rows={2} />
          </Form.Item>
          <Form.Item name="kind" label="Kind">
            <Select options={[
              { value: 'sales', label: 'Sales' },
              { value: 'support', label: 'Support' },
              { value: 'onboarding', label: 'Onboarding' },
              { value: 'custom', label: 'Custom' },
            ]} />
          </Form.Item>
          <Form.Item name="is_default" valuePropName="checked">
            <Select options={[{ value: false, label: 'Not default' }, { value: true, label: 'Make default' }]} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving} block>Create pipeline</Button>
        </Form>
      </Modal>

      {/* Arrange Diary (global from Business) */}
      <Modal title="Arrange diary / meeting" open={diaryOpen} onCancel={() => { setDiaryOpen(false); setSelectedCustForDiary(null) }} footer={null} destroyOnClose width={560}>
        <Form
          form={diaryForm}
          layout="vertical"
          onFinish={async (values) => {
            setSaving(true)
            try {
              const custId = selectedCustForDiary || values.customer_id
              if (!custId) throw new Error('Select a customer')
              await api('/business/diary', {
                method: 'POST',
                body: {
                  customer_id: Number(custId),
                  title: values.title,
                  start_at: values.start_at || null,
                  end_at: values.end_at || null,
                  location: values.location || '',
                  notes: values.notes || '',
                  owner_human_id: values.owner_human_id || null,
                  owner_agent_id: values.owner_agent_id || null,
                },
              })
              message.success('Diary entry added')
              setDiaryOpen(false)
              diaryForm.resetFields()
              setSelectedCustForDiary(null)
              await load()
            } catch (e) {
              message.error(e.message)
            } finally {
              setSaving(false)
            }
          }}
        >
          {!selectedCustForDiary && (
            <Form.Item name="customer_id" label="Customer" rules={[{ required: true }]}>
              <Select
                showSearch
                optionFilterProp="label"
                options={customers.map((c) => ({ value: c.id, label: `${c.name}${c.account_name ? ` · ${c.account_name}` : ''}` }))}
                placeholder="Select customer"
              />
            </Form.Item>
          )}
          <Form.Item name="title" label="Title" rules={[{ required: true }]} initialValue="Follow-up call">
            <Input />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="start_at" label="Start"><Input placeholder="2026-07-22T10:00" /></Form.Item></Col>
            <Col span={12}><Form.Item name="end_at" label="End"><Input placeholder="2026-07-22T10:30" /></Form.Item></Col>
          </Row>
          <Form.Item name="location" label="Location / link"><Input placeholder="Zoom / Phone / Office" /></Form.Item>
          <Form.Item name="notes" label="Notes"><TextArea rows={2} /></Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="owner_human_id" label="Owner (human)">
                <Select allowClear options={humans.map((h) => ({ value: h.id, label: h.name }))} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="owner_agent_id" label="Owner (agent)">
                <Select allowClear options={agents.map((a) => ({ value: a.id, label: a.name }))} />
              </Form.Item>
            </Col>
          </Row>
          <Button type="primary" htmlType="submit" loading={saving} block>Save to diary</Button>
        </Form>
      </Modal>
    </div>
  )
}
