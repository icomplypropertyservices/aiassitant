/**
 * API base URL:
 * - Local web: http://localhost:8000 (or VITE_API_URL)
 * - Local with Vite proxy: set VITE_API_URL= (empty) or VITE_USE_PROXY=1 → /api
 * - Production web (aibusinessagent.xyz): same-origin /api
 *   App UI lives at /agents; API stays at domain root /api
 * - iOS/Android Capacitor: absolute production API
 *
 * Override anytime with VITE_API_URL.
 * Native default: VITE_PROD_API_URL or https://aibusinessagent.xyz/api
 */

// Prefer www: apex currently 308-redirects some POSTs to www, which breaks
// non-browser clients (urllib / some native stacks) that do not re-POST.
const PROD_API_DEFAULT = 'https://www.aibusinessagent.xyz/api'

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
  // Relative API (e.g. /api) → same host + that path prefix
  if (API && API.startsWith('/')) {
    if (typeof window !== 'undefined') {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      return `${proto}://${window.location.host}${API.replace(/\/+$/, '')}`
    }
  }
  if (typeof window !== 'undefined') {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    return `${proto}://${window.location.host}/api`
  }
  return 'ws://localhost:8000'
}

export const WS =
  typeof window !== 'undefined'
    ? getWsBase()
    : API && API.startsWith('http')
      ? API.replace(/^http/i, (m) => (m.toLowerCase() === 'https' ? 'wss' : 'ws'))
      : 'ws://localhost:8000'

/**
 * Session credential is an API key (aba_…), not a JWT.
 * Stored under `api_key` (preferred) and `token` (legacy key for older tabs).
 */
export function getApiKey() {
  try {
    return localStorage.getItem('api_key') || localStorage.getItem('token') || ''
  } catch {
    return ''
  }
}

/** @deprecated use getApiKey — kept so existing imports keep working */
export function getToken() {
  return getApiKey()
}

/**
 * Dead socket stub (Vercel/prod default — serverless has no durable WS).
 * Duck-types WebSocket enough for callers that assign onmessage / close.
 */
function createNoopSocket() {
  return {
    readyState: 3, // CLOSED
    mode: 'noop',
    send() {},
    close() {},
    addEventListener() {},
    removeEventListener() {},
    onopen: null,
    onclose: null,
    onerror: null,
    onmessage: null,
  }
}

/**
 * Open a WebSocket and auth with API key (first message, not JWT).
 * Production defaults to a noop socket unless `force: true` (Vercel has no durable WS).
 * Prefer `createRealtime({ mode })` for new call sites.
 *
 * @param {string} path
 * @param {{ useQueryToken?: boolean, force?: boolean }} [opts]
 */
export function connectAuthedWs(path, opts = {}) {
  if (import.meta.env.PROD && !opts.force) {
    return createNoopSocket()
  }
  const apiKey = getApiKey() || ''
  const p = path.startsWith('/') ? path : `/${path}`
  const base = getWsBase()
  let url
  if (opts.useQueryToken && apiKey) {
    const sep = p.includes('?') ? '&' : '?'
    url = `${base}${p}${sep}token=${encodeURIComponent(apiKey)}`
  } else {
    url = `${base}${p}`
  }
  const ws = new WebSocket(url)
  ws.mode = 'ws'
  if (!opts.useQueryToken && apiKey) {
    ws.addEventListener(
      'open',
      () => {
        try {
          ws.send(JSON.stringify({ type: 'auth', api_key: apiKey, token: apiKey }))
        } catch {
          /* ignore */
        }
      },
      { once: true },
    )
  }
  return ws
}

/**
 * Single realtime adapter so pages do not branch on env.
 *
 * Modes:
 * - `noop` — closed stub (default in production)
 * - `ws`   — authenticated WebSocket via connectAuthedWs (force in prod if needed)
 * - `poll` — interval polling; returns a socket-like with close() to clear the timer
 *
 * @param {{
 *   mode?: 'ws' | 'poll' | 'noop',
 *   path?: string,
 *   force?: boolean,
 *   useQueryToken?: boolean,
 *   intervalMs?: number,
 *   onPoll?: () => void | Promise<void>,
 * }} [opts]
 */
