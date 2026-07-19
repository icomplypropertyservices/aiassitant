import React from 'react'
import {
  Modal, Form, Input, Select, Button, Row, Col, Space, InputNumber,
} from 'antd'
import { TagsOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

const { TextArea } = Input

/** Add / edit product modal for Business CRM. */
export default function BusinessProductModal({
  open, onCancel, form, onFinish, saving,
  editingProduct, companies, productTagPresets, defaultCompanyId,
}) {
  const nav = useNavigate()
  return (
    <Modal
      title={editingProduct ? 'Edit product' : 'Add product'}
      open={open}
      onCancel={onCancel}
      footer={null}
      destroyOnClose
      width={640}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={onFinish}
        initialValues={{
          status: 'active',
          kind: 'product',
          currency: 'USD',
          price: 0,
          company_id: defaultCompanyId,
          tags: [],
        }}
      >
        <Row gutter={12}>
          <Col xs={24} sm={12}>
            <Form.Item name="name" label="Product name" rules={[{ required: true }]}>
              <Input placeholder="AI Business Assistant Pro" />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item
              name="company_id"
              label="Your company"
              rules={[{ required: true, message: 'Link product to your company' }]}
            >
              <Select
                options={companies.map((c) => ({ value: c.id, label: c.name }))}
                placeholder="Select company"
                notFoundContent={<Button type="link" onClick={() => nav('/workspace')}>Create company</Button>}
              />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item name="sku" label="SKU">
              <Input placeholder="SKU-001" />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item name="kind" label="Type">
              <Select options={[
                { value: 'product', label: 'Product' },
                { value: 'service', label: 'Service' },
                { value: 'digital', label: 'Digital' },
                { value: 'subscription', label: 'Subscription' },
                { value: 'other', label: 'Other' },
              ]} />
            </Form.Item>
          </Col>
          <Col xs={24} sm={8}>
            <Form.Item name="price" label="Price">
              <InputNumber style={{ width: '100%' }} min={0} step={0.01} />
            </Form.Item>
          </Col>
          <Col xs={24} sm={8}>
            <Form.Item name="currency" label="Currency">
              <Input placeholder="USD" />
            </Form.Item>
          </Col>
          <Col xs={24} sm={8}>
            <Form.Item name="status" label="Status">
              <Select options={[
                { value: 'active', label: 'Active' },
                { value: 'draft', label: 'Draft' },
                { value: 'archived', label: 'Archived' },
              ]} />
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item name="description" label="Description">
              <TextArea rows={2} placeholder="What it is and who it is for" />
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item name="benefits" label="Key benefits">
              <TextArea rows={2} placeholder="Saves time, automates CRM…" />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item name="audience" label="Audience">
              <Input placeholder="SMB ops teams" />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item name="offer" label="Offer / CTA">
              <Input placeholder="14-day free trial" />
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item name="tags" label={<Space size={4}><TagsOutlined /> Product tags</Space>}>
              <Select
                mode="tags"
                tokenSeparators={[',']}
                placeholder="core, featured, b2b…"
                options={productTagPresets.map((t) => ({ value: t, label: t }))}
                style={{ width: '100%' }}
              />
            </Form.Item>
          </Col>
        </Row>
        <Button type="primary" htmlType="submit" loading={saving} block>
          {editingProduct ? 'Save product' : 'Create product'}
        </Button>
      </Form>
    </Modal>
  )
}
