import React from 'react'
import { Card, Space, Typography, Tag, Button, Alert, message } from 'antd'
import { CrownOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { isOrchestrator } from '../agents/roles'

/**
 * Shared gold banner for Main AI Orchestrator — always easy to spot.
 *
 * @param {object|null} orchestrator - agent payload or {id,name,status}
 * @param {() => void} [onChanged] - reload callback after ensure
 * @param {boolean} [compact]
 */
export default function OrchestratorBanner({ orchestrator, onChanged, compact = false }) {
  const nav = useNavigate()
  const orch = orchestrator && isOrchestrator(orchestrator) ? orchestrator : orchestrator

  const ensure = async () => {
    try {
      const a = await api('/agents/ensure-orchestrator', { method: 'POST' })
      message.success(`${a.name} ready — pinned at top of hierarchy`)
      onChanged?.()
      if (a?.id) nav(`/agents/${a.id}`)
    } catch (e) {
      message.error(e.message)
    }
  }

  return (
    <Card
      style={{
        marginBottom: 16,
        border: '2px solid #faad14',
        background: 'linear-gradient(90deg, #fffbe6 0%, #fff 55%)',
      }}
      styles={compact ? { body: { padding: '12px 16px' } } : undefined}
    >
      <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
        <Space align="start">
          <CrownOutlined style={{ fontSize: compact ? 22 : 28, color: '#d48806' }} />
          <div>
            <Typography.Title level={compact ? 5 : 5} style={{ margin: 0 }}>
              Main AI Orchestrator
            </Typography.Title>
            {!compact && (
              <Typography.Text type="secondary">
                Always at the top of your agent hierarchy. Routes work across companies and projects.
              </Typography.Text>
            )}
            {orch ? (
              <div style={{ marginTop: 6 }}>
                <Tag color="gold" icon={<CrownOutlined />}>{orch.name}</Tag>
                {orch.status && (
                  <Tag color={orch.status === 'active' ? 'green' : 'orange'}>{orch.status}</Tag>
                )}
              </div>
            ) : (
              <Alert
                type="warning"
                showIcon
                style={{ marginTop: 8 }}
                message="No Main Orchestrator yet"
                description={compact ? undefined : 'Create one so every team has a clear top-level commander.'}
              />
            )}
          </div>
        </Space>
        <Space>
          {orch ? (
            <Button type="primary" onClick={() => nav(`/agents/${orch.id}`)}>
              Open orchestrator
            </Button>
          ) : (
            <Button type="primary" icon={<CrownOutlined />} onClick={ensure}>
              Create Main Orchestrator
            </Button>
          )}
          <Button onClick={() => nav('/hierarchy')}>Hierarchy</Button>
        </Space>
      </Space>
    </Card>
  )
}
