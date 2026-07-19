import React, { useCallback, useEffect, useState } from 'react'
import {
  Card, Row, Col, Button, Tag, Space, Typography, Spin, Empty, Avatar, message,
} from 'antd'
import {
  TeamOutlined, RobotOutlined, CrownOutlined, UserOutlined,
  MessageOutlined, SettingOutlined, ThunderboltOutlined, ReloadOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

function roleColor(a) {
  const r = (a.hierarchy_role || '').toLowerCase()
  if (r === 'orchestrator') return 'purple'
  if (r === 'lead') return 'gold'
  if (r === 'specialist') return 'cyan'
  return 'blue'
}

function roleLabel(a) {
  const r = (a.hierarchy_role || a.template_type || 'member')
  return String(r).replace(/_/g, ' ')
}

/**
 * Core Team — pinned standing team for every user.
 * Loads GET /agents/core-team; can ensure with POST /agents/core-team/ensure.
 */
export default function CoreTeam({
  compact = false,
  autoEnsure = false,
  showTitle = true,
  className = '',
}) {
  const nav = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [ensuring, setEnsuring] = useState(false)

  const load = useCallback((opts = {}) => {
    if (!opts.quiet) setLoading(true)
    return api('/agents/core-team')
      .then((r) => setData(r))
      .catch((e) => {
        message.error(e?.message || 'Could not load Core Team')
        setData({ agents: [], human: null, empty: true })
      })
      .finally(() => setLoading(false))
  }, [])

  const ensure = async () => {
    setEnsuring(true)
    try {
      const r = await api('/agents/core-team/ensure', { method: 'POST' })
      setData(r)
      const n = r?.created_ids?.length || 0
      message.success(n ? `Core Team ready (+${n} new)` : 'Core Team ready')
    } catch (e) {
      const msg = e?.message || 'Could not set up Core Team'
      message.error(msg)
      if (e?.status === 402 || /plan|subscription|billing/i.test(msg)) {
        message.info('Activate a plan on Billing to create your Core Team')
      }
    } finally {
      setEnsuring(false)
    }
  }

  useEffect(() => {
    load().then(() => {
      /* optional auto-ensure left off by default — button is clearer */
    })
  }, [load])

  useEffect(() => {
    if (!autoEnsure || loading || !data) return
    if (data.empty || !(data.agents || []).length) {
      ensure()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoEnsure, loading, data?.empty])

  const agents = data?.agents || []
  const human = data?.human

  return (
    <Card
      className={`aba-soft-card aba-core-team ${className}`.trim()}
      title={showTitle ? (
        <Space wrap>
          <TeamOutlined />
          <span>Core Team</span>
          {agents.length > 0 && <Tag color="blue">{agents.length} agents</Tag>}
          {human && <Tag color="green">+ My Human</Tag>}
        </Space>
      ) : null}
      extra={(
        <Space wrap size={6}>
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={() => load({ quiet: true })}
            loading={loading && !!data}
          >
            Refresh
          </Button>
          <Button
            type="primary"
            size="small"
            icon={<ThunderboltOutlined />}
            loading={ensuring}
            onClick={ensure}
          >
            {agents.length ? 'Sync Core Team' : 'Set up Core Team'}
          </Button>
          <Button type="link" size="small" onClick={() => nav('/console')}>
            Console
          </Button>
        </Space>
      )}
      styles={{ body: { padding: compact ? 12 : 16 } }}
    >
      {loading && !data ? (
        <div style={{ textAlign: 'center', padding: 32 }}>
          <Spin tip="Loading Core Team…" />
        </div>
      ) : !agents.length && !human ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="No Core Team yet — set up your standing agents and My Human"
        >
          <Button type="primary" loading={ensuring} onClick={ensure} icon={<TeamOutlined />}>
            Set up Core Team
          </Button>
        </Empty>
      ) : (
        <Row gutter={[12, 12]}>
          {agents.map((a) => (
            <Col key={a.id} xs={24} sm={12} md={compact ? 12 : 8} lg={compact ? 8 : 6}>
              <Card
                size="small"
                hoverable
                className="aba-card-clickable aba-core-team-card"
                onClick={() => nav(`/console/${a.id}`)}
                styles={{ body: { padding: 12 } }}
              >
                <Space align="start" style={{ width: '100%' }}>
                  <Avatar
                    style={{
                      background:
                        (a.hierarchy_role || '') === 'orchestrator'
                          ? '#722ed1'
                          : (a.hierarchy_role || '') === 'lead'
                            ? '#faad14'
                            : '#1668dc',
                      flexShrink: 0,
                    }}
                    icon={
                      (a.hierarchy_role || '') === 'orchestrator'
                        ? <CrownOutlined />
                        : <RobotOutlined />
                    }
                  />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <Typography.Text strong ellipsis style={{ display: 'block' }}>
                      {a.name}
                    </Typography.Text>
                    <Space size={4} wrap style={{ marginTop: 4 }}>
                      <Tag color={roleColor(a)} style={{ margin: 0 }}>{roleLabel(a)}</Tag>
                      <Tag
                        color={a.status === 'active' ? 'success' : 'warning'}
                        style={{ margin: 0 }}
                      >
                        {a.status || 'active'}
                      </Tag>
                    </Space>
                    {!compact && a.personality && (
                      <Typography.Paragraph
                        type="secondary"
                        ellipsis={{ rows: 2 }}
                        style={{ marginBottom: 0, marginTop: 6, fontSize: 12 }}
                      >
                        {a.personality}
                      </Typography.Paragraph>
                    )}
                    <Space size={4} style={{ marginTop: 8 }} wrap>
                      <Button
                        type="primary"
                        size="small"
                        icon={<MessageOutlined />}
                        onClick={(e) => { e.stopPropagation(); nav(`/console/${a.id}`) }}
                      >
                        Talk
                      </Button>
                      <Button
                        size="small"
                        icon={<SettingOutlined />}
                        onClick={(e) => { e.stopPropagation(); nav(`/console/${a.id}/manage`) }}
                      >
                        Manage
                      </Button>
                    </Space>
                  </div>
                </Space>
              </Card>
            </Col>
          ))}

          {human && (
            <Col xs={24} sm={12} md={compact ? 12 : 8} lg={compact ? 8 : 6}>
              <Card
                size="small"
                hoverable
                className="aba-card-clickable aba-core-team-card is-human"
                onClick={() => nav('/humans')}
                styles={{ body: { padding: 12 } }}
              >
                <Space align="start" style={{ width: '100%' }}>
                  <Avatar style={{ background: '#16a34a', flexShrink: 0 }} icon={<UserOutlined />} />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <Typography.Text strong ellipsis style={{ display: 'block' }}>
                      {human.name || 'My Human'}
                    </Typography.Text>
                    <Space size={4} wrap style={{ marginTop: 4 }}>
                      <Tag color="green" style={{ margin: 0 }}>My Human</Tag>
                      <Tag style={{ margin: 0 }}>{human.status || 'active'}</Tag>
                    </Space>
                    <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 6 }}>
                      {human.role_title || 'Primary operator · human delegate'}
                    </Typography.Text>
                    <Button
                      type="primary"
                      size="small"
                      style={{ marginTop: 8 }}
                      onClick={(e) => { e.stopPropagation(); nav('/humans') }}
                    >
                      Open Team
                    </Button>
                  </div>
                </Space>
              </Card>
            </Col>
          )}
        </Row>
      )}
    </Card>
  )
}
