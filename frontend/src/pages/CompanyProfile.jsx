import React, { useEffect, useState } from 'react'
import {
  Card, Row, Col, Statistic, Table, Tag, Button, Space, Typography, Form, Input,
  message, Spin, Empty, Descriptions, Segmented,
} from 'antd'
import {
  ArrowLeftOutlined, BankOutlined, RobotOutlined, UserOutlined,
  RiseOutlined, FallOutlined, EditOutlined, SafetyCertificateOutlined,
  TeamOutlined, ReloadOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams, Link } from 'react-router-dom'
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid,
  PieChart, Pie, Cell, LineChart, Line, Legend,
} from 'recharts'
import { api } from '../api'

const { Title, Text, Paragraph } = Typography
const COLORS = ['#1668dc', '#52c41a', '#ff4d4f', '#faad14', '#722ed1']

export default function CompanyProfile() {
  const { id } = useParams()
  const nav = useNavigate()
  const [profile, setProfile] = useState(null)
  const [finance, setFinance] = useState(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [days, setDays] = useState(30)
  const [form] = Form.useForm()

  const load = async (period = days) => {
    setLoading(true)
    try {
      const [p, f] = await Promise.all([
        api(`/org/companies/${id}`),
        api(`/org/companies/${id}/finance?days=${period}`),
      ])
      setProfile(p)
      setFinance(f)
      form.setFieldsValue({ name: p.name, industry: p.industry, notes: p.notes })
    } catch (e) {
      message.error(e.message || 'Failed to load company')
      nav('/workspace')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load(days) }, [id, days])

  const save = async (values) => {
    try {
      await api(`/org/companies/${id}`, { method: 'PATCH', body: values })
      message.success('Company updated')
      setEditing(false)
      load()
    } catch (e) {
      message.error(e.message)
    }
  }

  if (loading || !profile) {
    return <div style={{ textAlign: 'center', padding: 48 }}><Spin size="large" /></div>
  }

  const s = profile.stats || {}
  const pnl = finance?.pnl || {}
  const daily = finance?.daily_ai || []
  const pipeline = finance?.pipeline || []
  const byModel = finance?.by_model || []

  return (
    <div className="aba-page" style={{ maxWidth: '100%', overflowX: 'hidden' }}>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }} wrap>
        <Space wrap>
          <Button icon={<ArrowLeftOutlined />} onClick={() => nav('/workspace')}>Workspace</Button>
          <Title level={3} style={{ margin: 0 }}>
            <BankOutlined /> {profile.name}
          </Title>
          <Tag color="blue">{profile.industry || 'No industry'}</Tag>
        </Space>
        <Space wrap>
          <Segmented
            size="small"
            value={days}
            onChange={setDays}
            options={[
              { label: '7d', value: 7 },
              { label: '30d', value: 30 },
              { label: '90d', value: 90 },
            ]}
          />
          <Button size="small" icon={<ReloadOutlined />} onClick={() => load(days)}>Refresh</Button>
          <Button size="small" icon={<TeamOutlined />} onClick={() => nav('/humans')}>Team</Button>
          <Button size="small" icon={<SafetyCertificateOutlined />} onClick={() => nav('/permissions')}>
            Permissions
          </Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => setEditing(!editing)}>
            {editing ? 'Cancel edit' : 'Edit profile'}
          </Button>
        </Space>
      </Space>

      {editing && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Form form={form} layout="vertical" onFinish={save}>
            <Row gutter={12}>
              <Col xs={24} md={8}><Form.Item name="name" label="Name" rules={[{ required: true }]}><Input /></Form.Item></Col>
              <Col xs={24} md={8}><Form.Item name="industry" label="Industry"><Input /></Form.Item></Col>
              <Col xs={24} md={8}><Form.Item name="notes" label="Notes"><Input.TextArea rows={1} /></Form.Item></Col>
            </Row>
            <Button type="primary" htmlType="submit">Save</Button>
          </Form>
        </Card>
      )}

      {!editing && profile.notes && (
        <Paragraph type="secondary" style={{ marginBottom: 16 }}>{profile.notes}</Paragraph>
      )}

      {/* KPI strip */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={8} md={4}><Card size="small"><Statistic title="Projects" value={profile.project_count ?? profile.projects?.length ?? 0} /></Card></Col>
        <Col xs={12} sm={8} md={4}><Card size="small"><Statistic title="Agents" value={profile.agents?.length ?? 0} prefix={<RobotOutlined />} /></Card></Col>
        <Col xs={12} sm={8} md={4}><Card size="small"><Statistic title="Humans" value={profile.humans?.length ?? 0} prefix={<UserOutlined />} /></Card></Col>
        <Col xs={12} sm={8} md={4}><Card size="small"><Statistic title="Customers" value={s.customers ?? 0} /></Card></Col>
        <Col xs={12} sm={8} md={4}><Card size="small"><Statistic title="Pipeline open" prefix="$" value={s.pipeline_open_value ?? 0} precision={0} /></Card></Col>
        <Col xs={12} sm={8} md={4}><Card size="small"><Statistic title="Won revenue" prefix="$" value={s.pipeline_won_value ?? 0} precision={0} valueStyle={{ color: '#52c41a' }} /></Card></Col>
      </Row>

      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="AI cost (all time)" prefix="$" value={s.ai_cost ?? 0} precision={4} valueStyle={{ color: '#fa8c16' }} />
            <Text type="secondary" style={{ fontSize: 12 }}>{(s.ai_tokens || 0).toLocaleString()} tokens</Text>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="Task AI cost" prefix="$" value={s.task_cost ?? 0} precision={4} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="Est. profit (won − AI)"
              prefix="$"
              value={s.profit ?? 0}
              precision={2}
              valueStyle={{ color: (s.profit ?? 0) >= 0 ? '#52c41a' : '#ff4d4f' }}
              suffix={(s.profit ?? 0) >= 0 ? <RiseOutlined /> : <FallOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="Margin" suffix="%" value={s.margin_pct ?? 0} precision={1} />
          </Card>
        </Col>
      </Row>

      {/* Graphs */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={14}>
          <Card title={`AI cost & tokens (${days} days)`} size="small">
            {daily.length === 0 ? (
              <Empty description="No AI usage attributed to this company yet" />
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={daily}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                  <YAxis yAxisId="l" tick={{ fontSize: 11 }} />
                  <YAxis yAxisId="r" orientation="right" tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Legend />
                  <Line yAxisId="l" type="monotone" dataKey="tokens" name="Tokens" stroke="#1668dc" strokeWidth={2} dot={false} />
                  <Line yAxisId="r" type="monotone" dataKey="ai_cost" name="AI $" stroke="#fa8c16" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title="Pipeline value" size="small">
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={pipeline} dataKey="value" nameKey="status" cx="50%" cy="50%" outerRadius={90} label>
                  {pipeline.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(v) => `$${Number(v).toLocaleString()}`} />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} md={12}>
          <Card title="P&L snapshot" size="small">
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="Revenue (won deals)">${Number(pnl.revenue_won || 0).toLocaleString()}</Descriptions.Item>
              <Descriptions.Item label={`AI expense (${days}d)`}>${Number(pnl.ai_cost || 0).toFixed(4)}</Descriptions.Item>
              <Descriptions.Item label="Profit (won − AI)">${Number(pnl.profit || 0).toLocaleString()}</Descriptions.Item>
            </Descriptions>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
              {pnl.note || 'Won deal value as revenue; AI token spend as expense.'}
            </Text>
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card title="AI cost by model" size="small">
            {byModel.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={byModel.slice(0, 8)}>
                  <XAxis dataKey="model" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="cost" fill="#1668dc" name="Cost $" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>
        </Col>
      </Row>

      {/* Team tables */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="Agents" size="small" extra={<Link to="/agents">All agents</Link>}>
            <Table
              size="small"
              rowKey="id"
              pagination={{ pageSize: 6 }}
              scroll={{ x: true }}
              dataSource={profile.agents || []}
              columns={[
                { title: 'Name', dataIndex: 'name', render: (n, r) => <Link to={`/agents/${r.id}`}>{n}</Link> },
                { title: 'Role', dataIndex: 'hierarchy_role', width: 100 },
                { title: 'Permission', dataIndex: 'permission_level', width: 100, render: (v) => <Tag>{v}</Tag> },
                { title: 'Model', dataIndex: 'model', width: 90 },
                { title: 'Status', dataIndex: 'status', width: 80, render: (v) => <Tag color={v === 'active' ? 'green' : 'orange'}>{v}</Tag> },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card
            title="Human teammates"
            size="small"
            extra={
              <Space>
                <Link to="/permissions">Permissions</Link>
                <Link to="/humans">Manage team</Link>
              </Space>
            }
          >
            <Table
              size="small"
              rowKey="id"
              pagination={{ pageSize: 6 }}
              dataSource={profile.humans || []}
              locale={{ emptyText: 'No humans scoped to this company — add in Users / Team' }}
              columns={[
                { title: 'Name', dataIndex: 'name' },
                { title: 'Email', dataIndex: 'email', ellipsis: true },
                { title: 'Role', dataIndex: 'role_title' },
                { title: 'Permission', dataIndex: 'permission_level', render: (v) => <Tag color="blue">{v}</Tag> },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Card title="Projects" size="small" style={{ marginTop: 16 }}>
        <Table
          size="small"
          rowKey="id"
          dataSource={profile.projects || []}
          scroll={{ x: true }}
          columns={[
            { title: 'Project', dataIndex: 'name' },
            { title: 'Status', dataIndex: 'status', width: 90, render: (v) => <Tag>{v}</Tag> },
            { title: 'Agents', dataIndex: 'agent_count', width: 80 },
            { title: 'Tasks', dataIndex: 'task_count', width: 80 },
            { title: 'Open', dataIndex: 'open_tasks', width: 80 },
          ]}
        />
      </Card>
    </div>
  )
}
