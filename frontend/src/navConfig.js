/**
 * Single source of truth for app navigation (mobile-first v2).
 *
 * - bottomPrimary: fixed tab bar on phone/tablet (<1024)
 * - menuGroups: full menu in drawer (mobile) + desktop sider
 */

export const BOTTOM_PRIMARY = [
  { key: '/', label: 'Home', icon: 'home' },
  { key: '/console', label: 'Agents', icon: 'agents' },
  { key: '/tasks', label: 'Tasks', icon: 'tasks' },
  { key: '/business', label: 'Biz', icon: 'business' },
  { key: '__more__', label: 'More', icon: 'more' },
]

/** Full app map — order is UX priority (ops near top for daily use). */
export function buildMenuItems({ isAdmin = false } = {}) {
  const main = [
    { key: '/', label: 'Dashboard', icon: 'home', group: 'Work' },
    { key: '/console', label: 'Agent console', icon: 'agents', group: 'Work' },
    { key: '/agent-dash', label: 'Agent dashboard', icon: 'ops', group: 'Work' },
    { key: '/tasks', label: 'Tasks board', icon: 'tasks', group: 'Work' },
    { key: '/meetings', label: 'Meetings', icon: 'meetings', group: 'Work' },
    { key: '/business', label: 'Business CRM', icon: 'business', group: 'Work' },
    { key: '/comms', label: 'Calls · SMS · Email', icon: 'comms', group: 'Work' },
    { key: '/ops', label: 'Live ops', icon: 'ops', group: 'Work' },
    { key: '/chat', label: 'AI Chat', icon: 'chat', group: 'Work' },
    { key: '/workspace', label: 'Workspace', icon: 'workspace', group: 'Org' },
    { key: '/hierarchy', label: 'Hierarchy', icon: 'hierarchy', group: 'Org' },
    { key: '/humans', label: 'Team', icon: 'team', group: 'Org' },
    { key: '/permissions', label: 'Permissions', icon: 'permissions', group: 'Org' },
    { key: '/templates', label: 'Templates', icon: 'templates', group: 'Grow' },
    { key: '/training', label: 'Training', icon: 'training', group: 'Grow' },
    { key: '/analytics', label: 'Analytics', icon: 'analytics', group: 'Grow' },
    { key: '/billing', label: 'Billing', icon: 'billing', group: 'Account' },
    { key: '__bay__', label: 'AgentBay', icon: 'bay', group: 'Account', external: true },
    { key: '__site__', label: 'Website', icon: 'home', group: 'Account', external: true },
    { key: '/profile', label: 'Profile', icon: 'profile', group: 'Account' },
    { key: '/settings', label: 'Settings', icon: 'settings', group: 'Account' },
  ]
  if (isAdmin) {
    main.push({ key: '/admin', label: 'Staff Admin', icon: 'admin', group: 'Account' })
  }
  return main
}

/** Normalize route path for selected-key matching. */
export function activeNavKey(pathname) {
  const p = pathname || '/'
  if (
    p === '/agent-dash'
    || ((p.endsWith('/dash') || p.endsWith('/dash/'))
      && (p.includes('/agents') || p.includes('/console') || p.includes('/army')))
  ) {
    return '/agent-dash'
  }
  if (
    p.startsWith('/agents/')
    || p.startsWith('/army/')
    || p.startsWith('/console/')
  ) {
    return '/console'
  }
  if (p === '/agents' || p === '/army' || p === '/console') return '/console'
  if (p.startsWith('/business')) return '/business'
  if (p.startsWith('/meetings')) return '/meetings'
  if (p.startsWith('/companies/')) return '/workspace'
  if (p === '/users') return '/humans'
  if (p === '/calls') return '/comms'
  return p
}

export function pageTitle(pathname, menuItems = []) {
  const key = activeNavKey(pathname)
  const hit = menuItems.find((i) => i.key === key)
  if (hit) return hit.label
  if ((pathname.includes('/agents/') || pathname.includes('/army/') || pathname.includes('/console/'))
    && pathname.endsWith('/manage')) {
    return 'Agent setup'
  }
  if (pathname.includes('/agents/') || pathname.includes('/army/') || pathname.includes('/console/')) {
    return 'Agent chat'
  }
  if (pathname.startsWith('/business/customers/')) return 'Customer'
  if (pathname.startsWith('/companies/')) return 'Company'
  return 'Menu'
}

export function isAgentChatPath(pathname) {
  return (
    /^\/agents\/[^/]+$/.test(pathname)
    || /^\/agents\/[^/]+\/chat$/.test(pathname)
    || /^\/army\/[^/]+$/.test(pathname)
    || /^\/army\/[^/]+\/chat$/.test(pathname)
    || /^\/console\/[^/]+$/.test(pathname)
    || /^\/console\/[^/]+\/chat$/.test(pathname)
  )
}
