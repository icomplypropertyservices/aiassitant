import React, { useMemo } from 'react'
import { Layout, Menu } from 'antd'
import { navIcon } from './navIcons'

const { Sider } = Layout

/**
 * Desktop-only permanent sidebar. Not mounted on phone (mobile-first).
 */
export default function DesktopSider({
  collapsed,
  onCollapse,
  activeKey,
  items,
  onNavigate,
}) {
  const menuItems = useMemo(
    () =>
      items.map((it) => ({
        key: it.key,
        icon: navIcon(it.icon),
        label: it.label,
      })),
    [items],
  )

  return (
    <Sider
      collapsible
      collapsed={collapsed}
      onCollapse={onCollapse}
      theme="dark"
      width={232}
      className="aba-sider aba-v2-sider"
      // Never auto-collapse via Ant breakpoint — we control mount via JS
      breakpoint={undefined}
      trigger={collapsed ? undefined : undefined}
    >
      <div
        className="aba-brand aba-card-clickable"
        role="button"
        tabIndex={0}
        aria-label="Go to Dashboard"
        onClick={() => onNavigate?.('/')}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onNavigate?.('/')
          }
        }}
      >
        <div className="aba-brand-mark" aria-hidden>
          <img
            src={`${import.meta.env.BASE_URL}logo.png`}
            alt=""
            width={40}
            height={40}
            style={{ objectFit: 'contain' }}
          />
        </div>
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
        selectedKeys={[activeKey]}
        items={menuItems}
        onClick={(e) => onNavigate?.(e.key)}
        style={{ borderInlineEnd: 'none', paddingBottom: 48 }}
      />
    </Sider>
  )
}
