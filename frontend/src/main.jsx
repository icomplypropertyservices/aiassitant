import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, HashRouter } from 'react-router-dom'
import { ConfigProvider, App as AntApp } from 'antd'
import App from './App'
import { initNativeShell } from './native'
import './styles/global.css'

function isNative() {
  try {
    return !!window.Capacitor?.isNativePlatform?.()
  } catch {
    return false
  }
}

// HashRouter is more reliable inside the iOS WebView (no server-side fallbacks).
const useHash = isNative() || import.meta.env.VITE_NATIVE === '1'
const Router = useHash ? HashRouter : BrowserRouter
// Path deploy: https://aibusinessagent.xyz/agents  (Vite base → import.meta.env.BASE_URL)
const routerBasename = (() => {
  if (useHash) return undefined
  const raw = (import.meta.env.BASE_URL || '/').replace(/\/+$/, '')
  return raw && raw !== '/' ? raw : undefined
})()

// Mobile-first theme: denser touch targets by default; desktop keeps polish.
const theme = {
  token: {
    colorPrimary: '#1668dc',
    colorInfo: '#1668dc',
    colorSuccess: '#16a34a',
    colorWarning: '#d97706',
    colorError: '#dc2626',
    colorTextBase: '#0f172a',
    colorTextSecondary: '#64748b',
    colorBorder: '#e2e8f0',
    colorBgLayout: '#f1f5f9',
    colorBgContainer: '#ffffff',
    borderRadius: 10,
    borderRadiusLG: 12,
    fontFamily:
      '"Inter", "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif',
    fontSize: 14,
    // 40px controls read better on phone than 36
    controlHeight: 40,
    controlHeightSM: 32,
    controlHeightLG: 44,
    boxShadow: '0 1px 2px rgba(15, 23, 42, 0.04), 0 4px 16px rgba(15, 23, 42, 0.04)',
    boxShadowSecondary: '0 4px 24px rgba(15, 23, 42, 0.08)',
  },
  components: {
    Button: {
      primaryShadow: '0 1px 2px rgba(22, 104, 220, 0.25)',
      fontWeight: 500,
      controlHeight: 40,
      paddingInline: 16,
    },
    Card: {
      headerFontSize: 15,
      paddingLG: 16,
    },
    Menu: {
      darkItemBg: 'transparent',
      darkSubMenuItemBg: 'transparent',
      darkItemSelectedBg: 'rgba(255,255,255,0.14)',
      itemBorderRadius: 8,
      itemHeight: 44,
    },
    Layout: {
      headerBg: 'transparent',
      bodyBg: 'transparent',
      siderBg: '#0b1f3a',
    },
    Table: {
      headerBg: '#f8fafc',
      rowHoverBg: '#f1f5f9',
    },
    Tabs: {
      titleFontSize: 14,
      horizontalItemPadding: '10px 12px',
    },
    Drawer: {
      paddingLG: 16,
    },
  },
}

async function boot() {
  await initNativeShell()
  ReactDOM.createRoot(document.getElementById('root')).render(
    <ConfigProvider theme={theme}>
      <AntApp>
        <Router basename={routerBasename}>
          <App />
        </Router>
      </AntApp>
    </ConfigProvider>
  )
}

boot()
