import React from 'react'
import {
  Modal, Form, Input, Select, Button, Row, Col, Space, InputNumber,
} from 'antd'
import { TagsOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

const { TextArea } = Input

/** Add customer modal for Business CRM. */
export default function BusinessCustomerModal({
  open, onCancel, form, onFinish, saving,
  companies, humans, agents, customerTagPresets, defaultCompanyId,
}) {
  const nav = useNavigate()
  return (
    <Modal title="Add customer" open={open} onCancel={onCancel} footer={null} destroyOnClose width={640}>
      <Form
        form={form}
        layout="vertical"
        onFinish={onFinish}
        initialValues={{ status: 'active', source: 'manual', company_id: defaultCompanyId, tags: [] }}
      >
        <Row gutter={12}>
          <Col xs={24} sm={12}><Form.Item name="name" label="Contact name" rules={[{ required: true }]}><Input placeholder="Jane Smith" /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name="account_name" label="Account name"><Input placeholder="Acme Ltd" /></Form.Item></Col>
          <Col xs={24} sm={12}>
            <Form.Item
              name="company_id"
              label="Your company"
              rules={companies.length ? [{ required: true, message: 'Link to your company' }] : []}
              extra={!companies.length ? 'Create a company in Workspace first' : 'Must be a company you own'}
            >
              <Select
                placeholder={companies.length ? 'Select company' : 'No companies yet'}
                options={companies.map((c) => ({ value: c.id, label: c.name }))}
                notFoundContent={<Button type="link" onClick={() => nav('/workspace')}>Create company</Button>}
              />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}><Form.Item name="email" label="Email"><Input placeholder="jane@acme.com" /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name="phone" label="Phone"><Input placeholder="+1…" /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name="job_title" label="Job title"><Input /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name="industry" label="Industry"><Input /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name="status" label="Status">
            <Select options={[
              { value: 'active', label: 'Active' },
              { value: 'inactive', label: 'Inactive' },
              { value: 'churned', label: 'Churned' },
            ]} />
          </Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name="source" label="Source">
            <Select options={[
              { value: 'manual', label: 'Manual' },
              { value: 'website', label: 'Website' },
              { value: 'referral', label: 'Referral' },
              { value: 'cold', label: 'Cold outreach' },
              { value: 'agent', label: 'Agent' },
              { value: 'import', label: 'Import' },
            ]} />
          </Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name="owner_human_id" label="Owner (human)">
            <Select allowClear options={humans.map((h) => ({ value: h.id, label: h.name }))} />
          </Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name="owner_agent_id" label="Owner (agent)">
            <Select allowClear options={agents.map((a) => ({ value: a.id, label: a.name }))} />
          </Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name="annual_value" label="Annual value"><InputNumber style={{ width: '100%' }} min={0} /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name="city" label="City"><Input /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name="country" label="Country"><Input /></Form.Item></Col>
          <Col span={24}>
            <Form.Item name="tags" label={<Space size={4}><TagsOutlined /> Customer tags</Space>}>
              <Select
                mode="tags"
                tokenSeparators={[',']}
                placeholder="vip, enterprise, renewing…"
                options={customerTagPresets.map((t) => ({ value: t, label: t }))}
                style={{ width: '100%' }}
              />
            </Form.Item>
          </Col>
          <Col span={24}><Form.Item name="notes" label="Notes"><TextArea rows={2} /></Form.Item></Col>
        </Row>
        <Button type="primary" htmlType="submit" loading={saving} block>Create customer</Button>
      </Form>
    </Modal>
  )
}
