import React, { useEffect, useMemo, useState } from 'react'
import { Layout, Alert, Drawer, Typography } from 'antd'
import { Link, Outlet, useNavigate, useLocation, Navigate } from 'react-router-dom'
import { clearAuth, api } from '../../api'
import { hapticSelect } from '../../native'
import { useBreakpoint } from '../../hooks/useBreakpoint'
import {
  buildMenuItems,
  activeNavKey,
  pageTitle,
  isAgentChatPath,
} from '../../navConfig'
import LiveOpsBanner from '../LiveOpsBanner'
import TopUpModal from '../TopUpModal'
import SystemNav from '../SystemNav'
import useShellSession, { snoozeTopup } from './useShellSession'
import AppHeader from './AppHeader'
import BottomNav from './BottomNav'
import NavDrawer from './NavDrawer'
import DesktopSider from './DesktopSider'

const { Content } = Layout

/**
 * AppShell v2 — mobile-first application chrome.
 *
 * Phone / tablet (<1024):
 *   sticky header · content · bottom tabs · bottom sheet menu
 * Desktop (≥1024):
 *   permanent sider · header · content (no bottom nav)
 *
 * Sider is not mounted on phone (not merely CSS-hidden).
 */
export default function AppShell() {
  const nav = useNavigate()
  const loc = useLocation()
  const bp = useBreakpoint()
  const {
    user,
    meter,
    setMeter,
    topupOpen,
    setTopupOpen,
  } = useShellSession()

  const [collapsed, setCollapsed] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [exploreOpen, setExploreOpen] = useState(false)

  useEffect(() => {
    setMenuOpen(false)
    setExploreOpen(false)
  }, [loc.pathname])

  const menuItems = useMemo(
    () => buildMenuItems({ isAdmin: user?.role === 'admin' }),
    [user?.role],
  )

  const path = activeNavKey(loc.pathname)
  const title = pageTitle(loc.pathname, menuItems)

  const goNav = (key) => {
    hapticSelect()
    setMenuOpen(false)
    setExploreOpen(false)
    if (key === '__bay__') {
      window.location.href = '/bay'
      return
    }
    if (key === '__explore__') {
      setExploreOpen(true)
      return
    }
    nav(key)
  }

  const logout = () => {
    clearAuth()
    setMenuOpen(false)
    nav('/login')
  }

  if (user?.needs_subscription) {
    return <Navigate to="/subscribe" replace />
  }

  // Full-screen agent conversation — no chrome
  if (isAgentChatPath(loc.pathname)) {
    return (
      <div className="aba-agent-chat-host aba-v2-chat-host">
        <Outlet />
      </div>
    )
  }

  const showTokenWarn =
    meter && (meter.warn || (meter.usage_percent != null && meter.usage_percent >= 80 && meter.usage_percent < 100))
  const showTokenHard =
    meter && (meter.hard_block || (meter.usage_percent != null && meter.usage_percent >= 100))

  return (
    <Layout
      className={`aba-shell aba-v2-shell${bp.showBottomNav ? ' is-mobile-shell' : ' is-desktop-shell'}`}
      style={{ minHeight: '100dvh' }}
    >
      {bp.showSider && (
        <DesktopSider
          collapsed={collapsed}
          onCollapse={setCollapsed}
          activeKey={path}
          items={menuItems}
          onNavigate={goNav}
        />
      )}

      <Layout className="aba-main-layout aba-v2-main">
        <AppHeader
          title={title}
          user={user}
          meter={meter}
          showSider={bp.showSider}
          onOpenMenu={() => setMenuOpen(true)}
          onOpenExplore={() => setExploreOpen(true)}
          onLogout={logout}
        />

        <LiveOpsBanner />

        {(showTokenHard || showTokenWarn) && (
          <Alert
            type={showTokenHard ? 'error' : 'warning'}
            showIcon
            banner
            className="aba-v2-banner"
            message={
              showTokenHard ? (
                <>
                  Included tokens exhausted — overage uses credits.{' '}
                  <Link to="/billing">Top up / billing</Link>
                </>
              ) : (
                <>
                  Included tokens running low — <Link to="/billing">top up</Link>
                </>
              )
            }
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
            className="aba-v2-banner"
            message={
              <>
                Free trial · 50k tokens · 10 agents
                {user?.subscription_expires_at && (() => {
                  const d = new Date(user.subscription_expires_at)
                  if (Number.isNaN(d.getTime())) return null
                  const days = Math.ceil((d.getTime() - Date.now()) / 86400000)
                  if (days < 0) return <> · expired {d.toLocaleDateString()}</>
                  if (days === 0) return <> · ends today</>
                  return <> · {days} day{days === 1 ? '' : 's'} left</>
                })()}
                {' '}— <Link to="/billing">Upgrade →</Link>
              </>
            }
          />
        )}

        <Content
          className={`aba-content aba-v2-content${bp.showBottomNav ? ' has-bottom-nav' : ''}`}
          data-aba-layout="content"
        >
          <div className="aba-page-center" data-aba-layout="page-center">
            <div className="aba-page-shell" data-aba-layout="page-shell">
              <Outlet />
            </div>
          </div>
        </Content>

        {bp.showBottomNav && (
          <BottomNav
            activeKey={path}
            menuOpen={menuOpen}
            onNavigate={goNav}
            onOpenMenu={() => setMenuOpen(true)}
          />
        )}

        <TopUpModal
          open={topupOpen}
          meter={meter}
          onClose={() => {
            snoozeTopup(meter?.hard_block ? 5 : 45)
            setTopupOpen(false)
            if (meter?.hard_block) nav('/billing')
          }}
          onTopped={() => {
            api('/billing/meter').then(setMeter).catch(() => {})
            setTopupOpen(false)
          }}
        />

        {!bp.showSider && (
          <NavDrawer
            open={menuOpen}
            onClose={() => setMenuOpen(false)}
            user={user}
            activeKey={path}
            items={menuItems}
            onNavigate={goNav}
            onExplore={() => setExploreOpen(true)}
            onLogout={logout}
          />
        )}

        <Drawer
          title="Explore everything"
          placement={bp.showSider ? 'right' : 'bottom'}
          height={bp.showSider ? undefined : '88%'}
          width={bp.showSider ? 420 : undefined}
          open={exploreOpen}
          onClose={() => setExploreOpen(false)}
          className="aba-explore-drawer"
          styles={{ body: { paddingTop: 8, paddingBottom: 32 } }}
          destroyOnClose={false}
        >
          <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
            Tap any card — same destinations as the menu.
          </Typography.Paragraph>
          <SystemNav onNavigate={() => setExploreOpen(false)} />
        </Drawer>
      </Layout>
    </Layout>
  )
}
