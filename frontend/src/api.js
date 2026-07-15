/**
 * API base URL:
 * - Local web: http://localhost:8000 (or VITE_API_URL)
 * - Vercel full-stack web: same-origin /api
 * - iOS/Android Capacitor: absolute production API (cannot use relative /api)
 *
 * Override anytime with VITE_API_URL.
 * Native default: VITE_PROD_API_URL or https://aiassitant-nu.vercel.app/api
 */

const PROD_API_DEFAULT = 'https://aiassitant-nu.vercel.app/api'

function isNativeShell() {
  try {
    // Capacitor injects this at runtime in the native WebView
    const cap = typeof window !== 'undefined' ? window.Capacitor : null
    if (cap?.isNativePlatform?.()) return true
    if (cap?.getPlatform?.() === 'ios' || cap?.getPlatform?.() === 'android') return true
  } catch {
    /* ignore */
  }
  // Build-time flag for store builds
  if (import.meta.env.VITE_NATIVE === '1' || import.meta.env.VITE_NATIVE === 'true') return true
  return false
}

function normalizeApiBase(url) {
  if (url !== undefined && url !== null && String(url).trim() !== '') {
    return String(url).trim().replace(/\/+$/, '')
  }
  if (isNativeShell()) {
    const native = import.meta.env.VITE_PROD_API_URL || PROD_API_DEFAULT
    return String(native).trim().replace(/\/+$/, '')
  }
  // Explicit empty / unset in production web → same-origin /api (Vercel full stack)
  if (import.meta.env.PROD) return '/api'
  return 'http://localhost:8000'
}

export const API = normalizeApiBase(import.meta.env.VITE_API_URL)
export const IS_NATIVE = isNativeShell()

/** WebSocket base. On Vercel serverless, WS often fails — chat falls back to REST. */
export function getWsBase() {
  if (API && (API.startsWith('http://') || API.startsWith('https://'))) {
    return API.replace(/^http/i, (m) => (m.toLowerCase() === 'https' ? 'wss' : 'ws'))
  }
  if (typeof window !== 'undefined') {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    return `${proto}://${window.location.host}`
  }
  return 'ws://localhost:8000'
}

// Back-compat for existing imports
export const WS =
  typeof window !== 'undefined'
    ? getWsBase()
    : API && API.startsWith('http')
      ? API.replace(/^http/i, (m) => (m.toLowerCase() === 'https' ? 'wss' : 'ws'))
      : 'ws://localhost:8000'

export function getToken() {
  return localStorage.getItem('token')
}
export function getUser() {
  try {
    return JSON.parse(localStorage.getItem('user'))
  } catch {
    return null
  }
}
export function setAuth(token, user) {
  localStorage.setItem('token', token)
  localStorage.setItem('user', JSON.stringify(user))
}
export function clearAuth() {
  localStorage.removeItem('token')
  localStorage.removeItem('user')
}

function formatDetail(detail) {
  if (!detail) return 'Request failed'
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
  }
  return String(detail)
}

export async function api(path, options = {}) {
  const res = await fetch(API + path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
      ...(options.headers || {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  })
  if (res.status === 401 && !path.startsWith('/auth/')) {
    clearAuth()
    window.location.href = '/login'
    throw new Error('Session expired')
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(formatDetail(data.detail) || 'Request failed')
  return data
}
