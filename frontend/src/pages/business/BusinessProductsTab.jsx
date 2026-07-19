import React from 'react'
import {
  Card, Table, Button, Space, Tag, Typography, Input, Select, Badge, Empty,
} from 'antd'
import {
  PlusOutlined, SearchOutlined, CloudSyncOutlined, CloudUploadOutlined, BankOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

const { Text } = Typography

/**
 * Products catalogue tab for Business CRM (company-linked + Shopify tags).
 */
export default function BusinessProductsTab({
  products,
  productTotal,
  loading,
  productQ,
  setProductQ,
  productStatus,
  setProductStatus,
  loadProducts,
  shopifySyncing,
  syncShopify,
  onAdd,
  onEdit,
  onRemove,
  onPushShopify,
}) {
  const nav = useNavigate()

  const productColumns = [
    {
      title: 'Product',
      key: 'name',
      render: (_, r) => (
        <div>
          <strong>{r.name}</strong>
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {r.sku ? `SKU ${r.sku} · ` : ''}{r.kind || 'product'}
            </Text>
          </div>
        </div>
      ),
    },
    {
      title: 'Company',
      key: 'company',
      render: (_, r) => (
        r.company_id ? (
          <Button type="link" size="small" style={{ padding: 0 }} onClick={() => nav(`/companies/${r.company_id}`)}>
            <BankOutlined /> {r.company_name || `#${r.company_id}`}
          </Button>
        ) : <Text type="secondary">Unlinked</Text>
      ),
    },
    {
      title: 'Price',
      render: (_, r) => `${r.currency || 'USD'} ${Number(r.price || 0).toLocaleString()}`,
    },
    {
      title: 'Status',
      dataIndex: 'status',
      render: (s) => <Tag color={s === 'active' ? 'green' : s === 'draft' ? 'gold' : 'default'}>{s}</Tag>,
    },
    {
      title: 'Tags',
      dataIndex: 'tags',
      render: (tags, r) => (
        <Space size={[4, 4]} wrap>
          {r.external_source === 'shopify' && <Tag color="green">shopify</Tag>}
          {(tags || []).filter((t) => t !== 'shopify').map((t) => <Tag key={t} color="purple">{t}</Tag>)}
          {!(tags || []).length && r.external_source !== 'shopify' && <Text type="secondary">—</Text>}
        </Space>
      ),
    },
    {
      title: '',
      key: 'actions',
      width: 200,
      render: (_, r) => (
        <Space size={4} wrap>
          <Button size="small" onClick={() => onEdit(r)}>Edit</Button>
          {r.external_source === 'shopify' && r.external_id && (
            <Button size="small" icon={<CloudUploadOutlined />} onClick={() => onPushShopify(r.id)} title="Push tags to Shopify">
              Push
            </Button>
          )}
          <Button size="small" danger onClick={() => onRemove(r.id)}>Del</Button>
        </Space>
      ),
    },
  ]

  return (
    <Card
      type="inner"
      className="aba-soft-card"
      title="Product catalogue"
      extra={(
        <Space wrap>
          <Button size="small" icon={<CloudSyncOutlined />} loading={shopifySyncing} onClick={() => syncShopify('products')}>
            Sync Shopify products
          </Button>
          <Button type="primary" size="small" icon={<PlusOutlined />} onClick={onAdd}>
            Add product
          </Button>
        </Space>
      )}
      styles={{ body: { paddingTop: 12, overflowX: 'auto' } }}
    >
      <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
        Products are tagged and linked to your company. Sync from Shopify to import catalogue tags.
      </Text>
      <Card size="small" type="inner" className="aba-soft-card" style={{ marginBottom: 12 }} styles={{ body: { padding: '10px 12px' } }}>
        <Space style={{ width: '100%' }} wrap>
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder="Search products, SKU, tags…"
            style={{ width: 280, maxWidth: '100%' }}
            value={productQ}
            onChange={(e) => setProductQ(e.target.value)}
            onPressEnter={loadProducts}
          />
          <Select
            allowClear
            placeholder="Status"
            style={{ width: 140 }}
            value={productStatus}
            onChange={setProductStatus}
            options={[
              { value: 'active', label: 'Active' },
              { value: 'draft', label: 'Draft' },
              { value: 'archived', label: 'Archived' },
            ]}
          />
          <Button onClick={loadProducts}>Search</Button>
        </Space>
      </Card>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={products}
        columns={productColumns}
        pagination={{ pageSize: 15, total: productTotal, showTotal: (t) => `${t} products` }}
        scroll={{ x: 800 }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No products — add your catalogue" /> }}
      />
    </Card>
  )
}

/** Badge label for Products tab */
export function productsTabLabel(productTotal) {
  return <Badge count={productTotal} offset={[12, 0]} size="small" color="#722ed1">Products</Badge>
}
