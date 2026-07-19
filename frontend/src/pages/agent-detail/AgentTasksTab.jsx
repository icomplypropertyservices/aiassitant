import React from 'react'
import { Card, Button, Space, Tag, List, message } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { api } from '../../api'
import { STATUS_COLOR } from './constants'

/** Agent manage page — Tasks tab body. */
export default function AgentTasksTab({
  agent, setTaskOpen, load, setSelectedTask, nav,
}) {
  return (
    <Card
      bordered
      size="small"
      className="aba-soft-card"
      title="Recent tasks"
      extra={(
        <Space wrap>
          <Button type="primary" size="small" onClick={() => setTaskOpen(true)}>New task</Button>
          <Button size="small" icon={<ReloadOutlined />} onClick={load}>Refresh</Button>
          <Button type="link" size="small" onClick={() => nav('/tasks')}>Open tasks board →</Button>
        </Space>
      )}
    >
      <List
        dataSource={agent.recent_tasks || []}
        locale={{ emptyText: 'No tasks yet — assign one from Actions or the board' }}
        renderItem={(t) => (
          <List.Item
            style={{ cursor: 'pointer' }}
            onClick={() => setSelectedTask(t)}
            actions={[
              t.status !== 'completed' && t.status !== 'in_progress' && (
                <Button
                  key="run"
                  type="link"
                  onClick={async (e) => {
                    e.stopPropagation()
                    try {
                      await api(`/agents/tasks/${t.id}/run`, { method: 'POST' })
                      message.success('Running…')
                      load()
                    } catch (err) { message.error(err.message) }
                  }}
                >
                  Run
                </Button>
              ),
            ].filter(Boolean)}
          >
            <List.Item.Meta
              title={(
                <Space wrap>
                  {t.title}
                  <Tag color={STATUS_COLOR[t.status]}>{t.status}</Tag>
                  <Tag>{t.priority}</Tag>
                  {t.tokens_used > 0 && (
                    <Tag color="purple">{t.tokens_used} tok · ${Number(t.cost).toFixed(4)}</Tag>
                  )}
                </Space>
              )}
              description={t.description}
            />
          </List.Item>
        )}
      />
    </Card>
  )
}
