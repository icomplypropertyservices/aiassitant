/**
 * API base URL:
 * - Local: default http://localhost:8000 (or VITE_API_URL)
 * - Vercel full-stack: leave VITE_API_URL empty → same origin (rewrites → /api Python)
 */
function normalizeApiBase(url) {
  // Explicit empty / unset in production → same-origin /api (Vercel full stack)
  if (url === undefined || url === null || String(url).trim() === '') {
    if (import.meta.env.PROD) return '/api'
    return 'http://localhost:8000'
  }
  return String(url).trim().replace(/\/+$/, '')
}

export const API = normalizeApiBase(import.meta.env.VITE_API_URL)

/** WebSocket base. On Vercel serverless, WS often fails — chat falls back to REST. */
export function getWsBase() {
  if (API) {
    return API.replace(/^http/i, (m) => (m.toLowerCase() === 'https' ? 'wss' : 'ws'))
  }
  if (typeof window !== 'undefined') {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    return `${proto}://${window.location.host}`
  }
  return 'ws://localhost:8000'
}

// Back-compat for existing imports (lazy-ish: may be empty until first page load)
export const WS = typeof window !== 'undefined' ? getWsBase() : (API ? API.replace(/^http/i, (m) => (m.toLowerCase() === 'https' ? 'wss' : 'ws')) : 'ws://localhost:8000')

export function getToken() { return localStorage.getItem('token') }
export function getUser() {
  try { return JSON.parse(localStorage.getItem('user')) } catch { return null }
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
    return detail.map(d => d.msg || JSON.stringify(d)).join('; ')
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
