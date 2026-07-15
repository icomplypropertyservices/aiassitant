export const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
export const WS = API.replace(/^http/, 'ws')

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
