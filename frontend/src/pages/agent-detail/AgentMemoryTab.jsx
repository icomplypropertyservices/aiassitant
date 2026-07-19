import React from 'react'
import {
  Card, Form, Input, Select, Switch, Button, Space, Tag, List, Typography, Popconfirm, message,
} from 'antd'
import { api } from '../../api'

/** Agent manage page — Data / memory tab body. */
export default function AgentMemoryTab({ id, memForm, loadSkillsExtra, memories }) {
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card bordered size="small" className="aba-soft-card">
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          Agent data vault — notes, facts, deliverables. Optionally promote into the Training library.
        </Typography.Paragraph>
      </Card>
      <Card bordered size="small" className="aba-soft-card" title="Add data">
        <Form
          form={memForm}
          layout="vertical"
          onFinish={async (v) => {
            try {
              const r = await api(`/agents/${id}/memory`, { method: 'POST', body: v })
              message.success(r.message || 'Saved')
              memForm.resetFields()
              loadSkillsExtra()
            } catch (e) { message.error(e.message) }
          }}
        >
          <Form.Item name="title" label="Title"><Input placeholder="Optional title" /></Form.Item>
          <Form.Item name="content" label="Content" rules={[{ required: true }]}>
            <Input.TextArea rows={4} placeholder="Data this agent should remember…" />
          </Form.Item>
          <Form.Item name="kind" label="Kind" initialValue="note">
            <Select options={[
              { value: 'note', label: 'Note' },
              { value: 'fact', label: 'Fact' },
              { value: 'deliverable', label: 'Deliverable' },
              { value: 'crm', label: 'CRM' },
            ]} />
          </Form.Item>
          <Form.Item name="tags" label="Tags"><Input placeholder="comma,separated" /></Form.Item>
          <Form.Item name="save_to_training" valuePropName="checked" initialValue={false}>
            <Switch checkedChildren="Also save to Training" unCheckedChildren="Vault only" />
          </Form.Item>
          <Button type="primary" htmlType="submit">Save data</Button>
        </Form>
      </Card>
      <Card bordered size="small" className="aba-soft-card" title="Saved data">
        <List
          dataSource={memories}
          locale={{ emptyText: 'No saved data yet' }}
          renderItem={(m) => (
            <List.Item
              actions={[
                <Popconfirm
                  key="d"
                  title="Delete?"
                  onConfirm={async () => {
                    await api(`/agents/${id}/memory/${m.id}`, { method: 'DELETE' })
                    loadSkillsExtra()
                  }}
                >
                  <Button size="small" danger>Delete</Button>
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={(
                  <Space>
                    <Tag>{m.kind}</Tag>
                    {m.title || 'Untitled'}
                    {m.knowledge_file_id && <Tag color="blue">in training</Tag>}
                  </Space>
                )}
                description={<div style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>}
              />
            </List.Item>
          )}
        />
      </Card>
    </Space>
  )
}
