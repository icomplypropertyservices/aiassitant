import React from 'react'
import {
  Layout, Button, Dropdown, Avatar, Tag, Tooltip, Typography,
} from 'antd'
import {
  MenuOutlined,
  ArrowLeftOutlined,
  AppstoreAddOutlined,
  UserOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  CreditCardOutlined,
  SettingOutlined,
  LogoutOutlined,
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import TokenMeter from '../TokenMeter'
import { hapticLight } from '../../native'

const { Header } = Layout

/**
 * Compact sticky header — phone first (hamburger + title + meter).
 * Desktop adds back control and plan chip.
 */
export default function AppHeader({
  title,
  user,
  meter,
  showSider,
  onOpenMenu,
  onOpenExplore,
  onLogout,
}) {
  const nav = useNavigate()
  const loc = useLocation()

  return (
    <Header className="aba-header aba-v2-header">
      <div className="aba-v2-header__left">
        {!showSider && (
          <Button
            type="text"
            className="aba-touch-btn aba-v2-header__menu-btn"
            icon={<MenuOutlined />}
            aria-label="Open menu"
            onClick={() => {
              hapticLight()
              onOpenMenu?.()
            }}
          />
        )}
        {/* Back on desktop always; on mobile when not on Home so Chat / detail pages can leave */}
        {(showSider || (loc.pathname && loc.pathname !== '/')) && (
          <Tooltip title="Go back">
            <Button
              type="text"
              className="aba-header-back aba-touch-btn"
              icon={<ArrowLeftOutlined />}
              aria-label="Go back"
              onClick={() => {
                hapticLight()
                if (loc.key && loc.key !== 'default') nav(-1)
                else nav('/')
              }}
            />
          </Tooltip>
        )}
        <Typography.Text
          className="aba-v2-header__title"
          ellipsis
          onClick={() => {
            if (!showSider) {
              hapticLight()
              onOpenMenu?.()
            }
          }}
          role={!showSider ? 'button' : undefined}
          tabIndex={!showSider ? 0 : undefined}
        >
          {title || 'Menu'}
        </Typography.Text>
      </div>

      <div className="aba-v2-header__right">
        <Tooltip title="Explore">
          <Button
            type="text"
            className="aba-touch-btn aba-v2-header__icon-btn"
            icon={<AppstoreAddOutlined />}
            aria-label="Explore system"
            onClick={() => {
              hapticLight()
              onOpenExplore?.()
            }}
          />
        </Tooltip>
        <TokenMeter
          user={user}
          onClick={() => {
            hapticLight()
            // Route from existing meter flags — no extra poll
            const path =
              meter?.upgrade_cta_path
              || (meter?.needs_subscription || user?.needs_subscription ? '/subscribe' : '/billing')
            nav(path)
          }}
          meter={
            meter
              ? {
                  ...meter,
                  plan: meter.plan || user?.plan,
                  needs_subscription:
                    meter.needs_subscription ?? user?.needs_subscription,
                  subscription_expires_at:
                    meter.subscription_expires_at || user?.subscription_expires_at,
                }
              : meter
          }
        />
        {showSider && user?.plan && user.plan !== 'none' && (
          <Tag
            color="blue"
            className="aba-v2-header__plan aba-card-clickable"
            onClick={() => nav(user?.needs_subscription ? '/subscribe' : '/billing')}
          >
            {user.plan.replace(/_/g, ' ')}
          </Tag>
        )}
        <Dropdown
          menu={{
            items: [
              {
                key: 'explore',
                icon: <AppstoreAddOutlined />,
                label: 'Explore everything',
                onClick: () => onOpenExplore?.(),
              },
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
                onClick: () => onLogout?.(),
              },
            ],
          }}
        >
          <button type="button" className="aba-user-chip aba-v2-header__user aba-card-clickable">
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
            {showSider && (
              <span className="name">{user?.name || user?.email}</span>
            )}
          </button>
        </Dropdown>
      </div>
    </Header>
  )
}
