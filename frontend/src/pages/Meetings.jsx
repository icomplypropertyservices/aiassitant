import React, { useEffect, useMemo, useState } from 'react'
import {
  Card, Table, Button, Space, Typography, Tag, Empty, Spin, message,
  Modal, Form, Input, Select, Alert, Segmented, Row, Col, Statistic,
} from 'antd'
import {
  PlusOutlined, ReloadOutlined, CommentOutlined, TeamOutlined,
  CheckCircleOutlined, PlayCircleOutlined, StopOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/PageHeader'
import PageShell from '../components/PageShell'

const { Text } = Typography
const { TextArea } = Input


const STATUS_COLOR = {
  open: 'blue',
  active: 'green',
  closed: 'default',
}

const TYPE_COLOR = {
  brainstorm: 'purple',
  task_war_room: 'orange',
  standup: 'cyan',
  review: 'geekblue',
}

const ROOM_TYPES = [
  { value: 'brainstorm', label: 'Brainstorm' },
  { value: 'task_war_room', label: 'Task war room' },
  { value: 'standup', label: 'Standup' },
  { value: 'review', label: 'Review' },
]

const STATUS_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'active', label: 'Active' },
  { value: 'closed', label: 'Closed' },
]

/** Center empty / loading placeholders inside Card body */
const emptyCardBody = {
  minHeight: 240,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
}

function normalizeRooms(data) {
  if (Array.isArray(data)) return data
  if (Array.isArray(data?.meetings)) return data.meetings
  if (Array.isArray(data?.rooms)) return data.rooms
  if (Array.isArray(data?.items)) return data.items
  return []
}

function normalizeAgents(data) {
  if (Array.isArray(data)) return data
  if (Array.isArray(data?.agents)) return data.agents
  if (Array.isArray(data?.items)) return data.items
  return []
}

function formatWhen(v) {
  if (!v) return '—'
  try {
    const d = new Date(v)
    if (Number.isNaN(d.getTime())) return '—'
    return d.toLocaleString()
  } catch {
    return '—'
  }
}

function roomKey(row, index) {
  if (row?.id != null) return String(row.id)
  return `room-${index}-${row?.title || 'x'}`
}

