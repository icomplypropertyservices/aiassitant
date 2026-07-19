import React, { useEffect, useState } from 'react'
import {
  Card, Row, Col, Table, Statistic, Collapse, Typography, Empty, Spin, Button,
} from 'antd'
import { BarChartOutlined, ReloadOutlined } from '@ant-design/icons'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../api'
import PageShell from '../components/PageShell'
import InfoDrawer, { InfoEmpty } from '../components/InfoDrawer'

export default function Analytics() {
  const [usage, setUsage] = useState(null)
  const [loading, setLoading] = useState(true)
  const [modelOpen, setModelOpen] = useState(null)

  const load = () => {
    setLoading(true)
    api('/billing/usage')
      .then(setUsage)
      .catch(() => setUsage(null))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const models = Object.entries(usage?.by_model || {}).map(([k, v]) => ({
    key: k,
    model_key: k,
    ...v,
  }))

  return (
    <PageShell
      title={(
        <span>
          <BarChartOutlined style={{ marginRight: 8 }} />
          Analytics
        </span>
      )}
      subtitle="Token usage and cost breakdown for your workspace."
      extra={(
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading} className="aba-touch-btn">
          Refresh
        </Button>
      )}
    >
      <Collapse
        className="aba-soft-card"
        style={{ background: '#fff' }}
        items={[{
          key: 'help',
          label: 'What this page shows',
          children: (
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
              Totals cover your workspace token meter and wallet spend. Charts use the last 7 days
              when available. Tap a model row to open a detail card.
            </Typography.Paragraph>
          ),
        }]}
      />

      {loading && !usage ? (
        <Card className="aba-soft-card">
          <div style={{ textAlign: 'center', padding: 40 }}><Spin size="large" tip="Loading analytics…" /></div>
        </Card>
      ) : (
        <>
          <Row gutter={[12, 12]} justify="center">
            <Col xs={12} sm={8} md={6}>
              <Card className="aba-stat-card aba-soft-card" size="small">
                <Statistic title="Total tokens" value={usage?.total_tokens ?? 0} />
              </Card>
            </Col>
            <Col xs={12} sm={8} md={6}>
              <Card className="aba-stat-card aba-soft-card" size="small">
                <Statistic title="Total cost" prefix="$" precision={4} value={usage?.total_cost ?? 0} />
              </Card>
            </Col>
            <Col xs={12} sm={8} md={6}>
              <Card className="aba-stat-card aba-soft-card" size="small">
                <Statistic title="Models used" value={models.length} />
              </Card>
            </Col>
          </Row>

          <Card className="aba-soft-card" title="Tokens — last 7 days">
            {(usage?.daily || []).length === 0 ? (
              <InfoEmpty
                title="No daily data yet"
                description="Send a few chats or agent runs and refresh this page."
              />
            ) : (
              <div style={{ width: '100%', minHeight: 240 }}>
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={usage?.daily || []}>
                    <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                    <YAxis width={48} tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Bar dataKey="tokens" fill="#1668dc" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>

          <Card className="aba-soft-card" title="Usage by model">
            {models.length === 0 ? (
              <Empty description="No model usage yet" />
            ) : (
              <Table
                pagination={false}
                dataSource={models}
                scroll={{ x: true }}
                onRow={(record) => ({
                  onClick: () => setModelOpen(record),
                  className: 'aba-click-row',
                })}
                columns={[
                  { title: 'Model', dataIndex: 'label', render: (v, r) => v || r.model_key || r.key },
                  {
                    title: 'Tokens',
                    dataIndex: 'tokens',
                    render: (v) => Number(v || 0).toLocaleString(),
                  },
                  {
                    title: 'Cost',
                    dataIndex: 'cost',
                    render: (v) => `$${Number(v || 0).toFixed(4)}`,
                  },
                ]}
              />
            )}
          </Card>
        </>
      )}

      <InfoDrawer
        open={!!modelOpen}
        onClose={() => setModelOpen(null)}
        title={modelOpen?.label || modelOpen?.model_key || 'Model usage'}
        subtitle="Tap outside or close to dismiss"
      >
        {modelOpen && (
          <Row gutter={[12, 12]}>
            <Col span={12}>
              <Card size="small" className="aba-stat-card">
                <Statistic title="Tokens" value={Number(modelOpen.tokens || 0)} />
              </Card>
            </Col>
            <Col span={12}>
              <Card size="small" className="aba-stat-card">
                <Statistic title="Cost" prefix="$" precision={4} value={Number(modelOpen.cost || 0)} />
              </Card>
            </Col>
            <Col span={24}>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                Key: <Typography.Text code>{modelOpen.model_key || modelOpen.key}</Typography.Text>
              </Typography.Paragraph>
            </Col>
          </Row>
        )}
      </InfoDrawer>
    </PageShell>
  )
}
