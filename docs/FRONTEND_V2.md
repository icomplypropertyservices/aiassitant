# Frontend v2 — mobile-first shell

## Principle

**Phone is the default.** Desktop is progressive enhancement.

| Width | Chrome |
|------:|--------|
| &lt; 768px | Sticky header · content · **bottom tabs** · bottom-sheet menu |
| 768–1023 | Same as phone (+ slightly roomier padding) |
| ≥ 1024px | **Permanent sider** · header · content · **no** bottom nav |

Sider is **not mounted** on phone (not only `display: none`).

## Architecture

```text
src/
  navConfig.js                 # bottom + full menu single source of truth
  hooks/useBreakpoint.js       # isPhone / showSider / showBottomNav
  components/
    AppLayout.jsx              # re-exports AppShell
    layout/
      AppShell.jsx             # shell orchestrator
      AppHeader.jsx
      BottomNav.jsx
      NavDrawer.jsx            # bottom sheet "More"
      DesktopSider.jsx
      useShellSession.js       # auth + meter + top-up
      navIcons.jsx
  styles/v2/shell.css          # mobile-first chrome CSS
```

## Bottom tabs (primary)

Home · Agents · Tasks · Biz · More

Full destinations live in the **More** sheet (grouped: Work / Org / Grow / Account).

## CSS load order

`global.css` imports legacy `parts/*` then `v2/shell.css` so v2 chrome wins without breaking page polish.

## Adding a nav item

1. Add to `buildMenuItems()` in `navConfig.js`.
2. Add icon key in `navIcons.jsx`.
3. Optionally promote to `BOTTOM_PRIMARY` (keep ≤5 tabs).

## Agent chat

Full-screen host: no bottom nav / no sider chrome (`isAgentChatPath`).
