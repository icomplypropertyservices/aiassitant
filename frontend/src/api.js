/**
 * API base URL:
 * - Local web: http://localhost:8000 (or VITE_API_URL)
 * - Local with Vite proxy: set VITE_API_URL= (empty) or VITE_USE_PROXY=1 → /api
 * - Vercel full-stack web: same-origin /api
 * - iOS/Android Capacitor: absolute production API
 *
 * Override anytime with VITE_API_URL.
 * Native default: VITE_PROD_API_URL or https://aiassitant-nu.vercel.app/api
 */

const PROD_API_DEFAULT = 'https://aiassitant-nu.vercel.app/api'

function isNativeShell() {
  try {
    const cap = typeof window !== 'undefined' ? window.Capacitor : null
    if (cap?.isNativePlatform?.()) return true
    if (cap?.getPlatform?.() === 'ios' || cap?.getPlatform?.() === 'android') return true
  } catch {
    /* ignore */
  }
  if (import.meta.env.VITE_NATIVE === '1' || import.meta.env.VITE_NATIVE === 'true') return true
  return false
}

function normalizeApiBase(url) {
  // Explicit empty string → same-origin /api (matches Vercel + Vite proxy)
  if (url !== undefined && url !== null && String(url).trim() !== '') {
    return String(url).trim().replace(/\/+$/, '')
  }
  if (isNativeShell()) {
    const native = import.meta.env.VITE_PROD_API_URL || PROD_API_DEFAULT
    return String(native).trim().replace(/\/+$/, '')
  }
  // Dev: prefer Vite proxy (/api → backend) when VITE_USE_PROXY=1 or no VITE_API_URL set to absolute
  if (import.meta.env.DEV) {
    if (import.meta.env.VITE_USE_PROXY === '1' || import.meta.env.VITE_USE_PROXY === 'true') {
      return '/api'
    }
    return 'http://localhost:8000'
  }
  // Production web → same-origin /api (Vercel full stack)
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
  if (!token) {
    clearAuth()
    return
  }
  localStorage.setItem('token', token)
  if (user) localStorage.setItem('user', JSON.stringify(user))
}
export function clearAuth() {
  localStorage.removeItem('token')
  localStorage.removeItem('user')
}

function formatDetail(detail) {
  if (!detail) return null
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((d) => d.msg || d.message || JSON.stringify(d)).join('; ')
  }
  if (typeof detail === 'object') {
    if (detail.message) return String(detail.message)
    if (detail.error) return String(detail.error)
    try {
      return JSON.stringify(detail)
    } catch {
      return String(detail)
    }
  }
  return String(detail)
}

/**
 * Unified API fetch. Paths start with / (e.g. /auth/login).
 */
export async function api(path, options = {}) {
  const url = `${API}${path.startsWith('/') ? path : `/${path}`}`
  let res
  try {
    res = await fetch(url, {
      ...options,
      headers: {
        Accept: 'application/json',
        ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
        ...(options.headers || {}),
      },
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    })
  } catch (err) {
    const msg = err?.message || 'Network error'
    if (msg.includes('Failed to fetch') || msg.includes('NetworkError')) {
      throw new Error(
        `Cannot reach API at ${API}. Start the backend (port 8000) or check VITE_API_URL.`,
      )
    }
    throw new Error(msg)
  }

  // Auth expired — force re-login (except on auth endpoints)
  if (res.status === 401 && !path.startsWith('/auth/')) {
    clearAuth()
    if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
      window.location.href = '/login'
    }
    throw new Error('Session expired — please sign in again')
  }

  const contentType = (res.headers.get('content-type') || '').toLowerCase()
  const raw = await res.text()
  let data = {}
  if (raw) {
    if (contentType.includes('application/json') || raw.trim().startsWith('{') || raw.trim().startsWith('[')) {
      try {
        data = JSON.parse(raw)
      } catch {
        data = { detail: raw.slice(0, 300) }
      }
    } else if (raw.trim().startsWith('<!')) {
      // HTML response usually means wrong API base / SPA fallback
      data = {
        detail: res.ok
          ? 'Unexpected HTML from API — check VITE_API_URL / deploy routing'
          : `API error ${res.status}: received HTML instead of JSON (is the API running?)`,
      }
    } else {
      data = { detail: raw.slice(0, 400) }
    }
  }

  if (!res.ok) {
    // Startup failure payload from Vercel
    if (data.error === 'startup_failed') {
      const err = new Error(data.detail || data.hint || 'Server failed to start')
      err.status = res.status
      throw err
    }
    const detail =
      formatDetail(data.detail) ||
      formatDetail(data.message) ||
      formatDetail(data.error) ||
      `Request failed (${res.status})`
    const err = new Error(detail)
    err.status = res.status
    throw err
  }
  return data
}
