import React from 'react'
import {
  Modal, Form, Input, Select, Button, Row, Col, message,
} from 'antd'
import { api } from '../../api'

const { TextArea } = Input

/**
 * Arrange diary / meeting modal opened from Business page header or overview.
 * Not a standalone tab — diary list lives in BusinessOverviewTab.
 */
export default function BusinessDiaryModal({
  open,
  onClose,
  form,
  saving,
  setSaving,
  selectedCustForDiary,
  setSelectedCustForDiary,
  customers,
  humans,
  agents,
  onSaved,
}) {
  return (
    <Modal
      title="Arrange diary / meeting"
      open={open}
      onCancel={() => { onClose(); setSelectedCustForDiary(null) }}
      footer={null}
      destroyOnClose
      width={560}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={async (values) => {
          setSaving(true)
          try {
            const custId = selectedCustForDiary || values.customer_id
            if (!custId) throw new Error('Select a customer')
            await api('/business/diary', {
              method: 'POST',
              body: {
                customer_id: Number(custId),
                title: values.title,
                start_at: values.start_at || null,
                end_at: values.end_at || null,
                location: values.location || '',
                notes: values.notes || '',
                owner_human_id: values.owner_human_id || null,
                owner_agent_id: values.owner_agent_id || null,
              },
            })
            message.success('Diary entry added')
            onClose()
            form.resetFields()
            setSelectedCustForDiary(null)
            await onSaved()
          } catch (e) {
            message.error(e.message)
          } finally {
            setSaving(false)
          }
        }}
      >
        {!selectedCustForDiary && (
          <Form.Item name="customer_id" label="Customer" rules={[{ required: true }]}>
            <Select
              showSearch
              optionFilterProp="label"
              options={customers.map((c) => ({ value: c.id, label: `${c.name}${c.account_name ? ` · ${c.account_name}` : ''}` }))}
              placeholder="Select customer"
            />
          </Form.Item>
        )}
        <Form.Item name="title" label="Title" rules={[{ required: true }]} initialValue="Follow-up call">
          <Input />
        </Form.Item>
        <Row gutter={12}>
          <Col span={12}><Form.Item name="start_at" label="Start"><Input placeholder="2026-07-22T10:00" /></Form.Item></Col>
          <Col span={12}><Form.Item name="end_at" label="End"><Input placeholder="2026-07-22T10:30" /></Form.Item></Col>
        </Row>
        <Form.Item name="location" label="Location / link"><Input placeholder="Zoom / Phone / Office" /></Form.Item>
        <Form.Item name="notes" label="Notes"><TextArea rows={2} /></Form.Item>
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item name="owner_human_id" label="Owner (human)">
              <Select allowClear options={humans.map((h) => ({ value: h.id, label: h.name }))} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="owner_agent_id" label="Owner (agent)">
              <Select allowClear options={agents.map((a) => ({ value: a.id, label: a.name }))} />
            </Form.Item>
          </Col>
        </Row>
        <Button type="primary" htmlType="submit" loading={saving} block>Save to diary</Button>
      </Form>
    </Modal>
  )
}
