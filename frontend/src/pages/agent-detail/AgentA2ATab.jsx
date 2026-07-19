import React from 'react'
import {
  Card, Form, Input, Select, Button, Space, Tag, List, Typography, message,
} from 'antd'
import { MessageOutlined } from '@ant-design/icons'
import { api } from '../../api'

/** Agent manage page — Agent-to-agent chat tab body. */
export default function AgentA2ATab({
  id, a2aForm, skillBusy, setSkillBusy, allAgents, loadSkillsExtra, agentMsgs,
}) {
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card bordered size="small" className="aba-soft-card">
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          Converse with other agents. Messages are stored and can trigger an auto-reply from the target agent.
        </Typography.Paragraph>
      </Card>
      <Card bordered size="small" className="aba-soft-card" title="Send message">
        <Form
          form={a2aForm}
          layout="vertical"
          onFinish={async (v) => {
            setSkillBusy(true)
            try {
              const r = await api(`/agents/${id}/message-agent`, { method: 'POST', body: { ...v, expect_reply: true } })
              if (r.ok) {
                message.success(r.message)
                if (r.reply) message.info(`Reply: ${String(r.reply).slice(0, 120)}…`)
              } else message.error(r.error)
              a2aForm.resetFields(['message'])
              loadSkillsExtra()
            } catch (e) { message.error(e.message) }
            finally { setSkillBusy(false) }
          }}
        >
          <Form.Item name="to_agent_id" label="To agent" rules={[{ required: true }]}>
            <Select
              showSearch
              optionFilterProp="label"
              options={allAgents.filter((a) => String(a.id) !== String(id)).map((a) => ({
                value: a.id,
                label: `${a.name} (${a.hierarchy_role || 'member'})`,
              }))}
            />
          </Form.Item>
          <Form.Item name="message" label="Message" rules={[{ required: true }]}>
            <Input.TextArea rows={3} placeholder="Internal instruction or question…" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={skillBusy} icon={<MessageOutlined />}>Send to agent</Button>
        </Form>
      </Card>
      <Card bordered size="small" className="aba-soft-card" title="Message history">
        <List
          dataSource={agentMsgs}
          locale={{ emptyText: 'No agent-to-agent messages yet' }}
          renderItem={(m) => (
            <List.Item>
              <List.Item.Meta
                title={<Space><Tag color="blue">{m.from_name}</Tag>→<Tag color="purple">{m.to_name}</Tag></Space>}
                description={<div style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>}
              />
            </List.Item>
          )}
        />
      </Card>
    </Space>
  )
}
