import React from 'react'
import {
  Card, Form, Input, Select, Switch, Button, Space, Tag, Typography, Descriptions,
} from 'antd'
import { SettingOutlined } from '@ant-design/icons'
import ModelSelect from '../../components/ModelSelect'

/** Agent manage page — Config tab body. */
export default function AgentConfigTab({ editForm, saveSettings, agent, humans }) {
  return (
    <Form form={editForm} layout="vertical" onFinish={saveSettings}>
      <Space direction="vertical" size={12} style={{ width: '100%', maxWidth: 720 }}>
        <Card bordered size="small" className="aba-soft-card" title="Identity & model">
          <Form.Item name="name" label="Name" rules={[{ required: true }]} style={{ marginBottom: 12 }}>
            <Input />
          </Form.Item>
          <Form.Item name="personality" label="Personality" style={{ marginBottom: 12 }}>
            <Input.TextArea rows={4} />
          </Form.Item>
          <Form.Item name="model" label="Model" style={{ marginBottom: 12 }}>
            <ModelSelect style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="never_idle"
            label="Never be idle (self-running work when free)"
            valuePropName="checked"
            style={{ marginBottom: 0 }}
          >
            <Switch />
          </Form.Item>
        </Card>

        <Card bordered size="small" className="aba-soft-card" title="Permissions & escalation">
          <Form.Item name="permission_level" label="Permission level" rules={[{ required: true }]} style={{ marginBottom: 12 }}>
            <Select options={[
              { value: 'viewer', label: 'Viewer — read only' },
              { value: 'operator', label: 'Operator — execute own work' },
              { value: 'lead', label: 'Lead — delegate, spawn, assign humans' },
              { value: 'admin', label: 'Admin — full control' },
            ]} />
          </Form.Item>
          <Form.Item name="escalate_when" label="When to escalate" rules={[{ required: true }]} style={{ marginBottom: 12 }}>
            <Select options={[
              { value: 'never', label: 'Never auto-escalate' },
              { value: 'on_failure', label: 'On failure' },
              { value: 'on_blocked', label: 'When blocked' },
              { value: 'high_priority', label: 'High / urgent priority' },
              { value: 'sla_breach', label: 'SLA / stuck too long' },
              { value: 'customer_vip', label: 'VIP / tagged customers' },
              { value: 'value_threshold', label: 'High deal value' },
              { value: 'always_review', label: 'Always review' },
              { value: 'custom', label: 'Custom rule (use reason below)' },
            ]} />
          </Form.Item>
          <Form.Item name="escalate_reason" label="Escalation reason / custom rule" style={{ marginBottom: 12 }}>
            <Input.TextArea rows={2} placeholder="e.g. Escalate refunds over £500 or legal risk" />
          </Form.Item>
          <Form.Item name="escalate_to" label="Escalate to" style={{ marginBottom: 12 }}>
            <Select options={[
              { value: 'parent', label: 'Reporting lead / parent agent' },
              { value: 'orchestrator', label: 'Main orchestrator' },
              { value: 'human', label: 'Human (pick below)' },
              { value: 'owner', label: 'Workspace owner' },
            ]} />
          </Form.Item>
          <Form.Item name="escalate_human_id" label="Escalate human (optional)" style={{ marginBottom: 0 }}>
            <Select allowClear options={humans.map((h) => ({ value: h.id, label: h.name }))} placeholder="Human teammate" />
          </Form.Item>
        </Card>

        <Card bordered size="small" className="aba-soft-card" title="Config & metadata">
          <Descriptions size="small" column={1}>
            <Descriptions.Item label="Type">{agent.template_type}</Descriptions.Item>
            <Descriptions.Item label="Permission"><Tag>{agent.permission_level || 'operator'}</Tag></Descriptions.Item>
            <Descriptions.Item label="Escalate when"><Tag color="orange">{agent.escalate_when || 'on_failure'}</Tag></Descriptions.Item>
            <Descriptions.Item label="Created">{agent.created_at && new Date(agent.created_at).toLocaleString()}</Descriptions.Item>
            <Descriptions.Item label="Config">
              <Typography.Paragraph code copyable style={{ margin: 0, fontSize: 12 }}>
                {JSON.stringify(agent.config || {}, null, 0)}
              </Typography.Paragraph>
            </Descriptions.Item>
          </Descriptions>
        </Card>

        <Button type="primary" htmlType="submit" icon={<SettingOutlined />}>Save config</Button>
      </Space>
    </Form>
  )
}
