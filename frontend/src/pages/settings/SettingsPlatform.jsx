import React, { useEffect, useState } from 'react'
import {
  Card, Typography, Alert, Tag, Space, Spin,
} from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined, CloudOutlined,
} from '@ant-design/icons'
import { getUser, API, api } from '../../api'

const { Text, Paragraph } = Typography

function StatusTag({ ok, label }) {
  return (
    <Tag icon={ok ? <CheckCircleOutlined /> : <CloseCircleOutlined />} color={ok ? 'success' : 'default'}>
      {label}: {ok ? 'live' : 'not configured'}
    </Tag>
  )
}

export default function SettingsPlatform() {
  const user = getUser()
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const embed = `<script src="${API}/embed.js" data-business="${user?.email || ''}"></script>`

  useEffect(() => {
    api('/system/status')
      .then(setStatus)
      .catch(() => setStatus(null))
      .finally(() => setLoading(false))
  }, [])

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title={<Space><CloudOutlined /> Platform status</Space>}
        className="aba-soft-card"
        type="inner"
      >
        <Paragraph type="secondary" style={{ marginBottom: 12 }}>
          Platform-level keys (server <Text code>.env</Text>). Your vault keys and Connected apps take priority when present.
        </Paragraph>
        {loading ? (
          <Spin />
        ) : status ? (
          <Space wrap>
            <Tag color="blue">Environment: {status.environment}</Tag>
            <Tag color="blue">Database: {status.database?.driver}</Tag>
          </Space>
        ) : (
          <Alert type="error" message="Could not load system status" />
        )}
      </Card>

      {loading ? null : status ? (
        <>
          <Card className="aba-soft-card" type="inner" title="LLM (platform)" size="small">
            <Space wrap>
              <StatusTag ok={status.llm?.anthropic} label="Anthropic (Claude)" />
              <StatusTag ok={status.llm?.xai} label="xAI (Grok)" />
              <Tag>Ollama: {status.llm?.ollama_url}</Tag>
            </Space>
          </Card>
          <Card className="aba-soft-card" type="inner" title="Billing" size="small">
            <Space wrap>
              <StatusTag ok={status.billing?.stripe} label="Stripe payments" />
            </Space>
          </Card>
          <Card className="aba-soft-card" type="inner" title="Channels" size="small">
            <Space wrap>
              <StatusTag ok={status.channels?.email_resend} label="Email (Resend)" />
              <StatusTag ok={status.channels?.sms_twilio} label="SMS (Twilio)" />
            </Space>
          </Card>
          <Card className="aba-soft-card" type="inner" title="OAuth apps (server)" size="small">
            <Space wrap>
              {status.oauth ? Object.entries(status.oauth).map(([k, v]) => (
                <StatusTag key={k} ok={v} label={k} />
              )) : (
                <Text type="secondary">No OAuth status</Text>
              )}
            </Space>
          </Card>
        </>
      ) : null}

      <Card title="Website embed" className="aba-soft-card" type="inner">
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="Paste this on your website to add your AI assistant (embed widget ships in a later build)."
        />
        <Paragraph copyable code>{embed}</Paragraph>
      </Card>
    </Space>
  )
}
