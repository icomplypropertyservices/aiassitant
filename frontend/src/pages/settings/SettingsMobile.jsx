import React, { useEffect, useState } from 'react'
import {
  Card, Typography, Alert, Button, Tag, Space, message, List, Switch,
} from 'antd'
import { MobileOutlined, NotificationOutlined } from '@ant-design/icons'
import { api } from '../../api'
import {
  isNative,
  getNativePlatform,
  getHapticsEnabled,
  getNotificationsEnabled,
  setHapticsEnabled,
  setNotificationsEnabled,
  registerPush,
  getPushToken,
  hapticSuccess,
  hapticMedium,
  notifyLocal,
} from '../../native'

const { Text, Paragraph } = Typography

export default function SettingsMobile({ active }) {
  const [hapticsOn, setHapticsOn] = useState(getHapticsEnabled())
  const [notifOn, setNotifOn] = useState(getNotificationsEnabled())
  const [pushDevices, setPushDevices] = useState([])
  const [pushStatus, setPushStatus] = useState(null)

  useEffect(() => {
    if (!active) return
    api('/devices/push').then((r) => setPushDevices(r.devices || [])).catch(() => {})
    api('/devices/push/status').then(setPushStatus).catch(() => {})
  }, [active])

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title={<Space><MobileOutlined /> Phone feel & alerts</Space>} className="aba-soft-card" type="inner">
        <Alert
          type="info"
          showIcon
          message={isNative() ? `Native ${getNativePlatform()} app` : 'Web preview'}
          description={
            isNative()
              ? 'Haptics and notifications use the device OS.'
              : 'Open the iOS/Android app for full haptics and push. On web these controls are previews only.'
          }
        />
      </Card>
      <Card title={<Space><MobileOutlined /> Haptics</Space>} className="aba-soft-card" type="inner">
        <Space direction="vertical" style={{ width: '100%' }}>
          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Text>Vibration / haptic feedback</Text>
            <Switch
              checked={hapticsOn}
              onChange={async (v) => {
                setHapticsOn(v)
                await setHapticsEnabled(v)
                if (v) hapticSuccess()
              }}
            />
          </Space>
          <Space wrap>
            <Button size="small" onClick={() => { hapticMedium(); message.info('Medium tap') }}>Test medium</Button>
            <Button size="small" onClick={() => { hapticSuccess(); message.success('Success') }}>Test success</Button>
          </Space>
          <Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
            Used when you send chat, complete agent steps, and navigate on device.
          </Paragraph>
        </Space>
      </Card>
      <Card title={<Space><NotificationOutlined /> Notifications</Space>} className="aba-soft-card" type="inner">
        <Space direction="vertical" style={{ width: '100%' }}>
          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Text>Push &amp; local alerts</Text>
            <Switch
              checked={notifOn}
              onChange={async (v) => {
                setNotifOn(v)
                await setNotificationsEnabled(v)
                if (v) {
                  const r = await registerPush()
                  if (r?.ok) message.success('Notifications ready')
                  else message.warning(r?.reason || 'Permission needed in system settings')
                }
              }}
            />
          </Space>
          <Button
            onClick={async () => {
              const r = await notifyLocal({
                title: 'AI Assistant',
                body: 'Test notification — agents and ops can alert you like this.',
              })
              if (r?.ok) {
                hapticSuccess()
                message.success('Notification scheduled')
              } else {
                message.warning(r?.reason || 'Could not show notification (use the mobile app)')
              }
            }}
          >
            Send test notification
          </Button>
          <Button
            type="primary"
            ghost
            onClick={async () => {
              const r = await registerPush()
              message.info(r?.ok ? `Registered · token ${String(getPushToken() || '').slice(0, 12)}…` : (r?.reason || 'Failed'))
              api('/devices/push').then((x) => setPushDevices(x.devices || [])).catch(() => {})
            }}
          >
            Register this device for push
          </Button>
          {pushStatus && (
            <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
              Devices on account: {pushStatus.enabled_devices || 0}. {pushStatus.note}
            </Paragraph>
          )}
          {pushDevices.length > 0 && (
            <List
              size="small"
              header="Registered devices"
              dataSource={pushDevices}
              renderItem={(d) => (
                <List.Item>
                  <Space>
                    <Tag color={d.enabled ? 'green' : 'default'}>{d.platform || 'device'}</Tag>
                    <Text type="secondary">{d.token_preview}</Text>
                  </Space>
                </List.Item>
              )}
            />
          )}
        </Space>
      </Card>
    </Space>
  )
}
