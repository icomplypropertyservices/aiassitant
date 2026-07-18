import React, { useEffect, useRef, useState } from 'react'
import { Layout, Menu, Avatar, Dropdown, Typography, Alert, Tag } from 'antd'
import {
  DashboardOutlined, MessageOutlined, RobotOutlined, AppstoreOutlined,
  BarChartOutlined, CreditCardOutlined, SettingOutlined, CrownOutlined,
  LogoutOutlined, ApartmentOutlined, CheckSquareOutlined, ClusterOutlined,
  BookOutlined, UserOutlined, ThunderboltOutlined, ShopOutlined,
  SafetyCertificateOutlined, TeamOutlined, GlobalOutlined,
} from '@ant-design/icons'
import { Outlet, useNavigate, useLocation, Navigate, Link } from 'react-router-dom'
import { api, getUser, getToken, clearAuth, setAuth, connectAuthedWs } from '../api'
import { hapticLight, hapticSelect } from '../native'
import TokenMeter from './TokenMeter'
import LiveOpsBanner from './LiveOpsBanner'
import TopUpModal from './TopUpModal'

const { Header, Sider, Content } = Layout

const SNOOZE_KEY = 'topup_modal_snooze_until'

function isSnoozed() {
  try {
    const t = Number(localStorage.getItem(SNOOZE_KEY) || 0)
    return t > Date.now()
  } catch {
    return false
  }
}

function snooze(minutes = 45) {
  try {
    localStorage.setItem(SNOOZE_KEY, String(Date.now() + minutes * 60 * 1000))
  } catch { /* ignore */ }
}

