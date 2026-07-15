import React, { useEffect, useMemo, useState } from 'react'
import { Row, Col, Card, Tag, Button, Input, Typography, Space, Segmented } from 'antd'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

const TYPE_COLOR = {
  sales: 'blue', support: 'cyan', marketing: 'purple', content: 'purple',
  coding: 'geekblue', ops: 'orange', booking: 'green', reviews: 'gold',
}

export default function Templates() {
  const nav = useNavigate()
  const [templates, setTemplates] = useState([])
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('all')

  useEffect(() => { api('/templates/').then(setTemplates).catch(() => {}) }, [])

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

  return (
    <div>
      <Space wrap style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Space wrap>
          <Input.Search
            placeholder="Search templates (coder, sales, support…)"
            style={{ width: 320 }}
            onChange={e => setSearch(e.target.value)}
            allowClear
          />
          <Typography.Text type="secondary">{filtered.length} templates</Typography.Text>
        </Space>
        <Segmented
          options={categories.map(c => ({
            label: c === 'all' ? 'All' : c.charAt(0).toUpperCase() + c.slice(1),
            value: c,
          }))}
          value={category}
          onChange={setCategory}
        />
      </Space>
      <Row gutter={[16, 16]}>
        {filtered.map(t => (
          <Col xs={24} md={12} xl={8} key={t.id}>
            <Card
              title={t.name}
              extra={<Tag color={TYPE_COLOR[t.type] || 'blue'}>{t.type}</Tag>}
              actions={[
                <Button key="use" type="link" onClick={() => nav('/agents', { state: { templateId: t.id } })}>
                  Use Template
                </Button>,
              ]}
            >
              <Typography.Paragraph ellipsis={{ rows: 3 }}>{t.description}</Typography.Paragraph>
              <Tag color="green">Estimated cost: {t.est_cost}</Tag>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  )
}