export function createRealtime(opts = {}) {
  const mode =
    opts.mode ||
    (import.meta.env.PROD && !opts.force ? 'noop' : 'ws')

  if (mode === 'noop') {
    return createNoopSocket()
  }

  if (mode === 'poll') {
    const intervalMs = opts.intervalMs ?? 8000
    let timer = null
    const tick = () => {
      try {
        const r = opts.onPoll?.()
        if (r && typeof r.then === 'function') r.catch(() => {})
      } catch {
        /* ignore poll errors */
      }
    }
    if (typeof opts.onPoll === 'function' && intervalMs > 0) {
      timer = setInterval(tick, intervalMs)
      // First tick shortly after open so UI is not empty
      setTimeout(tick, 0)
    }
    return {
      readyState: 1,
      mode: 'poll',
      send() {},
      close() {
        if (timer != null) {
          clearInterval(timer)
          timer = null
        }
      },
      addEventListener() {},
      removeEventListener() {},
      onopen: null,
      onclose: null,
      onerror: null,
      onmessage: null,
    }
  }

  // mode === 'ws'
  return connectAuthedWs(opts.path || '/agents/ws', {
    force: !!opts.force || !import.meta.env.PROD,
    useQueryToken: opts.useQueryToken,
  })
}
export function getUser() {
  try {
    const raw = localStorage.getItem('user')
    if (!raw || raw === 'undefined' || raw === 'null') return null
    const u = JSON.parse(raw)
    return u && typeof u === 'object' ? u : null
  } catch {
    return null
  }
}

/** Safe JSON.parse for WebSocket / external payloads — never throws. */
export function safeJsonParse(raw, fallback = null) {
  try {
    if (raw == null || raw === '') return fallback
    if (typeof raw === 'object') return raw
    return JSON.parse(raw)
  } catch {
    return fallback
  }
}

