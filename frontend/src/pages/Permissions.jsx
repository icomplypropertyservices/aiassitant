import React, { useEffect, useState } from 'react'
import {
  Card, Table, Tag, Select, message, Tabs, Typography, Alert, Space, Button, Spin,
} from 'antd'
import { SafetyCertificateOutlined, RobotOutlined, UserOutlined, ReloadOutlined, TeamOutlined } from '@ant-design/icons'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'

const { Title, Text } = Typography

const LEVEL_COLORS = { viewer: 'default', operator: 'blue', lead: 'purple', admin: 'gold' }

export default function Permissions() {
  const nav = useNavigate()
  const [data, setData] = useState(null)
  const [catalog, setCatalog] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(null)

  const load = async () => {
    setLoading(true)
    try {
      const [m, c] = await Promise.all([
        api('/permissions/matrix'),
        api('/permissions/catalog'),
      ])
      setData(m)
      setCatalog(c)
    } catch (e) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const levelOpts = (catalog?.levels || []).map((l) => ({
    value: l.id,
    label: `${l.label} — ${l.description}`,
  }))
  const whenOpts = (catalog?.escalate_when || []).map((e) => ({ value: e.id, label: e.label }))
  const toOpts = (catalog?.escalate_to || []).map((e) => ({ value: e.id, label: e.label }))
  const idleOpts = [
    { value: 'never_idle', label: 'Never idle (auto work)' },
    { value: 'allow_idle', label: 'Allow idle' },
  ]

  const patchAgent = async (id, field, value) => {
    const key = `agent-${id}`
    setSaving(key)
    try {
      await api(`/permissions/agents/${id}`, { method: 'PATCH', body: { [field]: value } })
      message.success('Saved')
      load()
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(null)
    }
  }

  const patchHuman = async (id, field, value) => {
    const key = `human-${id}`
    setSaving(key)
    try {
      await api(`/permissions/humans/${id}`, { method: 'PATCH', body: { [field]: value } })
      message.success('Saved')
      load()
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(null)
    }
  }

  if (loading && !data) {
    return <div style={{ textAlign: 'center', padding: 48 }}><Spin size="large" /></div>
  }

  const agentCols = [
    {
      title: 'Agent',
      dataIndex: 'name',
      fixed: 'left',
      width: 160,
      render: (n, r) => (
        <Space>
          <RobotOutlined />
          <Link to={`/agents/${r.id}/manage`}>{n}</Link>
        </Space>
      ),
    },
    { title: 'Role', dataIndex: 'role', width: 110, render: (v) => <Tag>{v}</Tag> },
    {
      title: 'Permission',
      dataIndex: 'permission_level',
      width: 160,
      render: (v, r) => (
        <Select
          size="small"
          style={{ width: '100%', minWidth: 120 }}
          value={v}
          options={levelOpts}
          loading={saving === `agent-${r.id}`}
          onChange={(val) => patchAgent(r.id, 'permission_level', val)}
        />
      ),
    },
    {
      title: 'Escalate when',
      dataIndex: 'escalate_when',
      width: 160,
      render: (v, r) => (
        <Select
          size="small"
          style={{ width: '100%', minWidth: 120 }}
          value={v}
          options={whenOpts}
          onChange={(val) => patchAgent(r.id, 'escalate_when', val)}
        />
      ),
    },
    {
      title: 'Escalate to',
      dataIndex: 'escalate_to',
      width: 140,
      render: (v, r) => (
        <Select
          size="small"
          style={{ width: '100%', minWidth: 110 }}
          value={v}
          options={toOpts}
          onChange={(val) => patchAgent(r.id, 'escalate_to', val)}
        />
      ),
    },
    {
      title: 'Idle mode',
      dataIndex: 'idle_mode',
      width: 150,
      render: (v, r) => (
        <Select
          size="small"
          style={{ width: '100%', minWidth: 120 }}
          value={v || 'never_idle'}
          options={idleOpts}
          onChange={(val) => patchAgent(r.id, 'idle_mode', val)}
        />
      ),
    },
    {
      title: 'Company',
      dataIndex: 'company_name',
      ellipsis: true,
      render: (n, r) => (r.company_id ? <Link to={`/companies/${r.company_id}`}>{n || 'Company'}</Link> : '—'),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      width: 90,
      render: (v) => <Tag color={v === 'active' ? 'green' : 'orange'}>{v}</Tag>,
    },
  ]

  const humanCols = [
    {
      title: 'Human',
      dataIndex: 'name',
      fixed: 'left',
      width: 160,
      render: (n) => (
        <Space><UserOutlined /><strong>{n}</strong></Space>
      ),
    },
    { title: 'Email', dataIndex: 'email', ellipsis: true },
    { title: 'Title', dataIndex: 'role', width: 120 },
    {
      title: 'Permission',
      dataIndex: 'permission_level',
      width: 160,
      render: (v, r) => (
        <Select
          size="small"
          style={{ width: '100%', minWidth: 120 }}
          value={v}
          options={levelOpts}
          onChange={(val) => patchHuman(r.id, 'permission_level', val)}
        />
      ),
    },
    {
      title: 'Escalate when',
      dataIndex: 'escalate_when',
      width: 160,
      render: (v, r) => (
        <Select
          size="small"
          style={{ width: '100%', minWidth: 120 }}
          value={v}
          options={whenOpts}
          onChange={(val) => patchHuman(r.id, 'escalate_when', val)}
        />
      ),
    },
    {
      title: 'Escalate to',
      dataIndex: 'escalate_to',
      width: 140,
      render: (v, r) => (
        <Select
          size="small"
          style={{ width: '100%', minWidth: 110 }}
          value={v}
          options={toOpts}
          onChange={(val) => patchHuman(r.id, 'escalate_to', val)}
        />
      ),
    },
    {
      title: 'Company',
      dataIndex: 'company_name',
      render: (n, r) => (r.company_id ? <Link to={`/companies/${r.company_id}`}>{n}</Link> : '—'),
    },
  ]

  return (
    <div style={{ maxWidth: '100%', overflowX: 'hidden' }}>
      <Space style={{ marginBottom: 12, width: '100%', justifyContent: 'space-between' }} wrap>
        <div>
          <Title level={3} style={{ margin: 0 }}><SafetyCertificateOutlined /> Permissions</Title>
          <Text type="secondary">
            Control what agents and human teammates can do, when they escalate, and idle behaviour.
          </Text>
        </div>
        <Space wrap>
          <Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button>
          <Button type="primary" icon={<TeamOutlined />} onClick={() => nav('/humans')}>
            Add people
          </Button>
          <Button onClick={() => nav('/profile')}>Your profile</Button>
        </Space>
      </Space>

      <Alert
        style={{ margin: '16px 0' }}
        type="info"
        showIcon
        message="Permission levels"
        description={
          <Space wrap>
            {(catalog?.levels || []).map((l) => (
              <Tag key={l.id} color={LEVEL_COLORS[l.id] || 'default'}>
                <strong>{l.label}</strong>: {l.description}
              </Tag>
            ))}
          </Space>
        }
      />

      <Card>
        <Tabs
          items={[
            {
              key: 'agents',
              label: `Agents (${data?.agents?.length || 0})`,
              children: (
                <Table
                  size="small"
                  rowKey="id"
                  scroll={{ x: 980 }}
                  dataSource={data?.agents || []}
                  columns={agentCols}
                  pagination={{ pageSize: 12 }}
                />
              ),
            },
            {
              key: 'humans',
              label: `Humans (${data?.humans?.length || 0})`,
              children: (
                <Table
                  size="small"
                  rowKey="id"
                  scroll={{ x: 900 }}
                  dataSource={data?.humans || []}
                  columns={humanCols}
                  locale={{ emptyText: 'No humans yet — add them under Team' }}
                  pagination={{ pageSize: 12 }}
                />
              ),
            },
          ]}
        />
      </Card>
    </div>
  )
}
