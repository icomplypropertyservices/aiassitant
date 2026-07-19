import React from 'react'
import {
  Card, Table, Button, Space, Tag, Typography, Input, Select, Badge, Empty,
} from 'antd'
import {
  PlusOutlined, SearchOutlined, CloudSyncOutlined, UserOutlined, BankOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { STATUS_COLOR } from './constants'

const { Text } = Typography

/**
 * Customers list tab for Business CRM (company-linked + Shopify tags).
 */
export default function BusinessCustomersTab({
  customers,
  total,
  loading,
  q,
  setQ,
  statusFilter,
  setStatusFilter,
  loadCustomers,
  shopifySyncing,
  syncShopify,
  onAdd,
}) {
  const nav = useNavigate()

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
    {
      title: 'Company',
      key: 'company',
      render: (_, r) => (
        r.company_id ? (
          <Button type="link" size="small" style={{ padding: 0 }} onClick={(e) => { e.stopPropagation(); nav(`/companies/${r.company_id}`) }}>
            <BankOutlined /> {r.company_name || `#${r.company_id}`}
          </Button>
        ) : <Text type="secondary">—</Text>
      ),
    },
    { title: 'Email', dataIndex: 'email', responsive: ['md'], render: (v) => v || '—' },
    {
      title: 'Status',
      dataIndex: 'status',
      render: (s) => <Tag color={STATUS_COLOR[s] || 'default'}>{s}</Tag>,
    },
    {
      title: 'Tags',
      dataIndex: 'tags',
      render: (tags, r) => (
        <Space size={[4, 4]} wrap>
          {r.external_source === 'shopify' && <Tag color="green">shopify</Tag>}
          {(tags || []).filter((t) => t !== 'shopify').map((t) => <Tag key={t} color="blue">{t}</Tag>)}
          {!(tags || []).length && r.external_source !== 'shopify' && <Text type="secondary">—</Text>}
        </Space>
      ),
    },
    {
      title: 'Open deals',
      dataIndex: 'open_deals',
      width: 100,
      responsive: ['lg'],
    },
    {
      title: 'Pipeline $',
      dataIndex: 'pipeline_value',
      responsive: ['lg'],
      render: (v) => `$${Number(v || 0).toLocaleString()}`,
    },
  ]

  return (
    <Card
      type="inner"
      className="aba-soft-card"
      title="Customer records"
      extra={(
        <Space wrap>
          <Button
            size="small"
            icon={<CloudSyncOutlined />}
            loading={shopifySyncing}
            onClick={() => syncShopify('customers')}
          >
            Sync Shopify customers
          </Button>
          <Button type="primary" size="small" icon={<PlusOutlined />} onClick={onAdd}>
            Add customer
          </Button>
        </Space>
      )}
      styles={{ body: { paddingTop: 12, overflowX: 'auto' } }}
    >
      <Card
        size="small"
        type="inner"
        className="aba-soft-card"
        style={{ marginBottom: 12 }}
        styles={{ body: { padding: '10px 12px' } }}
      >
        <Space style={{ width: '100%' }} wrap>
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
      </Card>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={customers}
        columns={customerColumns}
        pagination={{ pageSize: 15, total, showTotal: (t) => `${t} customers` }}
        scroll={{ x: 900 }}
        onRow={(r) => ({
          onClick: () => nav(`/business/customers/${r.id}`),
          style: { cursor: 'pointer' },
        })}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No customers — add your first record" /> }}
      />
    </Card>
  )
}

/** Badge label for Customers tab */
export function customersTabLabel(total) {
  return <Badge count={total} offset={[12, 0]} size="small" color="#1668dc">Customers</Badge>
}
