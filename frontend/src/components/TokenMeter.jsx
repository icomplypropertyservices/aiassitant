import React from 'react'
import { Progress, Space, Typography, Tooltip, Tag, Statistic, Row, Col } from 'antd'
import { ThunderboltOutlined, WalletOutlined, FireOutlined, CloudServerOutlined } from '@ant-design/icons'

const { Text } = Typography

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
  if (hard) {
    return {
      level: 'hard',
      pct: Math.min(100, Math.round(pct)),
      tagColor: 'error',
      progressStatus: 'exception',
      stroke: 'var(--aba-danger, #dc2626)',
    }
  }
  if (warn) {
    return {
      level: 'warn',
      pct: Math.min(100, Math.round(pct)),
      tagColor: 'orange',
      progressStatus: 'active',
      stroke: 'var(--aba-warning, #d97706)',
    }
  }
  return {
    level: 'ok',
    pct: Math.min(100, Math.round(pct)),
    tagColor: 'blue',
    progressStatus: pct >= 70 ? 'active' : 'success',
    stroke: 'var(--aba-primary, #1668dc)',
  }
}

function trialDaysLeft(meter) {
  const exp = meter?.subscription_expires_at
  const plan = meter?.plan
  if (!exp || plan !== 'trial') return null
  const d = new Date(exp)
  if (Number.isNaN(d.getTime())) return null
  return Math.ceil((d.getTime() - Date.now()) / 86400000)
}

function trialLabel(days) {
  if (days == null) return null
  if (days < 0) return 'Trial expired'
  if (days === 0) return 'Trial ends today'
  return `Trial · ${days} day${days === 1 ? '' : 's'} left`
}