/** Persist session API key (+ optional user). Accepts login response field token or api_key. */
export function setAuth(apiKeyOrToken, user) {
  if (!apiKeyOrToken) {
    clearAuth()
    return
  }
  try {
    localStorage.setItem('api_key', apiKeyOrToken)
    localStorage.setItem('token', apiKeyOrToken) // legacy alias
    if (user) localStorage.setItem('user', JSON.stringify(user))
  } catch (e) {
    console.warn('[auth] localStorage write failed', e)
  }
}
export function clearAuth() {
  try {
    localStorage.removeItem('api_key')
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    localStorage.removeItem('agentbay_token')
    localStorage.removeItem('agentbay_user')
  } catch { /* private mode / quota */ }
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

/** Short TTL GET cache — makes revisiting lists/dashboard feel instant */
const _getCache = new Map()
const GET_CACHE_MS = 8000
const CACHEABLE_PREFIXES = [
  '/agents/',
  '/dashboard/',
  '/templates/',
  '/org/',
  '/billing/meter',
  '/billing/plans',
  '/humans/',
  '/meetings/',
]

function _cacheKey(path, method) {
  return `${method || 'GET'}:${path}:${getApiKey().slice(0, 16)}`
}

function _isCacheableGet(path, options) {
  const method = (options.method || 'GET').toUpperCase()
  if (method !== 'GET') return false
  if (options.cache === false || options.noCache) return false
  const p = path.startsWith('/') ? path : `/${path}`
  // Don't cache detail chat payloads with long paths that include dynamic churn
  if (p.includes('/chat') || p.includes('/ws')) return false
  return CACHEABLE_PREFIXES.some((pre) => p === pre || p.startsWith(pre) || p.startsWith(pre.replace(/\/$/, '')))
}

/** Bust list caches after mutations (call from create/update UIs if needed). */
export function invalidateApiCache(prefix = '') {
  if (!prefix) {
    _getCache.clear()
    return
  }
  for (const k of _getCache.keys()) {
    if (k.includes(prefix)) _getCache.delete(k)
  }
}

/**
 * Unified API fetch. Paths start with / (e.g. /auth/login).
 * GETs for list-ish endpoints are cached ~8s for snappy UI.
 * Default timeout 45s (chat/media can pass a longer timeoutMs or their own signal).
 */
export async function api(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  const cacheable = _isCacheableGet(path, options)
  const ckey = cacheable ? _cacheKey(path, method) : null
  if (ckey) {
    const hit = _getCache.get(ckey)
    if (hit && Date.now() - hit.at < GET_CACHE_MS) {
      return hit.data
    }
  }

  const url = `${API}${path.startsWith('/') ? path : `/${path}`}`
  let res
  let ownedController = null
  let timeoutId = null
  try {
    const apiKey = getApiKey()
    const {
      body,
      headers: optHeaders,
      signal: outerSignal,
      cache: _c,
      noCache: _n,
      timeoutMs,
      ...rest
    } = options

    // Default timeouts keep UI from hanging forever on flaky mobile networks
    let timeout = timeoutMs
    if (timeout == null) {
      if (/\/chat\b|\/messages\b|\/media\//i.test(path)) timeout = 120000
      else if (method === 'GET') timeout = 30000
      else timeout = 45000
    }

    let signal = outerSignal
    if (timeout > 0 && typeof AbortController !== 'undefined') {
      ownedController = new AbortController()
      signal = ownedController.signal
      if (outerSignal) {
        if (outerSignal.aborted) ownedController.abort()
        else {
          outerSignal.addEventListener('abort', () => {
            try { ownedController.abort() } catch { /* ignore */ }
          }, { once: true })
        }
      }
      timeoutId = setTimeout(() => {
        try { ownedController.abort() } catch { /* ignore */ }
      }, timeout)
    }

    res = await fetch(url, {
      ...rest,
      method,
      signal,
      headers: {
        Accept: 'application/json',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        // Site-wide API key auth (not JWT)
        ...(apiKey
          ? {
              'X-API-Key': apiKey,
              Authorization: `Bearer ${apiKey}`,
            }
          : {}),
        ...(optHeaders || {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (err) {
    if (err?.name === 'AbortError') {
      // Outer caller abort (navigate away) vs our timeout — keep AbortError name
      const timedOut = ownedController?.signal?.aborted && !options.signal?.aborted
      const e = new Error(
        timedOut
          ? 'Request timed out — check your connection and try again'
          : (err.message || 'Aborted'),
      )
      e.name = 'AbortError'
      throw e
    }
    const msg = err?.message || 'Network error'
    if (msg.includes('Failed to fetch') || msg.includes('NetworkError')) {
      throw new Error(
        `Cannot reach API at ${API}. Start the backend (port 8000) or check VITE_API_URL.`,
      )
    }
    throw new Error(msg)
  } finally {
    if (timeoutId) clearTimeout(timeoutId)
  }

  // Auth expired / missing — force re-login (except on auth endpoints)
  if (res.status === 401 && !path.startsWith('/auth/')) {
    clearAuth()
    if (typeof window !== 'undefined') {
      // App lives at /agents/* — never bounce to bare /login (that hit the wrong route)
      const base = (import.meta.env.BASE_URL || '/agents/').replace(/\/+$/, '') || '/agents'
      const loginUrl = `${base}/login`
      const here = window.location.pathname || ''
      if (!here.includes('/login') && !here.endsWith('/login')) {
        window.location.href = loginUrl
      }
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

  // Cache successful GETs for list endpoints
  if (ckey && method === 'GET') {
    _getCache.set(ckey, { at: Date.now(), data })
    // Bound cache size
    if (_getCache.size > 80) {
      const first = _getCache.keys().next().value
      _getCache.delete(first)
    }
  } else if (method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS') {
    // Mutations invalidate related caches (prefix match)
    invalidateApiCache('/agents')
    invalidateApiCache('/dashboard')
    invalidateApiCache('/meetings')
    invalidateApiCache('/humans')
    invalidateApiCache('/business')
    invalidateApiCache('/org')
    invalidateApiCache('/integrations')
    invalidateApiCache('/billing')
    invalidateApiCache('/tasks')
    invalidateApiCache('/ops')
  }

  return data
}
