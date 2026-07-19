import React from 'react'
import { Row, Col, Card, Statistic } from 'antd'

/** Agent manage page — stats row under Actions. */
export default function AgentStatsRow({ agent }) {
  const s = agent.stats || {}
  return (
    <Row gutter={[12, 12]}>
      <Col xs={12} sm={8} md={4}>
        <Card bordered size="small" className="aba-stat-card aba-soft-card">
          <Statistic title="Open tasks" value={s.open ?? 0} />
        </Card>
      </Col>
      <Col xs={12} sm={8} md={4}>
        <Card bordered size="small" className="aba-stat-card aba-soft-card">
          <Statistic title="Completed" value={s.completed ?? 0} />
        </Card>
      </Col>
      <Col xs={12} sm={8} md={5}>
        <Card bordered size="small" className="aba-stat-card aba-soft-card">
          <Statistic title="Team reports" value={s.reports ?? agent.reports_count ?? 0} />
        </Card>
      </Col>
      <Col xs={12} sm={8} md={4}>
        <Card bordered size="small" className="aba-stat-card aba-soft-card">
          <Statistic title="Chats" value={s.conversations ?? 0} />
        </Card>
      </Col>
      <Col xs={12} sm={8} md={7}>
        <Card bordered size="small" className="aba-stat-card aba-soft-card">
          <Statistic
            title="Role"
            value={agent.hierarchy_role || (agent.is_lead ? 'lead' : 'member')}
            valueStyle={{ fontSize: 18, textTransform: 'capitalize' }}
          />
        </Card>
      </Col>
    </Row>
  )
}
