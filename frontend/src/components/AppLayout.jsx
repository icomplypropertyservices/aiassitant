import React, { useEffect, useRef, useState } from 'react'
import { Layout, Menu, Avatar, Dropdown, Typography, Alert, Tag } from 'antd'
import {
  DashboardOutlined, MessageOutlined, RobotOutlined, AppstoreOutlined,
  BarChartOutlined, CreditCardOutlined, SettingOutlined, CrownOutlined,
  LogoutOutlined, ApartmentOutlined, CheckSquareOutlined, ClusterOutlined,
  BookOutlined,
} from '@ant-design/icons'
import { Outlet, useNavigate, useLocation, Navigate, Link } from 'react-router-dom'
import { api, getUser, getToken, clearAuth, setAuth, getWsBase } from '../api'
import TokenMeter from './TokenMeter'

const { Header, Sider, Content } = Layout

export default function AppLayout() {
  const nav = useNavigate()
  const loc = useLocation()
  const [user, setUser] = useState(getUser())
  const [collapsed, setCollapsed] = useState(false)
  const [meter, setMeter] = useState(null)
  const wsRef = useRef(null)

  useEffect(() => {
    api('/auth/me').then(me => {
      setUser(me)
      setAuth(getToken(), me)
      if (me.meter) setMeter(me.meter)
      if (me.needs_subscription) nav('/subscribe', { replace: true })
    }).catch(() => {})

    api('/billing/meter').then(setMeter).catch(() => {})
    let ws
    try {
      ws = new WebSocket(`${getWsBase()}/billing/ws/tokens?token=${getToken()}`)
      ws.onmessage = e => {
        try {
          const m = JSON.parse(e.data)
          if (m.event === 'usage') {
            setMeter(prev => {
              if (!prev) return prev
              const used = (prev.tokens_used_period || 0) + (m.tokens || 0)
              const included = prev.tokens_included || 0
              const usage_percent = included
                ? Math.min(100, ((m.tokens_used_period ?? used) / included) * 100)
                : 0
              return {
                ...prev,
                tokens_used_period: m.tokens_used_period ?? used,
                tokens_remaining_included: Math.max(0, included - (m.tokens_used_period ?? used)),
                credits: m.credits != null ? m.credits : prev.credits,
                usage_percent,
                warn: m.warn != null ? m.warn : (usage_percent >= 80 && usage_percent < 100),
                hard_block: m.hard_block != null ? m.hard_block : usage_percent >= 100,
              }
            })
          }
        } catch { /* ignore bad frames */ }
      }
      wsRef.current = ws
    } catch { /* WS optional on serverless */ }
    return () => {
      try { ws?.close() } catch { /* ignore */ }
    }
  }, [])

  if (user?.needs_subscription) {
    return <Navigate to="/subscribe" replace />
  }

  const path = loc.pathname.startsWith('/agents/') ? '/agents' : loc.pathname
  const showTokenWarn = meter && (meter.warn || (meter.usage_percent != null && meter.usage_percent >= 80 && meter.usage_percent < 100))
  const showTokenHard = meter && (meter.hard_block || (meter.usage_percent != null && meter.usage_percent >= 100))

  const items = [
    { key: '/', icon: <DashboardOutlined />, label: 'Dashboard' },
    { key: '/workspace', icon: <ApartmentOutlined />, label: 'Workspace' },
    { key: '/tasks', icon: <CheckSquareOutlined />, label: 'Tasks board' },
    { key: '/agents', icon: <RobotOutlined />, label: 'Agents' },
    { key: '/hierarchy', icon: <ClusterOutlined />, label: 'Hierarchy' },
    { key: '/chat', icon: <MessageOutlined />, label: 'AI Chat' },
    { key: '/templates', icon: <AppstoreOutlined />, label: 'Templates' },
    { key: '/training', icon: <BookOutlined />, label: 'Training' },
    { key: '/analytics', icon: <BarChartOutlined />, label: 'Analytics' },
    { key: '/billing', icon: <CreditCardOutlined />, label: 'Billing' },
    { key: '/settings', icon: <SettingOutlined />, label: 'Settings' },
    ...(user?.role === 'admin' ? [{ key: '/admin', icon: <CrownOutlined />, label: 'Staff Admin' }] : []),
  ]

  const pageLabel = items.find(i => i.key === path)?.label
    || (loc.pathname.startsWith('/agents/') ? 'Agent workspace' : '')

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="dark"
        width={232}
        breakpoint="lg"
      >
        <div className="aba-brand">
          <div className="aba-brand-mark"><RobotOutlined /></div>
          {!collapsed && (
            <div className="aba-brand-text">
              <strong>AI Business Assistant</strong>
              <span>Companies · Agents · Chat</span>
            </div>
          )}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[path]}
          items={items}
          onClick={e => nav(e.key)}
          style={{ borderInlineEnd: 'none', paddingBottom: 48 }}
        />
      </Sider>
      <Layout>
        <Header className="aba-header">
          <div>
            <div className="aba-header-title">{pageLabel}</div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <TokenMeter meter={meter} />
            {user?.plan && user.plan !== 'none' && (
              <Tag color="blue" style={{ margin: 0, textTransform: 'capitalize' }}>
                {user.plan.replace(/_/g, ' ')}
              </Tag>
            )}
            <Dropdown
              menu={{
                items: [
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
        <Content className="aba-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
