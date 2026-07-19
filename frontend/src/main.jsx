import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, HashRouter } from 'react-router-dom'
import { ConfigProvider, App as AntApp } from 'antd'
import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import { initNativeShell } from './native'
import './styles/global.css'

/** Prevent uncaught promise / script errors from blanking the UI silently. */
function installGlobalHandlers() {
  if (typeof window === 'undefined') return
  window.addEventListener('unhandledrejection', (ev) => {
    try {
      console.warn('[unhandledrejection]', ev?.reason)
      // Stop some mobile WebViews from treating rejection as fatal
      ev?.preventDefault?.()
    } catch { /* ignore */ }
  })
  window.addEventListener('error', (ev) => {
    try {
      // ResizeObserver / script load noise — log only
      const msg = String(ev?.message || '')
      if (/ResizeObserver|Script error\.?/i.test(msg)) return
      console.warn('[window.error]', msg, ev?.filename, ev?.lineno)
    } catch { /* ignore */ }
  })
}
installGlobalHandlers()

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

function renderBootError(err) {
  const el = document.getElementById('root')
  if (!el) return
  const msg = String(err?.message || err || 'Failed to start')
  el.innerHTML = `
    <div style="min-height:100dvh;display:flex;align-items:center;justify-content:center;padding:24px;font-family:system-ui,sans-serif;background:#f1f5f9">
      <div style="max-width:420px;background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:24px;text-align:center;box-shadow:0 4px 24px rgba(15,23,42,.08)">
        <h1 style="font-size:18px;margin:0 0 8px;color:#0f172a">App failed to start</h1>
        <p style="font-size:13px;color:#64748b;margin:0 0 16px">${msg.replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]))}</p>
        <button type="button" onclick="location.reload()" style="background:#1668dc;color:#fff;border:0;border-radius:8px;padding:10px 18px;font-size:14px;font-weight:600;cursor:pointer">
          Reload
        </button>
      </div>
    </div>
  `
}

async function boot() {
  try {
    try {
      await initNativeShell()
    } catch (e) {
      console.warn('[boot] native shell init failed (continuing)', e)
    }
    const root = document.getElementById('root')
    if (!root) throw new Error('Missing #root element')
    ReactDOM.createRoot(root).render(
      <ErrorBoundary fullPage title="App crashed">
        <ConfigProvider theme={theme}>
          <AntApp>
            <Router basename={routerBasename}>
              <App />
            </Router>
          </AntApp>
        </ConfigProvider>
      </ErrorBoundary>,
    )
  } catch (err) {
    console.error('[boot]', err)
    renderBootError(err)
  }
}

boot()
