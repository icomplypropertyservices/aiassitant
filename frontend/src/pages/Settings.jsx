import React, { useCallback, useEffect, useState } from 'react'
import { Card, Typography, Tabs, Badge, Space, message } from 'antd'
import {
  KeyOutlined, AppstoreOutlined, RobotOutlined, UserOutlined,
  CloudOutlined, MobileOutlined,
} from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import PageShell from '../components/PageShell'
import SystemNav from '../components/SystemNav'
import SettingsProfile from './settings/SettingsProfile'
import SettingsKeys from './settings/SettingsKeys'
import SettingsApps from './settings/SettingsApps'
import SettingsAgents from './settings/SettingsAgents'
import SettingsPlatform from './settings/SettingsPlatform'
import SettingsMobile from './settings/SettingsMobile'

export default function Settings() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialTab = searchParams.get('tab') || 'profile'
  const [tab, setTab] = useState(initialTab)
  const [connectedCount, setConnectedCount] = useState(0)
  const [appsRefreshKey, setAppsRefreshKey] = useState(0)
  const onConnectedCountChange = useCallback((n) => setConnectedCount(n), [])

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
      let friendly = decodeURIComponent(raw.replace(/\+/g, ' '))
      if (/invalid_request|redirect_uri|redirect uri/i.test(friendly)) {
        friendly = `${friendly} — Add the exact Redirect URI from Settings → Connected apps into Google Cloud Console (Authorized redirect URIs).`
      }
      message.error(friendly, 8)
      setTab('apps')
      setAppsRefreshKey((k) => k + 1)
    }
    const next = new URLSearchParams(searchParams)
    next.delete('oauth')
    next.delete('message')
    if (!next.get('tab')) next.set('tab', 'apps')
    setSearchParams(next, { replace: true })
  }, [])

  const onTabChange = (key) => {
    setTab(key)
    const next = new URLSearchParams(searchParams)
    next.set('tab', key)
    setSearchParams(next, { replace: true })
  }

  return (
    <PageShell>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Card className="aba-soft-card" styles={{ body: { paddingBlock: 16 } }}>
          <PageHeader
            title="Settings"
            subtitle="Profile, mobile, API keys, connected apps, and agent access"
            style={{ marginBottom: 0 }}
          />
        </Card>

        <Card
          className="aba-soft-card"
          size="small"
          title="Jump to any area"
          extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}>Click a card</Typography.Text>}
        >
          <SystemNav compact groups={false} />
        </Card>

        <Card className="aba-soft-card" styles={{ body: { paddingTop: 8 } }}>
          <Tabs
            activeKey={tab}
            onChange={onTabChange}
            centered
            tabBarStyle={{ marginBottom: 16 }}
            items={[
              { key: 'profile', label: <span><UserOutlined /> Profile</span>, children: <SettingsProfile /> },
              { key: 'mobile', label: <span><MobileOutlined /> Mobile</span>, children: <SettingsMobile active={tab === 'mobile'} /> },
              { key: 'keys', label: <span><KeyOutlined /> API keys</span>, children: <SettingsKeys /> },
              {
                key: 'apps',
                label: (
                  <span>
                    <AppstoreOutlined /> Connected apps{' '}
                    <Badge
                      count={connectedCount}
                      size="small"
                      offset={[4, -2]}
                    />
                  </span>
                ),
                children: (
                  <SettingsApps
                    key={appsRefreshKey}
                    onConnectedCountChange={onConnectedCountChange}
                  />
                ),
              },
              { key: 'agents', label: <span><RobotOutlined /> Agent apps</span>, children: <SettingsAgents /> },
              { key: 'platform', label: <span><CloudOutlined /> Platform</span>, children: <SettingsPlatform /> },
            ]}
          />
        </Card>
      </Space>
    </PageShell>
  )
}
