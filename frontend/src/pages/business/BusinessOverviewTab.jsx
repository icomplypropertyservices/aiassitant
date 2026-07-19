import React from 'react'
import {
  Card, Table, Button, Space, Tag, Typography, Row, Col, Empty,
} from 'antd'
import { FunnelPlotOutlined, CalendarOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { STATUS_COLOR } from './constants'

const { Text } = Typography

/**
 * Overview tab for Business CRM — recent customers, pipelines, upcoming diary.
 */
export default function BusinessOverviewTab({
  overview, upcomingDiary, setTab, setPipelineId, setSelectedCustForDiary, setDiaryOpen,
}) {
  const nav = useNavigate()

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} md={12}>
        <Card
          type="inner"
          className="aba-soft-card"
          title="Recent customers"
          styles={{ header: { textAlign: 'center' }, body: { paddingTop: 8, overflowX: 'auto' } }}
          extra={<Button type="link" onClick={() => setTab('customers')}>View all</Button>}
        >
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
              { title: 'Account', dataIndex: 'account_name', render: (v) => v || '—' },
              { title: 'Status', dataIndex: 'status', render: (s) => <Tag color={STATUS_COLOR[s]}>{s}</Tag> },
            ]}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No customers yet" /> }}
          />
        </Card>
      </Col>
      <Col xs={24} md={12}>
        <Card
          type="inner"
          className="aba-soft-card"
          title="Pipelines"
          styles={{ header: { textAlign: 'center' } }}
          extra={<Button type="link" onClick={() => setTab('pipeline')}>Open board</Button>}
        >
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
        <Card
          type="inner"
          className="aba-soft-card"
          title="Upcoming diary / meetings"
          styles={{ header: { textAlign: 'center' }, body: { paddingTop: 8, overflowX: 'auto' } }}
          extra={(
            <Button
              type="link"
              icon={<CalendarOutlined />}
              onClick={() => { setSelectedCustForDiary(null); setDiaryOpen(true) }}
            >
              Arrange new
            </Button>
          )}
        >
          {(upcomingDiary || []).length ? (
            <Table
              size="small"
              rowKey="id"
              pagination={false}
              dataSource={upcomingDiary}
              scroll={{ x: 720 }}
              columns={[
                { title: 'When', dataIndex: 'start_at', width: 160, render: (v) => (v ? new Date(v).toLocaleString() : 'TBD') },
                { title: 'Customer', render: (_, r) => <Button type="link" style={{ padding: 0 }} onClick={() => nav(`/business/customers/${r.customer_id}`)}>{r.customer_name}</Button> },
                { title: 'Title', dataIndex: 'title', ellipsis: true },
                { title: 'Location', dataIndex: 'location', render: (v) => v || '—' },
                { title: 'Owner', render: (_, r) => r.owner_human_name || r.owner_agent_name || '—' },
              ]}
              onRow={(r) => ({ onClick: () => nav(`/business/customers/${r.customer_id}`), style: { cursor: 'pointer' } })}
            />
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="No upcoming diary items. Use “Arrange diary” to schedule meetings/calls for customers."
            />
          )}
        </Card>
      </Col>
    </Row>
  )
}
