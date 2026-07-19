import React, { useEffect, useState } from 'react'
import {
  Card, Typography, Alert, Tag, Space, message, Spin, Select, Empty,
} from 'antd'
import { RobotOutlined } from '@ant-design/icons'
import { api } from '../../api'
import { connStatusColor } from './helpers'

const { Text } = Typography

export default function SettingsAgents() {
  const [connections, setConnections] = useState([])
  const [agents, setAgents] = useState([])
  const [appsLoading, setAppsLoading] = useState(true)

  const loadApps = () => {
    setAppsLoading(true)
    Promise.all([
      api('/integrations/connections').catch(() => ({ connections: [] })),
      api('/agents/').catch(() => []),
    ])
      .then(([con, ag]) => {
        const conns = Array.isArray(con?.connections)
          ? con.connections
          : (Array.isArray(con) ? con : [])
        let agentList = []
        if (Array.isArray(ag)) agentList = ag
        else if (Array.isArray(ag?.agents)) agentList = ag.agents
        else if (Array.isArray(ag?.items)) agentList = ag.items
        setConnections(conns.filter((c) => c && c.id != null))
        setAgents(agentList.filter((a) => a && a.id != null))
      })
      .catch(() => {
        setConnections([])
        setAgents([])
      })
      .finally(() => setAppsLoading(false))
  }

  useEffect(() => {
    loadApps()
  }, [])

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title={<Space><RobotOutlined /> Allocate apps to agents</Space>}
        className="aba-soft-card"
        type="inner"
      >
        <Alert
          type="info"
          showIcon
          message="Agents only see apps you assign"
          description="Open a connection to change the agent list, or manage per agent below."
        />
      </Card>
      {appsLoading ? (
        <Card className="aba-soft-card" type="inner"><Spin /></Card>
      ) : agents.length === 0 ? (
        <Card className="aba-soft-card" type="inner">
          <Empty description="Create agents first, then allocate apps" />
        </Card>
      ) : (
        agents.map((agent) => {
          const linked = (agent.integrations || []).filter(Boolean)
          const fromConns = connections.filter((c) => (c.agent_ids || []).includes(agent.id))
          const apps = linked.length
            ? linked
            : fromConns.map((c) => ({
              connection_id: c.id,
              app_id: c.app_id,
              display_name: c.display_name,
              status: c.status,
            }))
          return (
            <Card
              key={agent.id}
              size="small"
              className="aba-soft-card"
              type="inner"
              title={
                <Space>
                  <RobotOutlined />
                  {agent.name}
                  <Tag>{agent.template_type}</Tag>
                  <Tag color={agent.status === 'active' ? 'success' : 'default'}>{agent.status}</Tag>
                </Space>
              }
            >
              <Space wrap style={{ marginBottom: 8 }}>
                {apps.length === 0 ? (
                  <Text type="secondary">No apps allocated</Text>
                ) : apps.map((a) => (
                  <Tag key={a.connection_id || a.app_id} color={connStatusColor(a.status)}>
                    {a.display_name || a.app_id}
                  </Tag>
                ))}
              </Space>
              <Select
                mode="multiple"
                allowClear
                placeholder="Select connected apps for this agent"
                style={{ width: '100%', maxWidth: 560 }}
                value={fromConns.map((c) => c.id)}
                options={connections.map((c) => ({
                  value: c.id,
                  label: `${c.display_name || c.app_name} (${c.status})`,
                }))}
                onChange={async (ids) => {
                  try {
                    await api(`/integrations/agents/${agent.id}`, {
                      method: 'PUT',
                      body: { connection_ids: ids, permission: 'full' },
                    })
                    message.success(`Updated apps for ${agent.name}`)
                    loadApps()
                  } catch (e) {
                    message.error(e.message)
                  }
                }}
              />
            </Card>
          )
        })
      )}
    </Space>
  )
}