export default function Meetings() {
  const nav = useNavigate()
  const [rooms, setRooms] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [statusFilter, setStatusFilter] = useState('all')
  const [createOpen, setCreateOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [agents, setAgents] = useState([])
  const [agentsLoaded, setAgentsLoaded] = useState(false)
  const [form] = Form.useForm()

  const load = (opts = {}) => {
    const quiet = Boolean(opts.quiet)
    if (!quiet) setLoading(true)
    setError(null)
    return api('/meetings')
      .then((data) => {
        const list = normalizeRooms(data)
          .filter((r) => r && typeof r === 'object')
          .map((r) => ({
            ...r,
            id: r.id,
            title: r.title || `Meeting #${r.id ?? ''}`,
            status: (r.status || 'open').toLowerCase(),
            room_type: (r.room_type || 'brainstorm').toLowerCase(),
          }))
        setRooms(list)
      })
      .catch((e) => {
        const msg = e?.message || 'Failed to load meetings'
        setError(msg)
        message.error(msg)
        if (!quiet) setRooms([])
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    api('/agents/')
      .then((a) => setAgents(normalizeAgents(a).filter((x) => x && x.id != null)))
      .catch(() => setAgents([]))
      .finally(() => setAgentsLoaded(true))
  }, [])

  const filtered = useMemo(() => {
    if (statusFilter === 'all') return rooms
    return rooms.filter((r) => (r.status || 'open') === statusFilter)
  }, [rooms, statusFilter])

  const statusCounts = useMemo(() => {
    const counts = { open: 0, active: 0, closed: 0, total: rooms.length }
    for (const r of rooms) {
      const s = (r.status || 'open').toLowerCase()
      if (s in counts) counts[s] += 1
    }
    return counts
  }, [rooms])

  const create = async (values) => {
    setSaving(true)
    try {
      const title = (values.title || '').trim()
      if (!title) {
        message.error('Title required')
        return
      }
      const agentIds = (Array.isArray(values.agent_ids) ? values.agent_ids : [])
        .filter((aid) => aid != null)
      // If user only picks participants, first agent chairs so room is not agent-empty
      const chairId = values.chair_agent_id || agentIds[0] || null
      const body = {
        title,
        purpose: (values.purpose || '').trim(),
        room_type: values.room_type || 'brainstorm',
        chair_agent_id: chairId,
        participants: agentIds
          .filter((aid) => aid !== chairId)
          .map((agent_id) => ({ kind: 'agent', agent_id, role: 'member' })),
      }
      const room = await api('/meetings', { method: 'POST', body })
      const roomId = room?.id ?? room?.meeting_id ?? room?.meeting?.id
      if (roomId == null) throw new Error('Meeting created but no id returned')
      message.success('Meeting opened')
      setCreateOpen(false)
      form.resetFields()
      nav(`/meetings/${roomId}`)
    } catch (e) {
      message.error(e?.message || 'Failed to create meeting')
    } finally {
      setSaving(false)
    }
  }

  const columns = [
    {
      title: 'Title',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (t, row) => (
        <Space>
          <CommentOutlined />
          <a
            onClick={(e) => {
              e.stopPropagation()
              if (row?.id != null) nav(`/meetings/${row.id}`)
            }}
          >
            {t || (row?.id != null ? `Meeting #${row.id}` : 'Meeting')}
          </a>
        </Space>
      ),
    },
    {
      title: 'Type',
      dataIndex: 'room_type',
      key: 'room_type',
      width: 140,
      render: (v) => {
        const type = (v || 'brainstorm').toLowerCase()
        return (
          <Tag color={TYPE_COLOR[type] || 'default'}>
            {type.replace(/_/g, ' ')}
          </Tag>
        )
      },
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (v) => {
        const s = (v || 'open').toLowerCase()
        return <Tag color={STATUS_COLOR[s] || 'default'}>{s}</Tag>
      },
    },
    {
      title: 'Participants',
      key: 'participants',
      width: 120,
      render: (_, row) => {
        const n = row.participant_count ?? (Array.isArray(row.participants) ? row.participants.length : null)
        return n != null ? (
          <Space size={4}>
            <TeamOutlined />
            <Text>{n}</Text>
          </Space>
        ) : (
          <Text type="secondary">—</Text>
        )
      },
    },
    {
      title: 'Messages',
      dataIndex: 'message_count',
      key: 'message_count',
      width: 100,
      render: (v) => (v != null ? v : <Text type="secondary">—</Text>),
    },
    {
      title: 'Created',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (v) => formatWhen(v),
    },
  ]

  const showInitialLoading = loading && rooms.length === 0 && !error
  const showErrorEmpty = error && rooms.length === 0 && !loading
  const showEmpty = !loading && !error && rooms.length === 0
  const showFilteredEmpty = !loading && !error && rooms.length > 0 && filtered.length === 0
  const showListChrome = !showInitialLoading && !showErrorEmpty && !showEmpty

  const headerExtra = (
    <Space wrap>
      <Button
        icon={<ReloadOutlined />}
        onClick={() => load({ quiet: rooms.length > 0 })}
        loading={loading}
      >
        Refresh
      </Button>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
        New meeting
      </Button>
    </Space>
  )

  return (
    <PageShell>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {/* Header — boxed Card */}
        <Card className="aba-soft-card" styles={{ body: { paddingBlock: 16 } }}>
          <PageHeader
            title={(
              <span>
                <CommentOutlined style={{ marginRight: 8 }} />
                Meetings
                {rooms.length > 0 && (
                  <Tag color="blue" style={{ marginInlineStart: 10, verticalAlign: 'middle' }}>
                    {rooms.length}
                  </Tag>
                )}
              </span>
            )}
            subtitle="Human + agent brainstorm rooms and war rooms — open a room, run rounds, extract tasks."
            style={{ marginBottom: 0 }}
            extra={headerExtra}
          />
        </Card>

        {error && rooms.length > 0 && (
          <Card className="aba-soft-card" size="small">
            <Alert
              type="warning"
              showIcon
              closable
              message="Could not refresh meetings"
              description={error}
              action={<Button size="small" onClick={() => load({ quiet: true })}>Retry</Button>}
              onClose={() => setError(null)}
              style={{ marginBottom: 0 }}
            />
          </Card>
        )}

        {/* Status summary — only when we have rooms */}
        {showListChrome && (
          <Row gutter={[12, 12]}>
            <Col xs={12} sm={6}>
              <Card
                size="small"
                className="aba-stat-card aba-soft-card"
                hoverable
                onClick={() => setStatusFilter('all')}
              >
                <Statistic
                  title="Total rooms"
                  value={statusCounts.total}
                  prefix={<CommentOutlined style={{ color: '#7c3aed' }} />}
                />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card
                size="small"
                className="aba-stat-card aba-soft-card"
                hoverable
                onClick={() => setStatusFilter('open')}
              >
                <Statistic
                  title="Open"
                  value={statusCounts.open}
                  prefix={<PlayCircleOutlined style={{ color: '#1668dc' }} />}
                  valueStyle={statusFilter === 'open' ? { color: '#1668dc' } : undefined}
                />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card
                size="small"
                className="aba-stat-card aba-soft-card"
                hoverable
                onClick={() => setStatusFilter('active')}
              >
                <Statistic
                  title="Active"
                  value={statusCounts.active}
                  prefix={<CheckCircleOutlined style={{ color: '#16a34a' }} />}
                  valueStyle={statusFilter === 'active' ? { color: '#16a34a' } : undefined}
                />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card
                size="small"
                className="aba-stat-card aba-soft-card"
                hoverable
                onClick={() => setStatusFilter('closed')}
              >
                <Statistic
                  title="Closed"
                  value={statusCounts.closed}
                  prefix={<StopOutlined style={{ color: '#8c8c8c' }} />}
                  valueStyle={statusFilter === 'closed' ? { color: '#8c8c8c' } : undefined}
                />
              </Card>
            </Col>
          </Row>
        )}

        {/* Rooms table + empty / loading / error states — all inside one Card */}
        <Card
          className="aba-soft-card"
          title={showListChrome ? (
            <Space size={8}>
              <TeamOutlined />
              <span>Rooms</span>
              {!loading && (
                <Tag style={{ marginInlineStart: 4 }}>
                  {statusFilter === 'all' ? filtered.length : `${filtered.length} / ${rooms.length}`}
                </Tag>
              )}
            </Space>
          ) : undefined}
          extra={showListChrome ? (
            <Segmented
              size="small"
              options={STATUS_FILTERS}
              value={statusFilter}
              onChange={setStatusFilter}
            />
          ) : undefined}
          styles={{
            body: (showInitialLoading || showEmpty || showErrorEmpty || showFilteredEmpty)
              ? emptyCardBody
              : { paddingInline: 12, paddingTop: 8, paddingBottom: 12, overflow: 'hidden' },
          }}
        >
          {showInitialLoading ? (
            <div style={{ textAlign: 'center', padding: 48, width: '100%' }}>
              <Spin size="large" tip="Loading meetings…" />
            </div>
          ) : showErrorEmpty ? (
            <Empty
              style={{ width: '100%', marginBlock: 0 }}
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={(
                <span>
                  Could not load meetings
                  <br />
                  <Text type="secondary">{error}</Text>
                </span>
              )}
            >
              <Button type="primary" onClick={() => load()}>Retry</Button>
            </Empty>
          ) : showEmpty ? (
            <Empty
              style={{ width: '100%', marginBlock: 0 }}
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={(
                <span>
                  No meeting rooms yet
                  <br />
                  <Text type="secondary">
                    Open a room to brainstorm with agents or run a task war room.
                  </Text>
                </span>
              )}
            >
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
                Open first meeting
              </Button>
            </Empty>
          ) : showFilteredEmpty ? (
            <Empty
              style={{ width: '100%', marginBlock: 0 }}
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={`No ${statusFilter} meetings`}
            >
              <Button onClick={() => setStatusFilter('all')}>Show all</Button>
            </Empty>
          ) : (
            <Table
              size="middle"
              rowKey={(row, index) => roomKey(row, index)}
              columns={columns}
              dataSource={filtered}
              loading={loading}
              pagination={{
                pageSize: 20,
                showSizeChanger: true,
                showTotal: (t) => `${t} meeting${t === 1 ? '' : 's'}`,
              }}
              locale={{
                emptyText: (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="No meetings match"
                  />
                ),
              }}
              onRow={(row) => ({
                onClick: () => {
                  if (row?.id != null) nav(`/meetings/${row.id}`)
                },
                style: { cursor: row?.id != null ? 'pointer' : 'default' },
              })}
            />
          )}
        </Card>
      </Space>

      <Modal
        title="New meeting"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); form.resetFields() }}
        onOk={() => form.submit()}
        confirmLoading={saving}
        destroyOnClose
        okText="Open room"
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={create}
          initialValues={{ room_type: 'brainstorm' }}
        >
          <Form.Item
            name="title"
            label="Title"
            rules={[
              { required: true, message: 'Title required' },
              { whitespace: true, message: 'Title required' },
            ]}
          >
            <Input placeholder="e.g. Q3 pipeline brainstorm" maxLength={240} showCount />
          </Form.Item>
          <Form.Item name="purpose" label="Purpose">
            <TextArea rows={2} placeholder="What should this room achieve?" maxLength={2000} />
          </Form.Item>
          <Form.Item name="room_type" label="Type">
            <Select options={ROOM_TYPES} />
          </Form.Item>
          {agentsLoaded && agents.length === 0 && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message="No agents yet — open a room anyway, then use Add agents inside the meeting."
            />
          )}
          <Form.Item name="chair_agent_id" label="Chair agent">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder={agents.length ? 'Optional facilitator agent' : 'No agents available'}
              disabled={!agents.length}
              options={agents.map((a) => ({
                value: a.id,
                label: `${a.name || `Agent #${a.id}`}${a.role ? ` · ${a.role}` : ''}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="agent_ids" label="Agent participants">
            <Select
              mode="multiple"
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder={agents.length ? 'Invite agents' : 'No agents available'}
              disabled={!agents.length}
              options={agents.map((a) => ({
                value: a.id,
                label: `${a.name || `Agent #${a.id}`}${a.role ? ` · ${a.role}` : ''}`,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </PageShell>
  )
}
