import React from 'react'
import { Button, Card, Tag, Typography } from 'antd'
import { CheckOutlined, WalletOutlined, ArrowUpOutlined, CrownOutlined, ThunderboltOutlined } from '@ant-design/icons'

function formatPrice(n) {
  if (n == null || Number.isNaN(Number(n))) return '0'
  const num = Number(n)
  return num % 1 ? num.toFixed(2) : String(num)
}

function normalizeEntries(plans) {
  const list = Array.isArray(plans)
    ? [...plans]
    : Object.entries(plans || {})
  // Trial first, then sort order — keeps free trial left-most and highlighted
  return list.sort((a, b) => {
    const aTrial = String(a[0] || '').toLowerCase() === 'trial' ? 0 : 1
    const bTrial = String(b[0] || '').toLowerCase() === 'trial' ? 0 : 1
    if (aTrial !== bTrial) return aTrial - bTrial
    return (a[1]?.sort ?? 50) - (b[1]?.sort ?? 50)
  })
}

/** Free trial plan key — always elevated on plan grids. */
function isTrialKey(key) {
  return String(key || '').toLowerCase() === 'trial'
}

/**
 * Centered, polished plan grid used on Login, Subscribe, and Billing.
 * Each tier is an Ant Design Card inside a centered max-width container grid.
 * Free trial is always highlighted as the one-click start path.
 *
 * props:
 *  plans: [ [key, planObj], ... ] or { key: plan }
 *  preorderOn?: boolean
 *  billingInterval?: 'month' | 'year'  — annual = 10× monthly (2 months free)
 *  currentPlan?: string
 *  busy?: string | boolean  (plan key when loading, or true for any)
 *  stripeSandbox?: boolean
 *  showCrypto?: boolean
 *  compact?: boolean  (login sidebar list style)
 *  onChoose: (planKey, interval?) => void
 *  onCrypto?: (planKey, interval?) => void
 *  ctaFor?: (key, plan, interval) => { label, disabled?, type? }
 */
