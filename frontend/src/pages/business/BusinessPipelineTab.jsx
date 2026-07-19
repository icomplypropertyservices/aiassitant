import React from 'react'
import {
  Card, Button, Space, Tag, Typography, Select, Badge, Empty, Spin,
} from 'antd'
import { PlusOutlined, HolderOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { STATUS_COLOR } from './constants'

const { Text } = Typography

/**
 * Pipeline deal board tab for Business CRM.
 */
export default function BusinessPipelineTab({
  overview,
  pipelines,
  pipelineId,
  setPipelineId,
  board,
  setDragDeal,
  onDropDeal,
  dealForm,
  setDealOpen,
}) {
  const nav = useNavigate()

  return (
    <Card
      type="inner"
      className="aba-soft-card"
      title="Deal board"
      extra={(
        <Space wrap>
          <Select
            style={{ minWidth: 200 }}
            value={pipelineId}
            onChange={setPipelineId}
            options={(overview?.pipelines || pipelines || []).map((p) => ({
              value: p.id,
              label: `${p.name}${p.is_default ? ' (default)' : ''}`,
            }))}
          />
          <Button
            size="small"
            icon={<PlusOutlined />}
            onClick={() => {
              dealForm.setFieldsValue({})
              setDealOpen(true)
            }}
            disabled={!pipelineId}
          >
            Add deal
          </Button>
        </Space>
      )}
      styles={{ body: { overflowX: 'auto' } }}
    >
      <Text type="secondary" style={{ display: 'block', marginBottom: 12, textAlign: 'center' }}>
        Drag deals between columns · click deal for customer
      </Text>

      {!board ? (
        <Card size="small" className="aba-soft-card" styles={{ body: { textAlign: 'center', padding: 40 } }}>
          <Spin />
        </Card>
      ) : (
        <div
          style={{
            display: 'flex',
            gap: 12,
            overflowX: 'auto',
            paddingBottom: 12,
            minHeight: 420,
          }}
        >
          {(board.board || []).map((stage) => (
            <Card
              key={stage.id}
              size="small"
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => onDropDeal(stage.id)}
              title={(
                <span>
                  <strong>{stage.name}</strong>
                  <Text type="secondary" style={{ fontSize: 12, marginLeft: 8, fontWeight: 400 }}>
                    ${Number(stage.value || 0).toLocaleString()}
                    {stage.stage_type !== 'open' && ` · ${stage.stage_type}`}
                  </Text>
                </span>
              )}
              extra={(
                <Badge
                  count={stage.count || 0}
                  showZero
                  style={{ background: stage.color || '#1668dc' }}
                />
              )}
              styles={{
                header: {
                  borderBottom: `2px solid ${stage.color || '#1668dc'}`,
                  minHeight: 44,
                },
                body: {
                  background: '#f5f5f5',
                  padding: 8,
                  minHeight: 200,
                  maxHeight: 'calc(100vh - 360px)',
                  overflowY: 'auto',
                },
              }}
              style={{
                minWidth: 260,
                maxWidth: 280,
                flex: '0 0 260px',
                borderRadius: 10,
              }}
            >
              {(stage.deals || []).map((d) => (
                <Card
                  key={d.id}
                  size="small"
                  draggable
                  onDragStart={() => setDragDeal(d)}
                  onDragEnd={() => setDragDeal(null)}
                  style={{
                    marginBottom: 8,
                    cursor: 'grab',
                    borderLeft: d.status === 'won' ? '3px solid #52c41a' : d.status === 'lost' ? '3px solid #ff4d4f' : undefined,
                  }}
                  styles={{ body: { padding: 10 } }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 4 }}>
                    <HolderOutlined style={{ color: '#bfbfbf' }} />
                    <div style={{ flex: 1 }}>
                      <Button
                        type="link"
                        style={{ padding: 0, height: 'auto', fontWeight: 600 }}
                        onClick={() => nav(`/business/customers/${d.customer_id}`)}
                      >
                        {d.title}
                      </Button>
                      <div>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {d.customer_name}
                          {d.account_name ? ` · ${d.account_name}` : ''}
                        </Text>
                      </div>
                      <Space size={4} style={{ marginTop: 4 }} wrap>
                        <Tag color="gold">${Number(d.value || 0).toLocaleString()}</Tag>
                        <Tag>{d.priority}</Tag>
                        {d.status !== 'open' && <Tag color={STATUS_COLOR[d.status]}>{d.status}</Tag>}
                      </Space>
                    </div>
                  </div>
                </Card>
              ))}
              {!stage.deals?.length && (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Drop deals here" />
              )}
            </Card>
          ))}
          {!(board.board || []).length && (
            <Empty description="No stages on this pipeline" style={{ margin: '40px auto' }} />
          )}
        </div>
      )}
    </Card>
  )
}
