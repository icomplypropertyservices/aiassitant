import React from 'react'
import { Progress, Space, Typography, Tooltip, Tag, Statistic, Row, Col, Button } from 'antd'
import { ThunderboltOutlined, WalletOutlined, FireOutlined, CloudServerOutlined, CrownOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

const { Text } = Typography

function fmt(n) {
  if (n == null || Number.isNaN(Number(n))) return '0'
  const v = Number(n)
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}k`
  return String(v)
}

function safeCredits(n) {
  const v = Number(n)
  return Number.isFinite(v) ? v : 0
}

/** Prefer server upgrade_cta_path; no plan / trial ended → /subscribe, else /billing. */
export function upgradePathFromMeter(meter, user) {
  if (meter?.primary_cta?.path) return meter.primary_cta.path
  if (meter?.upgrade_cta_path) return meter.upgrade_cta_path
  if (meter?.needs_subscription || meter?.trial_ended || user?.needs_subscription) return '/subscribe'
  const plan = (meter?.plan || user?.plan || '').toLowerCase()
  if (!plan || plan === 'none') return '/subscribe'
  return '/billing'
}

function meterSeverity(meter) {
  if (!meter) {
    return {
      level: 'ok',
      pct: 0,
      tagColor: 'default',
      progressStatus: 'normal',
      stroke: 'var(--aba-border, #e2e8f0)',
    }
  }
  const used = Number(meter.tokens_used_period) || 0
  const included = Number(meter.tokens_included) || 0
  const rawPct = meter.usage_percent != null ? Number(meter.usage_percent) : (included ? (used / included) * 100 : 0)
  const pct = Number.isFinite(rawPct) ? rawPct : 0
  const needsSub = Boolean(meter.needs_subscription || meter.trial_ended)
  const hard = meter.hard_block || pct >= 100 || needsSub
  const warn = !hard && (meter.warn || pct >= 80)
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

/** Compact header meter — clear for customers. Click opens Billing or Subscribe. */
export default function TokenMeter({ meter, compact = true, onClick, user }) {
  const nav = useNavigate()
  const upgradePath = upgradePathFromMeter(meter, user)
  const needsSub = Boolean(meter?.needs_subscription || meter?.trial_ended || user?.needs_subscription)
  const trialEnded = Boolean(meter?.trial_ended || (needsSub && meter?.plan === 'trial'))
  const hasServerUpgradePath = Boolean(meter?.upgrade_cta_path || meter?.primary_cta)
  const lowFuel = Boolean(meter?.hard_block || meter?.needs_topup || meter?.hard_block_soon)
  const goPath = (path) => {
    if (typeof onClick === 'function') {
      onClick({ path })
      return
    }
    nav(path || upgradePath)
  }
  const goUpgrade = (e) => {
    e?.stopPropagation?.()
    e?.preventDefault?.()
    goPath(upgradePath)
  }
  // Clickable when parent provides onClick, or meter flags an upgrade path
  const clickable =
    typeof onClick === 'function'
    || needsSub
    || hasServerUpgradePath
    || lowFuel
    || Boolean(meter?.hard_block || meter?.warn || meter?.hard_block_soon)
  const chipProps = clickable
    ? {
        role: 'button',
        tabIndex: 0,
        onClick: goUpgrade,
        onKeyDown: (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            goUpgrade(e)
          }
        },
        style: { cursor: 'pointer' },
        title: needsSub
          ? (trialEnded ? 'Subscribe — trial ended' : 'Choose a plan')
          : lowFuel
            ? 'Buy credits or upgrade'
            : upgradePath === '/subscribe' ? 'Upgrade plan' : 'Open Billing',
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

  const used = Number(meter.tokens_used_period) || 0
  const included = Number(meter.tokens_included) || 0
  const remaining = Number(
    meter.tokens_remaining_included ?? meter.tokens_remaining ?? Math.max(0, included - used),
  ) || 0
  const { pct, tagColor, progressStatus, level, stroke } = meterSeverity(meter)
  const trialDays = trialDaysLeft(meter)
  const credits = safeCredits(meter.credits)
  // needs_subscription / upgrade_cta_path always show CTA; also warn/hard/trial edge
  const showUpgradeCta =
    needsSub
    || hasServerUpgradePath
    || lowFuel
    || level === 'hard'
    || level === 'warn'
    || (trialDays != null && trialDays <= 3)
  // Prefer server primary_cta label; else clear dual-path labels
  const ctaLabel = meter?.primary_cta?.label
    || (needsSub
      ? (trialEnded ? 'Subscribe' : 'Subscribe')
      : lowFuel
        ? 'Buy credits'
        : (hasServerUpgradePath || upgradePath === '/subscribe')
          ? 'Upgrade'
          : 'Buy credits')
  const secondaryLabel = meter?.secondary_cta?.label
    || (!needsSub && lowFuel ? 'Upgrade' : null)
  const secondaryPath = meter?.secondary_cta?.path
    || meter?.cta_subscribe_path
    || '/subscribe'

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
      {needsSub && (
        <div className="aba-meter-tooltip-alert is-hard">
          {trialEnded
            ? 'Trial ended — subscribe to unlock full tool access'
            : 'No active plan — choose free trial or a paid plan'}
        </div>
      )}
      {!needsSub && level === 'hard' && (
        <div className="aba-meter-tooltip-alert is-hard">
          Pool empty / wallet low — buy credits or upgrade. Premium skills fail closed without credits.
        </div>
      )}
      {!needsSub && level === 'warn' && (
        <div className="aba-meter-tooltip-alert is-warn">Included tokens running low — top up or upgrade</div>
      )}
      {showUpgradeCta && (
        <div className="aba-meter-tooltip-hint">
          {needsSub
            ? (trialEnded
              ? 'Click → Subscribe (Starter / Pro / Business). No free re-grant.'
              : 'Click → Subscribe to start free trial (12 agents) or pick a paid plan.')
            : lowFuel
              ? 'Click → Billing to buy credits, or Subscribe to upgrade plan.'
              : upgradePath === '/subscribe'
                ? 'Click → Upgrade on Subscribe for a larger monthly pool.'
                : 'Click → Billing to buy credits or upgrade.'}
        </div>
      )}
      {!showUpgradeCta && (
        <div className="aba-meter-tooltip-hint">
          Included pool first; overage uses wallet credits. Premium skills never free-run.
        </div>
      )}
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
          aria-label={`Tokens ${fmt(remaining)} left of ${fmt(included)}, wallet $${credits.toFixed(2)}. ${ctaLabel}`}
          {...chipProps}
        >
          <Tag
            icon={<ThunderboltOutlined />}
            color={tagColor}
            bordered={false}
            className="aba-meter-tag"
          >
            {fmt(remaining)} left
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
          {showUpgradeCta && (
            <Tag
              color={needsSub ? 'purple' : 'error'}
              bordered={false}
              className="aba-meter-tag"
              icon={needsSub || upgradePath === '/subscribe' ? <CrownOutlined /> : <FireOutlined />}
            >
              {ctaLabel}
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
            {meter.plan_name || meter.plan || 'No plan'}
          </Tag>
          {trialDays != null && (
            <Tag
              color={trialDays < 0 ? 'error' : trialDays <= 3 ? 'orange' : 'cyan'}
              bordered={false}
            >
              {trialLabel(trialDays)}
            </Tag>
          )}
          {needsSub && (
            <Tag color="purple" bordered={false} icon={<CrownOutlined />}>
              {trialEnded ? 'Trial ended' : 'Choose a plan'}
            </Tag>
          )}
          {!needsSub && level === 'hard' && (
            <Tag color="error" bordered={false}>
              Hard limit
            </Tag>
          )}
          {!needsSub && level === 'warn' && (
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
        format={(p) => `${p ?? 0}%`}
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
      {showUpgradeCta && (
        <div style={{ textAlign: 'center', marginTop: 12 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
            {needsSub
              ? (trialEnded
                ? 'Trial ended — subscribe (Starter / Pro / Business) to restore full tool access. No free re-grant.'
                : 'No active plan — start free trial (50k tokens · 12 agents) or pick a paid plan.')
              : level === 'hard'
                ? 'Pool empty or wallet low — buy credits to keep AI running, or upgrade for a larger pool. Premium skills fail closed without credits.'
                : 'Running low — buy credits or upgrade for a larger monthly pool.'}
          </Text>
          <Space wrap>
            <Button
              type="primary"
              size="small"
              icon={needsSub || upgradePath === '/subscribe' ? <CrownOutlined /> : <FireOutlined />}
              onClick={goUpgrade}
            >
              {ctaLabel}
            </Button>
            {secondaryLabel && !needsSub && (
              <Button
                size="small"
                icon={<CrownOutlined />}
                onClick={(e) => {
                  e?.stopPropagation?.()
                  goPath(secondaryPath)
                }}
              >
                {secondaryLabel}
              </Button>
            )}
            {needsSub && !trialEnded && (
              <Button size="small" onClick={(e) => { e?.stopPropagation?.(); goPath('/billing') }}>
                View billing
              </Button>
            )}
          </Space>
        </div>
      )}
    </div>
  )
}
