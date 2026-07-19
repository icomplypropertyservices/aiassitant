import React, { useEffect, useMemo, useState } from 'react'
import {
  Row, Col, Card, Tag, Button, Input, Typography, Space, Segmented, Empty, Collapse, Descriptions,
} from 'antd'
import { useNavigate } from 'react-router-dom'
import { AppstoreOutlined, RocketOutlined } from '@ant-design/icons'
import { api } from '../api'
import PageShell from '../components/PageShell'
import InfoDrawer, { InfoEmpty } from '../components/InfoDrawer'

const TYPE_COLOR = {
  sales: 'blue', support: 'cyan', marketing: 'purple', content: 'purple',
  coding: 'geekblue', ops: 'orange', booking: 'green', reviews: 'gold',
}

export default function Templates() {
  const nav = useNavigate()
  const [templates, setTemplates] = useState([])
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('all')
  const [open, setOpen] = useState(null)

  useEffect(() => {
    const normalize = (t) => (
      Array.isArray(t) ? t
        : Array.isArray(t?.templates) ? t.templates
          : Array.isArray(t?.items) ? t.items
            : []
    )
    api('/templates/')
      .then(async (t) => {
        let list = normalize(t)
        if (!list.length) {
          try { await api('/templates/ensure', { method: 'POST' }) } catch { /* ignore */ }
          list = normalize(await api('/templates/'))
        }
        setTemplates(list)
      })
      .catch(() => setTemplates([]))
  }, [])

  const categories = useMemo(() => {
    const types = [...new Set(templates.map(t => t.type))].sort()
    return ['all', ...types]
  }, [templates])

  const filtered = templates.filter(t => {
    const q = search.toLowerCase()
    const matchQ = !q || (t.name + t.description + t.type).toLowerCase().includes(q)
    const matchC = category === 'all' || t.type === category
    return matchQ && matchC
  })

  const useTemplate = (t) => {
    setOpen(null)
    nav('/agents', { state: { templateId: t.id || t.template_type || t.type } })
  }

  return (
    <PageShell
      title={(
        <span>
          <AppstoreOutlined style={{ marginRight: 8 }} />
          Templates
        </span>
      )}
      subtitle="Browse ready-made agent templates and spawn one into your workspace."
    >
      <Collapse
        className="aba-soft-card"
        style={{ marginBottom: 0, background: '#fff' }}
        items={[{
          key: 'help',
          label: 'How templates work',
          children: (
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
              Tap any template card to open full details. Use <strong>Use template</strong> to open
              the agent console with that template pre-selected. Categories filter by role (sales,
              support, coding, and more).
            </Typography.Paragraph>
          ),
        }]}
      />

      <Card
        className="aba-soft-card"
        size="small"
        styles={{ body: { padding: '12px 16px' } }}
      >
        <Space
          direction="vertical"
          style={{ width: '100%' }}
          size="middle"
        >
          <Input.Search
            placeholder="Search templates (coder, sales, support…)"
            style={{ width: '100%' }}
            onChange={e => setSearch(e.target.value)}
            allowClear
            size="large"
          />
          <div style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch', width: '100%' }}>
            <Segmented
              options={categories.map(c => ({
                label: c === 'all' ? 'All' : c.charAt(0).toUpperCase() + c.slice(1),
                value: c,
              }))}
              value={category}
              onChange={setCategory}
              block={categories.length <= 4}
            />
          </div>
          <Typography.Text type="secondary" style={{ display: 'block', textAlign: 'center' }}>
            {filtered.length} template{filtered.length === 1 ? '' : 's'}
          </Typography.Text>
        </Space>
      </Card>

      <Card className="aba-soft-card" styles={{ body: { paddingTop: 16 } }}>
        {filtered.length === 0 ? (
          <InfoEmpty
            title={templates.length ? 'No matches' : 'No templates yet'}
            description={
              templates.length
                ? 'Try another search or category.'
                : 'Templates will appear after the catalog is seeded.'
            }
          />
        ) : (
          <Row gutter={[16, 16]} justify="center">
            {filtered.map(t => (
              <Col xs={24} sm={12} xl={8} key={t.id || t.name}>
                <Card
                  className="aba-soft-card aba-card-clickable"
                  size="small"
                  title={t.name}
                  extra={<Tag color={TYPE_COLOR[t.type] || 'blue'}>{t.type}</Tag>}
                  style={{ height: '100%' }}
                  onClick={() => setOpen(t)}
                  actions={[
                    <Button
                      key="use"
                      type="link"
                      icon={<RocketOutlined />}
                      className="aba-touch-btn"
                      onClick={(e) => {
                        e.stopPropagation()
                        useTemplate(t)
                      }}
                    >
                      Use template
                    </Button>,
                    <Button
                      key="info"
                      type="link"
                      className="aba-touch-btn"
                      onClick={(e) => {
                        e.stopPropagation()
                        setOpen(t)
                      }}
                    >
                      Details
                    </Button>,
                  ]}
                >
                  <Typography.Paragraph ellipsis={{ rows: 3 }} style={{ marginBottom: 12 }}>
                    {t.description || 'No description'}
                  </Typography.Paragraph>
                  {t.est_cost != null && (
                    <Tag color="green">Est. cost: {t.est_cost}</Tag>
                  )}
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Card>

      <InfoDrawer
        open={!!open}
        onClose={() => setOpen(null)}
        title={open?.name}
        subtitle={open?.type ? `Type: ${open.type}` : undefined}
        footer={(
          <Button type="primary" size="large" block icon={<RocketOutlined />} onClick={() => open && useTemplate(open)}>
            Use this template
          </Button>
        )}
      >
        {open && (
          <>
            <Typography.Paragraph>
              {open.description || 'No description provided.'}
            </Typography.Paragraph>
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="Type">{open.type || '—'}</Descriptions.Item>
              {open.est_cost != null && (
                <Descriptions.Item label="Est. cost">{open.est_cost}</Descriptions.Item>
              )}
              {open.id != null && (
                <Descriptions.Item label="ID">{String(open.id)}</Descriptions.Item>
              )}
              {open.template_type && (
                <Descriptions.Item label="Template key">{open.template_type}</Descriptions.Item>
              )}
              {open.default_model && (
                <Descriptions.Item label="Default model">{open.default_model}</Descriptions.Item>
              )}
            </Descriptions>
            {Array.isArray(open.skills) && open.skills.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <Typography.Text strong>Suggested skills</Typography.Text>
                <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {open.skills.slice(0, 24).map((s) => (
                    <Tag key={String(s)}>{typeof s === 'string' ? s : s.id || s.name}</Tag>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </InfoDrawer>
    </PageShell>
  )
}
