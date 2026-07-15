import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, HashRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import App from './App'
import { initNativeShell } from './native'

function isNative() {
  try {
    return !!window.Capacitor?.isNativePlatform?.()
  } catch {
    return false
  }
}

// HashRouter is more reliable inside the iOS WebView (no server-side fallbacks).
const Router = isNative() || import.meta.env.VITE_NATIVE === '1' ? HashRouter : BrowserRouter

async function boot() {
  await initNativeShell()
  ReactDOM.createRoot(document.getElementById('root')).render(
    <ConfigProvider theme={{ token: { colorPrimary: '#1668dc', borderRadius: 6 } }}>
      <Router>
        <App />
      </Router>
    </ConfigProvider>
  )
}

boot()