export default function PlanCards({
  plans,
  preorderOn = false,
  billingInterval = 'month',
  currentPlan,
  busy,
  stripeSandbox = false,
  showCrypto = true,
  compact = false,
  onChoose,
  onCrypto,
  ctaFor,
}) {
  const isAnnual = billingInterval === 'year' || billingInterval === 'annual'
  const entries = normalizeEntries(plans)

  if (!entries.length) {
    return (
      <div className="aba-plans-empty">
        <Card
          className="aba-soft-card"
          style={{ maxWidth: 420, margin: '0 auto', textAlign: 'center' }}
        >
          <Typography.Text type="secondary">Loading plans…</Typography.Text>
        </Card>
      </div>
    )
  }

  if (compact) {
    return (
      <div className="aba-plans-wrap aba-plans-wrap--compact">
        <div className="aba-plans-compact">
          {entries.map(([key, p]) => {
            const monthly = Number(p.price) || 0
            const annual = Number(p.price_annual != null ? p.price_annual : (monthly > 0 ? monthly * 10 : 0))
            const checkout = isAnnual && annual > 0
              ? Number(p.price_annual_checkout != null ? p.price_annual_checkout : annual)
              : (preorderOn && p.price_checkout != null ? p.price_checkout : monthly)
            const discounted = isAnnual
              ? monthly > 0 && annual < monthly * 12
              : (preorderOn && monthly > 0 && p.price_checkout != null && p.price_checkout < monthly)
            const isTrial = isTrialKey(key)
            const isFree = !(p.price > 0)
            const isHighlight = Boolean(p.highlight) || isTrial
            return (
              <Card
                key={key}
                size="small"
                hoverable
                className={[
                  'aba-plan-compact',
                  isHighlight ? 'is-highlight' : '',
                  isTrial || isFree ? 'is-free' : '',
                  currentPlan === key ? 'is-current' : '',
                ].filter(Boolean).join(' ')}
                styles={{ body: { padding: '14px 14px 12px' } }}
              >
                <div className="aba-plan-compact-top">
                  <div className="aba-plan-compact-name">
                    <Typography.Text strong>{p.name}</Typography.Text>
                    {isTrial && <Tag color="cyan">Free trial</Tag>}
                    {!isTrial && p.highlight && <Tag color="blue">Popular</Tag>}
                    {isAnnual && !isFree && <Tag color="gold">Annual</Tag>}
                    {preorderOn && p.price > 0 && (
                      <Tag color="gold">{p.preorder_discount_percent || 10}% off</Tag>
                    )}
                  </div>
                  <div className="aba-plan-compact-price">
                    {p.price > 0 ? (
                      <>
                        {discounted && !isAnnual && <span className="aba-price-was">${formatPrice(p.price)}</span>}
                        <span className="aba-price-now">${formatPrice(checkout)}</span>
                        <span className="aba-price-unit">{isAnnual ? '/yr' : '/mo'}</span>
                      </>
                    ) : (
                      <span className="aba-price-now free">Free</span>
                    )}
                  </div>
                </div>
                <p className="aba-plan-compact-blurb">{p.blurb}</p>
                <div className="aba-plan-compact-meta">
                  {(p.tokens_included || 0).toLocaleString()} tokens/mo
                  {' · '}{p.companies || 0} co
                  {' · '}{p.agents || 0} agents
                </div>
              </Card>
            )
          })}
        </div>
      </div>
    )
  }

  const colCount = Math.max(1, Math.min(entries.length, 4))
  // Always center the tier grid inside the shell; pin column width so 2–3 cards don't stretch edge-to-edge
  const gridClass = [
    'aba-plans-grid',
    'is-centered-cols',
    `cols-${colCount}`,
  ].filter(Boolean).join(' ')

  return (
    <div className="aba-plans-wrap" role="list" aria-label="Subscription plans">
      <div
        className={gridClass}
        style={{
          gridTemplateColumns: `repeat(${colCount}, minmax(0, ${colCount >= 4 ? 250 : 260}px))`,
        }}
      >
        {entries.map(([key, p]) => {
          const isCurrent = currentPlan === key
          const isBusy = busy === true || busy === key
          const isFree = !(p.price > 0)
          const isTrial = isTrialKey(key)
          const isHighlight = Boolean(p.highlight) || isTrial
          const monthly = Number(p.price) || 0
          const annual = Number(p.price_annual != null ? p.price_annual : (monthly > 0 ? monthly * 10 : 0))
          const checkout = isAnnual && annual > 0
            ? Number(p.price_annual_checkout != null ? p.price_annual_checkout : annual)
            : (preorderOn && p.price_checkout != null ? p.price_checkout : monthly)
          const discounted = isAnnual
            ? monthly > 0 && annual < monthly * 12
            : (preorderOn && monthly > 0 && p.price_checkout != null && p.price_checkout < monthly)
          const interval = isAnnual ? 'year' : 'month'
          const unit = isAnnual ? '/yr' : '/mo'
          const freeCtaLabel =
            isTrial
              ? (p.cta && String(p.cta).toLowerCase().includes('trial')
                ? p.cta
                : 'Start free trial — no card')
              : (p.cta || 'Start free')
          const cta = ctaFor
            ? ctaFor(key, p, interval)
            : {
                label: isFree
                  ? freeCtaLabel
                  : `${isAnnual ? 'Pay annually' : 'Subscribe'} · $${formatPrice(checkout)}${unit}${stripeSandbox ? ' (test card)' : ''}`,
                disabled: isCurrent,
                // Free trial is the one-click path for new users — keep CTA primary
                type: isFree || isHighlight || isCurrent ? 'primary' : 'default',
              }

          const showRibbon =
            isTrial ||
            isHighlight ||
            (preorderOn && p.price > 0) ||
            (isFree && !isCurrent)

          return (
            <Card
              key={key}
              hoverable
              role="listitem"
              className={[
                'aba-plan-card',
                isHighlight ? 'is-highlight' : '',
                isCurrent ? 'is-current' : '',
                isTrial || isFree ? 'is-free' : '',
              ].filter(Boolean).join(' ')}
              styles={{ body: { padding: 0, height: '100%', display: 'flex', flexDirection: 'column' } }}
            >
              <div className="aba-plan-card-inner">
                {showRibbon && (
                  <div className={`aba-plan-ribbon${isTrial || isFree ? ' is-free-ribbon' : ''}`}>
                    {isTrial || isFree ? (
                      <><ThunderboltOutlined /> {p.badge || 'Try free'} · no card</>
                    ) : p.highlight || isHighlight ? (
                      <><CrownOutlined /> {p.badge || 'Most popular'}</>
                    ) : (
                      <>Pre-order · {p.preorder_discount_percent || 10}% off</>
                    )}
                  </div>
                )}

                <header className="aba-plan-head">
                  <h3 className="aba-plan-name">{p.name}</h3>
                  <div className="aba-plan-price-block">
                    {p.price > 0 ? (
                      <>
                        {discounted && !isAnnual && (
                          <span className="aba-price-was">${formatPrice(p.price)}</span>
                        )}
                        {isAnnual && monthly > 0 && (
                          <span className="aba-price-was">${formatPrice(monthly * 12)}/yr</span>
                        )}
                        <span className="aba-price-now">${formatPrice(checkout)}</span>
                        <span className="aba-price-unit">{unit}</span>
                      </>
                    ) : (
                      <span className="aba-price-now free">$0</span>
                    )}
                  </div>
                  {isAnnual && p.price > 0 && (
                    <Tag color="gold" className="aba-plan-you">
                      {p.annual_label || '2 months free'}
                      {p.price_annual_per_month
                        ? ` · ~$${formatPrice(p.price_annual_per_month)}/mo`
                        : ''}
                    </Tag>
                  )}
                  {isCurrent && <Tag color="success" className="aba-plan-you">Current plan</Tag>}
                  {isTrial && !isCurrent && (
                    <Tag color="cyan" className="aba-plan-you">Recommended to start</Tag>
                  )}
                </header>

                <p className="aba-plan-blurb">{p.blurb}</p>

                <div className="aba-plan-chips">
                  {preorderOn && p.price > 0 && (
                    <Tag color="gold">Early access</Tag>
                  )}
                  {isAnnual && p.price > 0 && (
                    <Tag color="gold">Billed yearly</Tag>
                  )}
                  <Tag color="processing">
                    {(p.tokens_included || 0).toLocaleString()} tokens/mo
                  </Tag>
                </div>

                {p.value_line && (
                  <div className="aba-plan-value">{p.value_line}</div>
                )}

                <ul className="aba-plan-features">
                  {(p.features || []).slice(0, 6).map((f) => (
                    <li key={f}>
                      <CheckOutlined className="aba-plan-check" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>

                {(p.teasers || []).slice(0, 1).map((t) => (
                  <div key={t} className="aba-plan-teaser">{t}</div>
                ))}

                <div className="aba-plan-actions">
                  <Button
                    type={cta.type || (isHighlight ? 'primary' : 'default')}
                    block
                    size="large"
                    disabled={cta.disabled}
                    loading={isBusy}
                    icon={p.price > 0 && !isCurrent ? <ArrowUpOutlined /> : null}
                    onClick={() => onChoose?.(key, interval)}
                    className="aba-plan-cta"
                  >
                    {cta.label}
                  </Button>
                  {showCrypto && p.price > 0 && !isCurrent && onCrypto && (
                    <Button
                      block
                      size="large"
                      icon={<WalletOutlined />}
                      onClick={() => onCrypto(key, interval)}
                      className="aba-plan-crypto"
                    >
                      Pay with crypto
                    </Button>
                  )}
                </div>

                {p.upgrade_teaser && p.next_plan && !isCurrent && (
                  <p className="aba-plan-upgrade-hint">{p.upgrade_teaser}</p>
                )}
              </div>
            </Card>
          )
        })}
      </div>
    </div>
  )
}

export function PlansSectionHeader({ title, subtitle, centered = true }) {
  return (
    <div className={`aba-plans-section-head${centered ? ' is-centered' : ''}`}>
      <Typography.Title level={4} style={{ margin: 0 }}>
        {title}
      </Typography.Title>
      {subtitle && (
        <Typography.Paragraph type="secondary" style={{ margin: '6px 0 0', maxWidth: 560 }}>
          {subtitle}
        </Typography.Paragraph>
      )}
    </div>
  )
}
