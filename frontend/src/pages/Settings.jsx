import React, { useCallback, useEffect, useState, Suspense, lazy } from 'react'
import { Card, Tabs, Badge, message, Spin } from 'antd'
import {
  KeyOutlined, AppstoreOutlined, RobotOutlined, UserOutlined,
  CloudOutlined, MobileOutlined,
} from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import PageShell from '../components/PageShell'
import ErrorBoundary from '../components/ErrorBoundary'

// Lazy tab bodies so a broken tab cannot blank the whole Settings page
const SettingsProfile = lazy(() => import('./settings/SettingsProfile'))
const SettingsKeys = lazy(() => import('./settings/SettingsKeys'))
const SettingsApps = lazy(() => import('./settings/SettingsApps'))
const SettingsAgents = lazy(() => import('./settings/SettingsAgents'))
const SettingsPlatform = lazy(() => import('./settings/SettingsPlatform'))
const SettingsMobile = lazy(() => import('./settings/SettingsMobile'))

function TabPane({ children }) {
  return (
    <ErrorBoundary compact title="This settings section failed">
      <Suspense
        fallback={(
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin tip="Loading…" />
          </div>
        )}
      >
        {children}
      </Suspense>
    </ErrorBoundary>
  )
}

export default function Settings() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialTab = searchParams.get('tab') || 'profile'
  const allowed = new Set(['profile', 'mobile', 'keys', 'apps', 'agents', 'platform'])
  const [tab, setTab] = useState(allowed.has(initialTab) ? initialTab : 'profile')
  const [connectedCount, setConnectedCount] = useState(0)
  const [appsRefreshKey, setAppsRefreshKey] = useState(0)
  const onConnectedCountChange = useCallback((n) => {
    const num = Number(n)
    setConnectedCount(Number.isFinite(num) && num > 0 ? Math.floor(num) : 0)
  }, [])

  // Keep tab in sync if URL changes (e.g. OAuth return)
  useEffect(() => {
    const t = searchParams.get('tab')
    if (t && allowed.has(t) && t !== tab) setTab(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  // OAuth return toast — remount apps tab so connections reload
  useEffect(() => {
    const oauth = searchParams.get('oauth')
    if (!oauth) return
    if (oauth === 'success') {
      message.success('App connected via OAuth')
      setTab('apps')
      setAppsRefreshKey((k) => k + 1)
    } else if (oauth === 'error') {
      const raw = searchParams.get('message') || 'OAuth failed'
      let friendly = decodeURIComponent(String(raw).replace(/\+/g, ' '))
      if (/access_denied|verification process|only be accessed by developer-approved|test user/i.test(friendly)) {
        friendly = (
          'Google 403 access_denied: OAuth consent screen is in Testing. '
          + 'Add your Google email under Google Cloud Console → OAuth consent screen → Test users, then Connect again with that account.'
        )
      } else if (/invalid_request|redirect_uri|redirect uri|mismatch/i.test(friendly)) {
        friendly = `${friendly} — Add this exact Redirect URI in Google Cloud Console → Credentials → Web client: https://www.aibusinessagent.xyz/api/integrations/oauth/callback`
      }
      message.error(friendly, 14)
      setTab('apps')
      setAppsRefreshKey((k) => k + 1)
    }
    try {
      const next = new URLSearchParams(searchParams)
      next.delete('oauth')
      next.delete('message')
      if (!next.get('tab')) next.set('tab', 'apps')
      setSearchParams(next, { replace: true })
    } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const onTabChange = (key) => {
    const k = allowed.has(key) ? key : 'profile'
    setTab(k)
    try {
      const next = new URLSearchParams(searchParams)
      next.set('tab', k)
      setSearchParams(next, { replace: true })
    } catch { /* ignore */ }
  }

  return (
    <PageShell
      title="Settings"
      subtitle={
        tab === 'apps'
          ? 'Connect Gmail, Sheets, and other apps'
          : 'Profile, keys, apps, and agent access'
      }
      showBack
      backTo="/"
    >
      <Card className="aba-soft-card" styles={{ body: { paddingTop: 8 } }}>
        <Tabs
          activeKey={tab}
          onChange={onTabChange}
          destroyInactiveTabPane
          tabBarStyle={{ marginBottom: 16 }}
          items={[
            {
              key: 'profile',
              label: <span><UserOutlined /> Profile</span>,
              children: <TabPane><SettingsProfile /></TabPane>,
            },
            {
              key: 'mobile',
              label: <span><MobileOutlined /> Mobile</span>,
              children: (
                <TabPane>
                  <SettingsMobile active={tab === 'mobile'} />
                </TabPane>
              ),
            },
            {
              key: 'keys',
              label: <span><KeyOutlined /> API keys</span>,
              children: <TabPane><SettingsKeys /></TabPane>,
            },
            {
              key: 'apps',
              label: (
                <span>
                  <AppstoreOutlined /> Apps{' '}
                  {connectedCount > 0 ? (
                    <Badge count={connectedCount} size="small" offset={[4, -2]} />
                  ) : null}
                </span>
              ),
              children: (
                <TabPane>
                  <SettingsApps
                    key={appsRefreshKey}
                    onConnectedCountChange={onConnectedCountChange}
                  />
                </TabPane>
              ),
            },
            {
              key: 'agents',
              label: <span><RobotOutlined /> Agents</span>,
              children: <TabPane><SettingsAgents /></TabPane>,
            },
            {
              key: 'platform',
              label: <span><CloudOutlined /> Platform</span>,
              children: <TabPane><SettingsPlatform /></TabPane>,
            },
          ]}
        />
      </Card>
    </PageShell>
  )
}
