import React from 'react'
import { Card, Space, Tag, Typography, Button } from 'antd'
import { AppstoreOutlined } from '@ant-design/icons'

/** Agent manage page — Apps & training integrations card. */
export default function AgentIntegrationsCard({ agentApps, agentTraining, nav }) {
  return (
    <Card bordered size="small" className="aba-soft-card" title={<Space><AppstoreOutlined /> Apps & training</Space>}>
      <Space direction="vertical" style={{ width: '100%' }} size={8}>
        <Space wrap>
          <Typography.Text type="secondary">Apps:</Typography.Text>
          {(agentApps || []).length === 0 ? (
            <Typography.Text type="secondary">none</Typography.Text>
          ) : (
            agentApps.map((c) => (
              <Tag
                key={c.id || c.connection_id}
                color={c.status === 'connected' ? 'success' : c.status === 'error' ? 'error' : 'default'}
              >
                {c.display_name || c.app_name || c.app_id}
              </Tag>
            ))
          )}
        </Space>
        <Space wrap>
          <Typography.Text type="secondary">Training files:</Typography.Text>
          {(agentTraining || []).length === 0 ? (
            <Typography.Text type="secondary">none allocated</Typography.Text>
          ) : (
            agentTraining.map((f) => (
              <Tag key={f.id}>{f.name}</Tag>
            ))
          )}
        </Space>
        <Space wrap>
          <Button type="link" size="small" onClick={() => nav('/settings?tab=apps')}>Connected apps</Button>
          <Button type="link" size="small" onClick={() => nav('/training')}>Training library</Button>
          <Button type="link" size="small" onClick={() => nav('/training')}>Program this agent</Button>
        </Space>
      </Space>
    </Card>
  )
}
