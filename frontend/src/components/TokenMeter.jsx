import React from 'react'
import { Progress, Space, Typography, Tooltip, Tag } from 'antd'
import { ThunderboltOutlined, WalletOutlined } from '@ant-design/icons'

function fmt(n) {
  if (n == null) return '0'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

function meterSeverity(meter) {
  const used = meter.tokens_used_period ?? 0
  const included = meter.tokens_included ?? 0
  const pct = meter.usage_percent != null
    ? Number(meter.usage_percent)
    : (included ? Math.min(100, (used / included) * 100) : 0)
  const hard = meter.hard_block || pct >= 100
  const warn = meter.warn || pct >= 80
  if (hard) return { level: 'hard', pct: Math.min(100, Math.round(pct)), tagColor: 'error', progressStatus: 'exception' }
  if (warn) return { level: 'warn', pct: Math.min(100, Math.round(pct)), tagColor: 'orange', progressStatus: 'active' }
  return {
    level: 'ok',
    pct: Math.min(100, Math.round(pct)),
    tagColor: pct >= 70 ? 'blue' : 'blue',
    progressStatus: pct >= 70 ? 'active' : 'success',
  }
}

/** Compact header meter — clear for customers */
export default function TokenMeter({ meter, compact = true }) {
  if (!meter) {
    return <Tag icon={<ThunderboltOutlined />} color="default">Tokens —</Tag>
  }
  const used = meter.tokens_used_period ?? 0
  const included = meter.tokens_included ?? 0
  const remaining = meter.tokens_remaining_included ?? Math.max(0, included - used)
  const { pct, tagColor, progressStatus, level } = meterSeverity(meter)
  const title = (
    <div style={{ maxWidth: 260 }}>
      <div><strong>This month</strong></div>
      <div>Used: {fmt(used)} / {fmt(included)} included</div>
      <div>Remaining included: {fmt(remaining)}</div>
      <div>Wallet credits: ${Number(meter.credits || 0).toFixed(2)}</div>
      {level === 'hard' && <div style={{ color: '#ff4d4f', marginTop: 4 }}>Included pool exhausted</div>}
      {level === 'warn' && <div style={{ color: '#fa8c16', marginTop: 4 }}>Included tokens running low</div>}
      <div style={{ opacity: 0.8, marginTop: 4 }}>
        Included tokens cover VPS/Qwen. Premium Claude/Grok bill credits.
        Overage after the pool also uses credits.
      </div>
    </div>
  )

  if (compact) {
    return (
      <Tooltip title={title}>
        <Space size={8} style={{ cursor: 'help' }}>
          <Tag icon={<ThunderboltOutlined />} color={tagColor} style={{ margin: 0 }}>
            {fmt(used)} / {fmt(included)} tokens
          </Tag>
          <Progress
            percent={included ? pct : 0}
            size="small"
            status={progressStatus}
            showInfo={false}
            strokeColor={level === 'warn' ? '#fa8c16' : undefined}
            style={{ width: 72, margin: 0 }}
          />
          <Tag icon={<WalletOutlined />} color="gold" style={{ margin: 0 }}>
            ${Number(meter.credits || 0).toFixed(2)}
          </Tag>
        </Space>
      </Tooltip>
    )
  }

  return (
    <div>
      <Space style={{ marginBottom: 8 }}>
        <Typography.Text strong>Token usage this month</Typography.Text>
        <Tag>{meter.plan_name || meter.plan}</Tag>
        {level === 'hard' && <Tag color="error">Hard limit</Tag>}
        {level === 'warn' && <Tag color="orange">Running low</Tag>}
      </Space>
      <Progress
        percent={included ? pct : 0}
        status={progressStatus}
        strokeColor={level === 'warn' ? '#fa8c16' : undefined}
      />
      <Space split="·" wrap>
        <span>Used <strong>{fmt(used)}</strong></span>
        <span>Included <strong>{fmt(included)}</strong></span>
        <span>Left <strong>{fmt(remaining)}</strong></span>
        <span>Credits <strong>${Number(meter.credits || 0).toFixed(2)}</strong></span>
      </Space>
    </div>
  )
}