export default function AppLayout() {
  const nav = useNavigate()
  const loc = useLocation()
  const [user, setUser] = useState(getUser())
  const [collapsed, setCollapsed] = useState(false)
  const [meter, setMeter] = useState(null)
  const [topupOpen, setTopupOpen] = useState(false)
  const wsRef = useRef(null)
  const autoTrigRef = useRef(false)

  const maybeOpenTopup = (m) => {
    const u = getUser()
    if (!m || u?.role === 'admin') return
    const pathNow = window.location.pathname || ''
    if (pathNow.includes('/billing') || pathNow.includes('/subscribe')) return
    if (isSnoozed() && !m.hard_block) return
    if (m.needs_topup || m.hard_block || m.hard_block_soon || (m.warn && (m.credits || 0) < 10)) {
      setTopupOpen(true)
    }
    // Auto top-up: prepare checkout once per session when enabled (user still sees pitch)
    if (
      m.auto_topup?.should_trigger
      && m.auto_topup?.enabled
      && !autoTrigRef.current
    ) {
      autoTrigRef.current = true
      api('/billing/auto-topup/trigger', { method: 'POST', body: {} })
        .then((r) => {
          if (r.checkout_url) {
            setTopupOpen(true)
            setMeter((prev) => (prev ? { ...prev, auto_checkout_url: r.checkout_url } : prev))
          } else if (r.dev_mode) {
            api('/billing/meter').then(setMeter).catch(() => {})
          }
        })
        .catch(() => {})
    }
  }

  useEffect(() => {
    api('/auth/me').then(me => {
      setUser(me)
      setAuth(getToken(), me)
      if (me.meter) {
        setMeter(me.meter)
        maybeOpenTopup(me.meter)
      }
      if (me.needs_subscription) nav('/subscribe', { replace: true })
    }).catch(() => {})

    api('/billing/meter').then((m) => {
      setMeter(m)
      maybeOpenTopup(m)
    }).catch(() => {})

    const applyUsage = (m) => {
      if (!m) return
      setMeter((prev) => {
        if (!prev && m.meter) {
          setTimeout(() => maybeOpenTopup(m.meter), 0)
          return m.meter
        }
        if (!prev) return prev
        const used = m.tokens_used_period != null
          ? m.tokens_used_period
          : (prev.tokens_used_period || 0) + (m.tokens || 0)
        const included = prev.tokens_included || 0
        const usage_percent = included ? Math.min(100, (used / included) * 100) : 0
        const next = {
          ...prev,
          ...(m.meter || {}),
          tokens_used_period: used,
          tokens_remaining_included: Math.max(0, included - used),
          credits: m.credits != null ? m.credits : (m.meter?.credits ?? prev.credits),
          usage_percent: m.meter?.usage_percent ?? usage_percent,
          warn: m.meter?.warn != null ? m.meter.warn : (usage_percent >= 80 && usage_percent < 100),
          hard_block: m.meter?.hard_block != null ? m.meter.hard_block : usage_percent >= 100,
          hard_block_soon: m.meter?.hard_block_soon != null ? m.meter.hard_block_soon : usage_percent >= 95,
          needs_topup: m.meter?.needs_topup ?? prev.needs_topup,
          urgency: m.meter?.urgency ?? prev.urgency,
          headline: m.meter?.headline ?? prev.headline,
          sales_message: m.meter?.sales_message ?? prev.sales_message,
          cta: m.meter?.cta ?? prev.cta,
          auto_topup: m.meter?.auto_topup || prev.auto_topup,
        }
        setTimeout(() => maybeOpenTopup(next), 0)
        return next
      })
      // Prefer full meter refresh after billable events
      if (m.tokens || m.meter) {
        api('/billing/meter').then((full) => {
          setMeter(full)
          maybeOpenTopup(full)
        }).catch(() => {})
      }
    }

    const onAbaUsage = (ev) => applyUsage(ev.detail || {})
    window.addEventListener('aba-usage', onAbaUsage)

    // Billing meter WS is optional; Vercel serverless returns 403 on WS upgrade.
    // Token updates still arrive via aba-usage events after chat REST calls.
    let ws
    if (!import.meta.env.PROD) {
      try {
        ws = connectAuthedWs('/billing/ws/tokens')
        ws.onmessage = e => {
          try {
            const m = JSON.parse(e.data)
            if (m.type === 'auth_ok') return
            if (m.event === 'usage') applyUsage(m)
          } catch { /* ignore bad frames */ }
        }
        wsRef.current = ws
      } catch { /* ignore */ }
    }
    return () => {
      window.removeEventListener('aba-usage', onAbaUsage)
      try { ws?.close() } catch { /* ignore */ }
    }
  }, [])

  if (user?.needs_subscription) {
    return <Navigate to="/subscribe" replace />
  }

  const path = (loc.pathname.startsWith('/agents/') || loc.pathname.startsWith('/army/') || loc.pathname.startsWith('/console/'))
    ? '/console'
    : loc.pathname === '/agents' || loc.pathname === '/army' || loc.pathname === '/console'
      ? '/console'
      : loc.pathname.startsWith('/business')
        ? '/business'
        : loc.pathname.startsWith('/companies/')
          ? '/workspace'
          : loc.pathname === '/users'
            ? '/humans'
            : loc.pathname
  const showTokenWarn = meter && (meter.warn || (meter.usage_percent != null && meter.usage_percent >= 80 && meter.usage_percent < 100))
  const showTokenHard = meter && (meter.hard_block || (meter.usage_percent != null && meter.usage_percent >= 100))

  const items = [
    { key: '/', icon: <DashboardOutlined />, label: 'Dashboard' },
    { key: '/workspace', icon: <ApartmentOutlined />, label: 'Workspace' },
    { key: '/business', icon: <ShopOutlined />, label: 'Business' },
    { key: '/tasks', icon: <CheckSquareOutlined />, label: 'Tasks board' },
    { key: '/console', icon: <RobotOutlined />, label: 'Console' },
    { key: '/hierarchy', icon: <ClusterOutlined />, label: 'Hierarchy' },
    { key: '/humans', icon: <TeamOutlined />, label: 'Team' },
    { key: '/permissions', icon: <SafetyCertificateOutlined />, label: 'Permissions' },
    { key: '/ops', icon: <ThunderboltOutlined />, label: 'Live ops' },
    { key: '/chat', icon: <MessageOutlined />, label: 'AI Chat' },
    { key: '/templates', icon: <AppstoreOutlined />, label: 'Templates' },
    { key: '/training', icon: <BookOutlined />, label: 'Training' },
    { key: '/analytics', icon: <BarChartOutlined />, label: 'Analytics' },
    { key: '/billing', icon: <CreditCardOutlined />, label: 'Billing' },
    { key: '__bay__', icon: <GlobalOutlined />, label: 'AgentBay' },
    { key: '/profile', icon: <UserOutlined />, label: 'Profile' },
    { key: '/settings', icon: <SettingOutlined />, label: 'Settings' },
    ...(user?.role === 'admin' ? [{ key: '/admin', icon: <CrownOutlined />, label: 'Staff Admin' }] : []),
  ]

  const pageLabel = items.find(i => i.key === path)?.label
    || ((loc.pathname.includes('/agents/') || loc.pathname.includes('/army/') || loc.pathname.includes('/console/'))
      && loc.pathname.endsWith('/manage') ? 'Agent setup' : '')
    || ((loc.pathname.includes('/agents/') || loc.pathname.includes('/army/') || loc.pathname.includes('/console/')) ? 'Agent chat' : '')
    || (loc.pathname.startsWith('/business/customers/') ? 'Customer' : '')
    || (loc.pathname.startsWith('/companies/') ? 'Company profile' : '')

  // Full-screen ChatGPT-style agent conversation (one agent per page)
  const isAgentChat =
    /^\/agents\/[^/]+$/.test(loc.pathname)
    || /^\/agents\/[^/]+\/chat$/.test(loc.pathname)
    || /^\/army\/[^/]+$/.test(loc.pathname)
    || /^\/army\/[^/]+\/chat$/.test(loc.pathname)
    || /^\/console\/[^/]+$/.test(loc.pathname)
    || /^\/console\/[^/]+\/chat$/.test(loc.pathname)

  if (isAgentChat) {
    return (
      <div className="aba-agent-chat-host">
        <Outlet />
      </div>
    )
  }

  return (
    <Layout style={{ minHeight: '100vh' }} className="aba-shell">
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="dark"
        width={232}
        breakpoint="lg"
        className="aba-sider"
      >
        <div className="aba-brand">
          <div className="aba-brand-mark"><RobotOutlined /></div>
          {!collapsed && (
            <div className="aba-brand-text">
              <strong>AI Business Agent</strong>
              <span>Console · Agents · Chat</span>
            </div>
          )}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[path]}
          items={items}
          onClick={e => {
            if (e.key === '__bay__') {
              // Same-origin marketplace; session token is shared via localStorage
              window.location.href = '/bay'
              return
            }
            nav(e.key)
          }}
          style={{ borderInlineEnd: 'none', paddingBottom: 48 }}
        />
      </Sider>
      <Layout>
        <Header className="aba-header">
          <div>
            <div className="aba-header-title">{pageLabel}</div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <TokenMeter
              meter={
                meter
                  ? {
                      ...meter,
                      plan: meter.plan || user?.plan,
                      subscription_expires_at:
                        meter.subscription_expires_at || user?.subscription_expires_at,
                    }
                  : meter
              }
            />
            {user?.plan && user.plan !== 'none' && (
              <Tag color="blue" style={{ margin: 0, textTransform: 'capitalize' }}>
                {user.plan.replace(/_/g, ' ')}
              </Tag>
            )}
            <Dropdown
              menu={{
                items: [
                  {
                    key: 'profile',
                    icon: <UserOutlined />,
                    label: 'Your profile',
                    onClick: () => nav('/profile'),
                  },
                  {
                    key: 'permissions',
                    icon: <SafetyCertificateOutlined />,
                    label: 'Permissions',
                    onClick: () => nav('/permissions'),
                  },
                  {
                    key: 'team',
                    icon: <TeamOutlined />,
                    label: 'Users / Team',
                    onClick: () => nav('/humans'),
                  },
                  {
                    key: 'billing',
                    icon: <CreditCardOutlined />,
                    label: 'Billing',
                    onClick: () => nav('/billing'),
                  },
                  {
                    key: 'settings',
                    icon: <SettingOutlined />,
                    label: 'Settings',
                    onClick: () => nav('/settings'),
                  },
                  { type: 'divider' },
                  {
                    key: 'logout',
                    icon: <LogoutOutlined />,
                    label: 'Sign out',
                    onClick: () => { clearAuth(); nav('/login') },
                  },
                ],
              }}
            >
              <div className="aba-user-chip">
                <Avatar
                  size={28}
                  style={{
                    background: 'linear-gradient(135deg,#3b82f6,#1d4ed8)',
                    fontSize: 13,
                    fontWeight: 600,
                  }}
                >
                  {(user?.name || user?.email || '?')[0].toUpperCase()}
                </Avatar>
                <span className="name">{user?.name || user?.email}</span>
              </div>
            </Dropdown>
          </div>
        </Header>
        <LiveOpsBanner />
        {(showTokenHard || showTokenWarn) && (
          <Alert
            type={showTokenHard ? 'error' : 'warning'}
            showIcon
            banner
            message={
              showTokenHard
                ? <>Included tokens exhausted — overage uses credits. <Link to="/billing">Top up / billing</Link></>
                : <>Included tokens running low — <Link to="/billing">top up</Link></>
            }
            style={{ borderRadius: 0 }}
          />
        )}
        {user?.plan === 'trial' && !showTokenHard && (
          <Alert
            type={(() => {
              const exp = user?.subscription_expires_at
              if (!exp) return 'info'
              const days = Math.ceil((new Date(exp).getTime() - Date.now()) / 86400000)
              return days <= 3 ? 'warning' : 'info'
            })()}
            showIcon
            banner
            message={
              <>
                Free trial · 50k tokens
                {user?.subscription_expires_at && (() => {
                  const d = new Date(user.subscription_expires_at)
                  if (Number.isNaN(d.getTime())) return null
                  const days = Math.ceil((d.getTime() - Date.now()) / 86400000)
                  if (days < 0) return <> · expired {d.toLocaleDateString()}</>
                  if (days === 0) return <> · ends today</>
                  return <> · {days} day{days === 1 ? '' : 's'} left ({d.toLocaleDateString()})</>
                })()}
                {' '}— unlock 2M on Starter.{' '}
                <Link to="/billing">Upgrade →</Link>
              </>
            }
            style={{ borderRadius: 0 }}
          />
        )}
        {user?.plan === 'starter' && !showTokenHard && !showTokenWarn && (
          <Alert
            type="info"
            showIcon
            banner
            message={
              <>
                Starter · Pro unlocks 10M tokens &amp; 20 agents.{' '}
                <Link to="/billing">See upgrades →</Link>
              </>
            }
            style={{ borderRadius: 0 }}
          />
        )}
        <Content className="aba-content">
          <Outlet />
        </Content>
        <TopUpModal
          open={topupOpen}
          meter={meter}
          onClose={() => {
            if (!meter?.hard_block) snooze(45)
            else snooze(5)
            setTopupOpen(false)
            if (meter?.hard_block) nav('/billing')
          }}
          onTopped={() => {
            api('/billing/meter').then(setMeter).catch(() => {})
            setTopupOpen(false)
          }}
        />
        {/* Mobile bottom nav — primary destinations */}
        <nav className="aba-mobile-nav" aria-label="Main">
          {[
            { key: '/', icon: <DashboardOutlined />, label: 'Home' },
            { key: '/agents', icon: <RobotOutlined />, label: 'Agents' },
            { key: '/business', icon: <ShopOutlined />, label: 'Business' },
            { key: '/ops', icon: <ThunderboltOutlined />, label: 'Ops' },
            { key: '/settings', icon: <SettingOutlined />, label: 'More' },
          ].map((item) => {
            const active = path === item.key || (item.key !== '/' && path.startsWith(item.key))
            return (
              <button
                key={item.key}
                type="button"
                className={`aba-mobile-nav-item${active ? ' is-active' : ''}`}
                onClick={() => { hapticSelect(); nav(item.key) }}
              >
                {item.icon}
                <span>{item.label}</span>
              </button>
            )
          })}
        </nav>
      </Layout>
    </Layout>
  )
}
