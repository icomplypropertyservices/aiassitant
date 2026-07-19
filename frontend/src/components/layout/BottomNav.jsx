import React from 'react'
import { hapticSelect } from '../../native'
import { navIcon } from './navIcons'
import { BOTTOM_PRIMARY } from '../../navConfig'

/**
 * Fixed bottom tab bar — primary mobile navigation (phone + tablet).
 * Desktop hides this; permanent sider takes over.
 */
export default function BottomNav({
  activeKey,
  menuOpen,
  onNavigate,
  onOpenMenu,
}) {
  return (
    <nav className="aba-v2-bottom-nav" aria-label="Primary">
      {BOTTOM_PRIMARY.map((item) => {
        const isMore = item.key === '__more__'
        const active = isMore
          ? menuOpen
          : activeKey === item.key
            || (item.key !== '/' && activeKey.startsWith(item.key))
        return (
          <button
            key={item.key}
            type="button"
            className={`aba-v2-bottom-nav__item${active ? ' is-active' : ''}`}
            aria-current={active && !isMore ? 'page' : undefined}
            aria-label={item.label}
            onClick={() => {
              hapticSelect()
              if (isMore) {
                onOpenMenu?.()
                return
              }
              onNavigate?.(item.key)
            }}
          >
            <span className="aba-v2-bottom-nav__icon" aria-hidden>
              {navIcon(item.icon)}
            </span>
            <span className="aba-v2-bottom-nav__label">{item.label}</span>
          </button>
        )
      })}
    </nav>
  )
}
