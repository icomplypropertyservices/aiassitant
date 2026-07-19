import React from 'react'
import { Card, Button, Space, Popconfirm, message } from 'antd'
import {
  ThunderboltOutlined, TeamOutlined, PauseCircleOutlined, PlayCircleOutlined,
  CopyOutlined, DeleteOutlined, DashboardOutlined,
} from '@ant-design/icons'
import { api } from '../../api'

/** Agent manage page — top Actions card (assign, pause, delete, etc.). */
export default function AgentActionsCard({
  agent, id, nav,
  setTaskOpen, setDelegateOpen,
  meetingBusy, openMeetingRoom, toggle,
}) {
  return (
    <Card
      bordered
      size="small"
      className="aba-soft-card"
      title={<Space><ThunderboltOutlined /> Actions</Space>}
    >
      <Space wrap>
        <Button
          type="primary"
          icon={<DashboardOutlined />}
          onClick={() => nav(`/agents/${id}/dash`)}
        >
          Dashboard
        </Button>
        <Button onClick={() => setTaskOpen(true)}>Assign task</Button>
        {(agent.is_lead || agent.reports?.length > 0) && (
          <Button icon={<TeamOutlined />} onClick={() => setDelegateOpen(true)}>Delegate</Button>
        )}
        <Button icon={<TeamOutlined />} loading={meetingBusy} onClick={openMeetingRoom}>
          Open meeting room
        </Button>
        <Button
          icon={agent.status === 'active' ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
          onClick={toggle}
        >
          {agent.status === 'active' ? 'Pause' : 'Resume'}
        </Button>
        <Button
          icon={<CopyOutlined />}
          onClick={async () => {
            try {
              const c = await api(`/agents/${id}/duplicate`, { method: 'POST' })
              message.success('Agent duplicated')
              nav(`/agents/${c.id}`)
            } catch (e) { message.error(e.message) }
          }}
        >
          Duplicate
        </Button>
        <Popconfirm
          title="Delete this agent?"
          description="Removes the agent and unlinks chats, tasks, and skills."
          okText="Delete"
          okButtonProps={{ danger: true }}
          onConfirm={async () => {
            try {
              await api(`/agents/${id}`, { method: 'DELETE' })
              message.success('Agent deleted')
              nav('/console')
            } catch (e) {
              message.error(e?.message || e?.detail || 'Delete failed — try again')
            }
          }}
        >
          <Button danger icon={<DeleteOutlined />} className="aba-delete-agent-btn">Delete</Button>
        </Popconfirm>
      </Space>
    </Card>
  )
}
