import React, { useEffect, useRef, useState } from 'react'
import { Layout, Menu, Avatar, Dropdown, Space, Typography, Alert } from 'antd'
import {
  DashboardOutlined, MessageOutlined, RobotOutlined, AppstoreOutlined,
  BarChartOutlined, CreditCardOutlined, SettingOutlined, CrownOutlined,
  LogoutOutlined, ApartmentOutlined, CheckSquareOutlined, ClusterOutlined,
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
    const ws = new WebSocket(`${getWsBase()}/billing/ws/tokens?token=${getToken()}`)
    ws.onmessage = e => {
      const m = JSON.parse(e.data)
      if (m.event === 'usage') {
        setMeter(prev => {
          if (!prev) return prev
          const used = (prev.tokens_used_period || 0) + (m.tokens || 0)
          const included = prev.tokens_included || 0
          const usage_percent = included ? Math.min(100, ((m.tokens_used_period ?? used) / included) * 100) : 0
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
    }
    wsRef.current = ws
    return () => ws.close()
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
    { key: '/analytics', icon: <BarChartOutlined />, label: 'Analytics' },
    { key: '/billing', icon: <CreditCardOutlined />, label: 'Billing' },
    { key: '/settings', icon: <SettingOutlined />, label: 'Settings' },
    ...(user?.role === 'admin' ? [{ key: '/admin', icon: <CrownOutlined />, label: 'Staff Admin' }] : []),
  ]

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} theme="dark">
        <div style={{ color: '#fff', padding: 16, fontWeight: 700, fontSize: 16, whiteSpace: 'nowrap', overflow: 'hidden' }}>
          <RobotOutlined /> {!collapsed && ' AI Business Assistant'}
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={[path]} items={items} onClick={e => nav(e.key)} />
      </Sider>
      <Layout>
        <Header style={{
          background: '#fff', padding: '0 24px',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          borderBottom: '1px solid #f0f0f0', gap: 16, flexWrap: 'wrap', height: 'auto', minHeight: 64,
        }}>
          <Typography.Text strong>
            {items.find(i => i.key === path)?.label || (loc.pathname.startsWith('/agents/') ? 'Agent workspace' : '')}
          </Typography.Text>
          <Space size="middle" wrap>
            <TokenMeter meter={meter} />
            <Dropdown menu={{
              items: [{
                key: 'logout',
                icon: <LogoutOutlined />,
                label: 'Sign out',
                onClick: () => { clearAuth(); nav('/login') },
              }],
            }}>
              <Space style={{ cursor: 'pointer' }}>
                <Avatar style={{ background: '#1668dc' }}>
                  {(user?.name || user?.email || '?')[0].toUpperCase()}
                </Avatar>
                <span>{user?.name || user?.email}</span>
              </Space>
            </Dropdown>
          </Space>
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
        <Content style={{ padding: 24, background: '#f5f5f5' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