/** Compact header meter — clear for customers. Click opens Billing. */
export default function TokenMeter({ meter, compact = true, onClick }) {
  const clickable = typeof onClick === 'function'
  const chipProps = clickable
    ? {
        role: 'button',
        tabIndex: 0,
        onClick,
        onKeyDown: (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onClick(e)
          }
        },
        style: { cursor: 'pointer' },
        title: 'Open Billing',
      }
    : {}

  if (!meter) {
    return (
      <span
        className={`aba-meter-chip aba-meter-chip--empty${clickable ? ' aba-clickable' : ''}`}
        {...chipProps}
      >
        <Tag
          icon={<ThunderboltOutlined />}
          color="default"
          bordered={false}
          className="aba-meter-tag"
        >
          Tokens —
        </Tag>
      </span>
    )
  }

  const used = meter.tokens_used_period ?? 0
  const included = meter.tokens_included ?? 0
  const remaining = meter.tokens_remaining_included ?? Math.max(0, included - used)
  const { pct, tagColor, progressStatus, level, stroke } = meterSeverity(meter)
  const trialDays = trialDaysLeft(meter)
  const credits = Number(meter.credits || 0)

  const title = (
    <div className="aba-meter-tooltip">
      <div className="aba-meter-tooltip-title">This month</div>
      <div>Used: {fmt(used)} / {fmt(included)} included</div>
      <div>Remaining included: {fmt(remaining)}</div>
      <div>Wallet credits: ${credits.toFixed(2)}</div>
      {meter.storage && (
        <div>
          Storage: {meter.storage.used_human || '—'}
          {' / '}
          {meter.storage.limit_human || '—'}
          {meter.storage.hard_block ? ' · full' : meter.storage.warn ? ' · low' : ''}
        </div>
      )}
      {trialDays != null && (
        <div className="aba-meter-tooltip-trial">{trialLabel(trialDays)}</div>
      )}
      {level === 'hard' && (
        <div className="aba-meter-tooltip-alert is-hard">Included pool exhausted</div>
      )}
      {level === 'warn' && (
        <div className="aba-meter-tooltip-alert is-warn">Included tokens running low</div>
      )}
      <div className="aba-meter-tooltip-hint">
        Included pool first; overage uses wallet credits. Storage is separate — upgrade plan or buy GB packs.
      </div>
    </div>
  )

  const st = meter.storage
  const stPct = st && !st.unlimited ? Math.min(100, Number(st.usage_percent) || 0) : 0
  const stColor = st?.hard_block ? 'error' : st?.warn ? 'orange' : 'default'

  if (compact) {
    return (
      <Tooltip title={title} placement="bottomRight">
        <span
          className={`aba-meter-chip aba-meter-chip--${level}${clickable ? ' aba-clickable' : ''}`}
          role={clickable ? 'button' : 'img'}
          aria-label={`Tokens ${fmt(used)} of ${fmt(included)}, wallet $${credits.toFixed(2)}. Open Billing`}
          {...chipProps}
        >
          <Tag
            icon={<ThunderboltOutlined />}
            color={tagColor}
            bordered={false}
            className="aba-meter-tag"
          >
            {fmt(used)} / {fmt(included)}
          </Tag>
          <Progress
            percent={included ? pct : 0}
            size="small"
            status={progressStatus}
            showInfo={false}
            strokeColor={stroke}
            trailColor="var(--aba-border, #e2e8f0)"
            className="aba-meter-progress"
          />
          <Tag
            icon={<WalletOutlined />}
            color="gold"
            bordered={false}
            className="aba-meter-tag"
          >
            ${credits.toFixed(2)}
          </Tag>
          {st && (
            <Tag
              icon={<CloudServerOutlined />}
              color={stColor}
              bordered={false}
              className="aba-meter-tag"
            >
              {st.used_human || '0'}
              {!st.unlimited ? ` / ${st.limit_human}` : ''}
            </Tag>
          )}
          {meter.auto_topup?.enabled && (
            <Tag color="green" bordered={false} className="aba-meter-tag" icon={<ThunderboltOutlined />}>
              Auto
            </Tag>
          )}
          {(level === 'hard' || level === 'warn') && (
            <Tag color="error" bordered={false} className="aba-meter-tag" icon={<FireOutlined />}>
              Top up
            </Tag>
          )}
          {trialDays != null && trialDays >= 0 && (
            <Tag
              color={trialDays <= 3 ? 'orange' : 'cyan'}
              bordered={false}
              className="aba-meter-tag"
            >
              {trialDays === 0 ? 'Trial ends today' : `Trial ${trialDays}d`}
            </Tag>
          )}
        </span>
      </Tooltip>
    )
  }

  return (
    <div className="aba-meter-full">
      <div className="aba-meter-full-head">
        <Space size={[8, 8]} wrap align="center" className="aba-meter-full-tags">
          <Text strong className="aba-meter-full-title">
            Token usage this month
          </Text>
          <Tag color="blue" bordered={false}>
            {meter.plan_name || meter.plan}
          </Tag>
          {trialDays != null && (
            <Tag
              color={trialDays < 0 ? 'error' : trialDays <= 3 ? 'orange' : 'cyan'}
              bordered={false}
            >
              {trialLabel(trialDays)}
            </Tag>
          )}
          {level === 'hard' && (
            <Tag color="error" bordered={false}>
              Hard limit
            </Tag>
          )}
          {level === 'warn' && (
            <Tag color="orange" bordered={false}>
              Running low
            </Tag>
          )}
        </Space>
      </div>

      <Progress
        percent={included ? pct : 0}
        status={progressStatus}
        strokeColor={stroke}
        trailColor="var(--aba-border, #e2e8f0)"
        strokeWidth={10}
        format={(p) => `${p}%`}
        className="aba-meter-full-progress"
      />

      <Row gutter={[12, 12]} justify="center" className="aba-meter-full-stats">
        <Col xs={12} sm={6}>
          <div className="aba-meter-stat">
            <Statistic
              title="Used"
              value={fmt(used)}
              valueStyle={{ fontSize: 18, fontWeight: 650 }}
            />
          </div>
        </Col>
        <Col xs={12} sm={6}>
          <div className="aba-meter-stat">
            <Statistic
              title="Included"
              value={fmt(included)}
              valueStyle={{ fontSize: 18, fontWeight: 650 }}
            />
          </div>
        </Col>
        <Col xs={12} sm={6}>
          <div className="aba-meter-stat">
            <Statistic
              title="Left"
              value={fmt(remaining)}
              valueStyle={{ fontSize: 18, fontWeight: 650 }}
            />
          </div>
        </Col>
        <Col xs={12} sm={6}>
          <div className="aba-meter-stat">
            <Statistic
              title="Credits"
              prefix="$"
              value={credits.toFixed(2)}
              valueStyle={{ fontSize: 18, fontWeight: 650 }}
            />
          </div>
        </Col>
      </Row>
    </div>
  )
}
