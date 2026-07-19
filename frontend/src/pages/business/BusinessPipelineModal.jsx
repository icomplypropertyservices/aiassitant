import React from 'react'
import { Modal, Form, Input, Select, Button } from 'antd'

const { TextArea } = Input

/** New pipeline modal for Business CRM. */
export default function BusinessPipelineModal({
  open, onCancel, form, onFinish, saving,
}) {
  return (
    <Modal title="New pipeline" open={open} onCancel={onCancel} footer={null} destroyOnClose>
      <Form form={form} layout="vertical" onFinish={onFinish} initialValues={{ kind: 'sales' }}>
        <Form.Item name="name" label="Name" rules={[{ required: true }]}>
          <Input placeholder="Enterprise sales" />
        </Form.Item>
        <Form.Item name="description" label="Description">
          <TextArea rows={2} />
        </Form.Item>
        <Form.Item name="kind" label="Kind">
          <Select options={[
            { value: 'sales', label: 'Sales' },
            { value: 'support', label: 'Support' },
            { value: 'onboarding', label: 'Onboarding' },
            { value: 'custom', label: 'Custom' },
          ]} />
        </Form.Item>
        <Form.Item name="is_default" valuePropName="checked">
          <Select options={[{ value: false, label: 'Not default' }, { value: true, label: 'Make default' }]} />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={saving} block>Create pipeline</Button>
      </Form>
    </Modal>
  )
}
