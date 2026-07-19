import React from 'react'
import { Card, Statistic, Row, Col, Typography } from 'antd'
import {
  TeamOutlined, ShoppingOutlined, FunnelPlotOutlined, DollarOutlined, BankOutlined,
} from '@ant-design/icons'

const { Text } = Typography

/** Top statistic cards for Business CRM. */
export default function BusinessStatsRow({ counts, companies }) {
  return (
    <Row gutter={[16, 16]}>
      <Col xs={12} md={6} lg={4}>
        <Card className="aba-stat-card aba-soft-card" size="small">
          <Statistic title="Customers" value={counts.customers || 0} prefix={<TeamOutlined />} suffix={<Text type="secondary" style={{ fontSize: 13 }}>/ {counts.customers_active || 0}</Text>} />
        </Card>
      </Col>
      <Col xs={12} md={6} lg={4}>
        <Card className="aba-stat-card aba-soft-card" size="small">
          <Statistic title="Products" value={counts.products || 0} prefix={<ShoppingOutlined />} suffix={<Text type="secondary" style={{ fontSize: 13 }}>/ {counts.products_active || 0}</Text>} />
        </Card>
      </Col>
      <Col xs={12} md={6} lg={4}>
        <Card className="aba-stat-card aba-soft-card" size="small">
          <Statistic title="Open deals" value={counts.deals_open || 0} prefix={<FunnelPlotOutlined />} />
        </Card>
      </Col>
      <Col xs={12} md={6} lg={4}>
        <Card className="aba-stat-card aba-soft-card" size="small">
          <Statistic title="Pipeline $" value={counts.pipeline_value || 0} prefix={<DollarOutlined />} precision={0} />
        </Card>
      </Col>
      <Col xs={12} md={6} lg={4}>
        <Card className="aba-stat-card aba-soft-card" size="small">
          <Statistic title="Won $" value={counts.won_value || 0} prefix={<DollarOutlined />} precision={0} valueStyle={{ color: '#52c41a' }} />
        </Card>
      </Col>
      <Col xs={12} md={6} lg={4}>
        <Card className="aba-stat-card aba-soft-card" size="small">
          <Statistic title="Companies" value={counts.companies || companies.length || 0} prefix={<BankOutlined />} />
        </Card>
      </Col>
    </Row>
  )
}
