import React, { useMemo } from 'react'
import { Drawer, Menu, Avatar, Button, Typography } from 'antd'
import { CloseOutlined, LogoutOutlined, AppstoreAddOutlined } from '@ant-design/icons'
import { navIcon } from './navIcons'

/**
 * Full navigation drawer — mobile-first "More" menu.
 * Groups items for scannability on small screens.
 */
export default function NavDrawer({
  open,
  onClose,
  user,
  activeKey,
  items,
  onNavigate,
  onExplore,
  onLogout,
}) {
  const menuItems = useMemo(() => {
    const groups = {}
    for (const it of items) {
      const g = it.group || 'More'
      if (!groups[g]) groups[g] = []
      groups[g].push({
        key: it.key,
        icon: navIcon(it.icon),
        label: it.label,
      })
    }
    const out = []
    for (const [label, children] of Object.entries(groups)) {
      out.push({ type: 'group', label, children })
    }
    return out
  }, [items])

  return (
    <Drawer
      title={null}
      placement="bottom"
      height="min(92dvh, 920px)"
      open={open}
      onClose={onClose}
      className="aba-v2-nav-drawer"
      styles={{
        body: { padding: 0, display: 'flex', flexDirection: 'column', height: '100%' },
        header: { display: 'none' },
      }}
      closeIcon={null}
      destroyOnClose={false}
    >
      <div className="aba-v2-nav-drawer__sheet">
        <div className="aba-v2-nav-drawer__handle" aria-hidden />
        <header className="aba-v2-nav-drawer__head">
          <div className="aba-v2-nav-drawer__brand">
            <img
              src={`${import.meta.env.BASE_URL}logo.png`}
              alt=""
              width={36}
              height={36}
            />
            <div>
              <strong>AI Business Agent</strong>
              <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>
                All areas
              </Typography.Text>
            </div>
          </div>
          <Button
            type="text"
            icon={<CloseOutlined />}
            aria-label="Close menu"
            className="aba-touch-btn"
            onClick={onClose}
          />
        </header>

        <button
          type="button"
          className="aba-v2-nav-drawer__user"
          onClick={() => onNavigate?.('/profile')}
        >
          <Avatar
            size={40}
            style={{
              background: 'linear-gradient(135deg,#3b82f6,#1d4ed8)',
              fontWeight: 600,
              flexShrink: 0,
            }}
          >
            {(user?.name || user?.email || '?')[0].toUpperCase()}
          </Avatar>
          <div className="aba-v2-nav-drawer__user-text">
            <strong>{user?.name || user?.email || 'Account'}</strong>
            {user?.plan && user.plan !== 'none' && (
              <span className="plan">{String(user.plan).replace(/_/g, ' ')}</span>
            )}
          </div>
        </button>

        <div className="aba-v2-nav-drawer__scroll">
          <Menu
            mode="inline"
            selectedKeys={[activeKey]}
            items={menuItems}
            onClick={(e) => onNavigate?.(e.key)}
            className="aba-v2-nav-drawer__menu"
          />
        </div>

        <footer className="aba-v2-nav-drawer__foot">
          <Button
            block
            icon={<AppstoreAddOutlined />}
            onClick={() => {
              onClose?.()
              onExplore?.()
            }}
          >
            Explore all cards
          </Button>
          <Button
            block
            danger
            type="text"
            icon={<LogoutOutlined />}
            onClick={onLogout}
          >
            Sign out
          </Button>
        </footer>
      </div>
    </Drawer>
  )
}
