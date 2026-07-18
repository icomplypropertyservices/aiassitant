import React, { useEffect, useState } from 'react'
import { Card, Row, Col, Table, Statistic } from 'antd'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../api'

export default function Analytics() {
  const [usage, setUsage] = useState(null)
  useEffect(() => { api('/billing/usage').then(setUsage).catch(() => {}) }, [])
  const models = Object.entries(usage?.by_model || {}).map(([k, v]) => ({ key: k, ...v }))

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}><Card><Statistic title="Total tokens" value={usage?.total_tokens ?? 0} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="Total cost" prefix="$" precision={4} value={usage?.total_cost ?? 0} /></Card></Col>
      </Row>
      <Card title="Tokens — last 7 days" style={{ marginBottom: 16 }}>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={usage?.daily || []}>
            <XAxis dataKey="day" /><YAxis /><Tooltip />
            <Bar dataKey="tokens" fill="#1668dc" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Card>
      <Card title="Usage by model">
        <Table pagination={false} dataSource={models} columns={[
          { title: 'Model', dataIndex: 'label' },
          { title: 'Tokens', dataIndex: 'tokens', render: v => v.toLocaleString() },
          { title: 'Cost', dataIndex: 'cost', render: v => `$${v}` },
        ]} />
      </Card>
    </div>
  )
}
