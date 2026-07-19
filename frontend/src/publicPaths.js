/**
 * Public path layout on the apex domain (no subdomains):
 *   /           marketing landing (website/)
 *   /agents/*   product SPA
 *   /bay/*      AgentBay marketplace SPA
 *   /api/*      product API
 *
 * Always use root-absolute paths so click-through works whether the
 * browser is on aibusinessagent.xyz or www (same path layout).
 */

export const APEX_HOST = 'aibusinessagent.xyz'
export const APEX_ORIGIN = `https://${APEX_HOST}`

/** Prefer apex origin in production; localhost keeps current origin. */
export function siteOrigin() {
  if (typeof window === 'undefined') return APEX_ORIGIN
  const h = window.location.hostname || ''
  if (h === 'localhost' || h === '127.0.0.1' || h.endsWith('.local')) {
    return window.location.origin
  }
  if (h === APEX_HOST || h === `www.${APEX_HOST}`) return APEX_ORIGIN
  return window.location.origin
}

function withSuffix(base, suffix = '') {
  if (!suffix) return base
  const s = String(suffix)
  if (s.startsWith('http://') || s.startsWith('https://')) return s
  if (s.startsWith(base)) return s
  return `${base}${s.startsWith('/') ? s : `/${s}`}`
}

/** Product app path, e.g. appPath('/login') → /agents/login */
export function appPath(suffix = '') {
  return withSuffix('/agents', suffix)
}

/** AgentBay path, e.g. bayPath('/browse') → /bay/browse */
export function bayPath(suffix = '') {
  return withSuffix('/bay', suffix)
}

/** Marketing site path on domain root, e.g. sitePath('/') → / */
export function sitePath(suffix = '/') {
  if (!suffix || suffix === '/') return '/'
  const s = String(suffix)
  if (s.startsWith('http')) return s
  return s.startsWith('/') ? s : `/${s}`
}

/** Absolute URL when a full origin is required (email, native, share). */
export function absoluteAppUrl(suffix = '') {
  return `${siteOrigin()}${appPath(suffix)}`
}

export function absoluteBayUrl(suffix = '') {
  return `${siteOrigin()}${bayPath(suffix)}`
}

export function absoluteSiteUrl(suffix = '/') {
  const p = sitePath(suffix)
  return `${siteOrigin()}${p === '/' ? '/' : p}`
}

/** Hard navigation out of the React SPA (marketing or bay). */
export function goExternal(path) {
  if (typeof window === 'undefined') return
  window.location.href = path
}

export function goBay(suffix = '/browse') {
  goExternal(bayPath(suffix))
}

export function goMarketing(suffix = '/') {
  goExternal(sitePath(suffix))
}

export function goApp(suffix = '/') {
  // Inside SPA prefer relative /agents routes handled by router base;
  // for full page load use path under /agents.
  goExternal(appPath(suffix === '/' ? '' : suffix))
}
