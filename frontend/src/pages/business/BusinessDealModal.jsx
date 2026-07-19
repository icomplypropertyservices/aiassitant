import React from 'react'
import { Modal, Form, Input, Select, Button, InputNumber } from 'antd'

const { TextArea } = Input

/** Add deal modal for Business CRM. */
export default function BusinessDealModal({
  open, onCancel, form, onFinish, saving, customers,
}) {
  return (
    <Modal title="Add deal" open={open} onCancel={onCancel} footer={null} destroyOnClose>
      <Form form={form} layout="vertical" onFinish={onFinish} initialValues={{ priority: 'medium', currency: 'USD', value: 0 }}>
        <Form.Item name="title" label="Deal title" rules={[{ required: true }]}>
          <Input placeholder="Acme annual subscription" />
        </Form.Item>
        <Form.Item name="customer_id" label="Customer" rules={[{ required: true }]}>
          <Select
            showSearch
            optionFilterProp="label"
            options={customers.map((c) => ({
              value: c.id,
              label: `${c.name}${c.account_name ? ` · ${c.account_name}` : ''}`,
            }))}
            placeholder="Select customer"
          />
        </Form.Item>
        <Form.Item name="value" label="Value">
          <InputNumber style={{ width: '100%' }} min={0} />
        </Form.Item>
        <Form.Item name="priority" label="Priority">
          <Select options={[
            { value: 'low', label: 'Low' },
            { value: 'medium', label: 'Medium' },
            { value: 'high', label: 'High' },
            { value: 'urgent', label: 'Urgent' },
          ]} />
        </Form.Item>
        <Form.Item name="description" label="Description">
          <TextArea rows={2} />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={saving} block>Create deal</Button>
      </Form>
    </Modal>
  )
}
