import React, { useEffect, useState } from 'react'
import { Card, Table, Row, Col, Statistic, Tabs, Tag, Result, Button } from 'antd'
import { useNavigate } from 'react-router-dom'
import { api, getUser } from '../api'

export default function Admin() {
  const nav = useNavigate()
  const user = getUser()
  const [stats, setStats] = useState(null)
  const [users, setUsers] = useState([])
  const [agents, setAgents] = useState([])

  useEffect(() => {
    if (user?.role !== 'admin') return
    api('/admin/stats').then(setStats).catch(() => {})
    api('/admin/users').then(setUsers).catch(() => {})
    api('/admin/agents').then(setAgents).catch(() => {})
  }, [user?.role])

  if (user?.role !== 'admin') {
    return (
      <Result
        status="403"
        title="Access denied"
        subTitle="Staff admin is only available to users with the admin role."
        extra={<Button type="primary" onClick={() => nav('/')}>Back to dashboard</Button>}
      />
    )
  }

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}><Card><Statistic title="Users" value={stats?.users ?? 0} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="Agents" value={stats?.agents ?? 0} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="Total tokens" value={stats?.total_tokens ?? 0} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="Revenue" prefix="$" precision={4} value={stats?.total_revenue ?? 0} /></Card></Col>
      </Row>
      <Card>
        <Tabs items={[
          { key: 'users', label: 'User management', children: (
            <Table rowKey="id" dataSource={users} columns={[
              { title: 'Email', dataIndex: 'email' },
              { title: 'Name', dataIndex: 'name' },
              { title: 'Role', dataIndex: 'role', render: r => <Tag color={r === 'admin' ? 'gold' : 'default'}>{r}</Tag> },
              { title: 'Plan', dataIndex: 'plan' },
              { title: 'Credits', dataIndex: 'credits', render: v => `$${v}` },
              { title: 'Agents', dataIndex: 'agents' },
              { title: 'Tokens', dataIndex: 'tokens' },
              { title: 'Spend', dataIndex: 'spend', render: v => `$${v}` },
            ]} />
          )},
          { key: 'agents', label: 'Agents oversight', children: (
            <Table rowKey="id" dataSource={agents} columns={[
              { title: 'Agent', dataIndex: 'name' },
              { title: 'Owner', dataIndex: 'owner' },
              { title: 'Template', dataIndex: 'template_type' },
              { title: 'Model', dataIndex: 'model' },
              { title: 'Status', dataIndex: 'status', render: s => <Tag color={s === 'active' ? 'green' : 'orange'}>{s}</Tag> },
              { title: 'Idle mode', dataIndex: 'idle_mode' },
            ]} />
          )},
        ]} />
      </Card>
    </div>
  )
}
