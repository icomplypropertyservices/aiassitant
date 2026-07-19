/**
 * Capacitor native shell: status bar, keyboard, haptics, push + local notifications.
 * Safe no-ops on web.
 */
import { Preferences } from '@capacitor/preferences'

let _native = false
let _platform = 'web'
let _pushReady = false
let _hapticsEnabled = true
let _notifEnabled = true

export function isNative() {
  try {
    return !!window.Capacitor?.isNativePlatform?.()
  } catch {
    return false
  }
}

export function getNativePlatform() {
  return _platform
}

async function loadPrefs() {
  try {
    if (!isNative()) return
    const h = await Preferences.get({ key: 'haptics_enabled' })
    const n = await Preferences.get({ key: 'notifications_enabled' })
    if (h.value != null) _hapticsEnabled = h.value !== '0' && h.value !== 'false'
    if (n.value != null) _notifEnabled = n.value !== '0' && n.value !== 'false'
  } catch {
    /* ignore */
  }
}

export async function setHapticsEnabled(on) {
  _hapticsEnabled = !!on
  try {
    if (isNative()) await Preferences.set({ key: 'haptics_enabled', value: on ? '1' : '0' })
  } catch { /* ignore */ }
}

export async function setNotificationsEnabled(on) {
  _notifEnabled = !!on
  try {
    if (isNative()) await Preferences.set({ key: 'notifications_enabled', value: on ? '1' : '0' })
  } catch { /* ignore */ }
  if (on) {
    try { await registerPush() } catch { /* ignore */ }
  }
}

export function getHapticsEnabled() {
  return _hapticsEnabled
}

export function getNotificationsEnabled() {
  return _notifEnabled
}

// ─── Haptics ───────────────────────────────────────────────────────────────

async function impact(style = 'Medium') {
  if (!_native || !_hapticsEnabled) return
  try {
    const { Haptics, ImpactStyle } = await import('@capacitor/haptics')
    const map = {
      Light: ImpactStyle.Light,
      Medium: ImpactStyle.Medium,
      Heavy: ImpactStyle.Heavy,
    }
    await Haptics.impact({ style: map[style] || ImpactStyle.Medium })
  } catch { /* web / simulator */ }
}

async function notificationHaptic(type = 'SUCCESS') {
  if (!_native || !_hapticsEnabled) return
  try {
    const { Haptics, NotificationType } = await import('@capacitor/haptics')
    const map = {
      SUCCESS: NotificationType.Success,
      WARNING: NotificationType.Warning,
      ERROR: NotificationType.Error,
    }
    await Haptics.notification({ type: map[type] || NotificationType.Success })
  } catch { /* ignore */ }
}

async function selectionChanged() {
  if (!_native || !_hapticsEnabled) return
  try {
    const { Haptics } = await import('@capacitor/haptics')
    await Haptics.selectionStart()
    await Haptics.selectionChanged()
    await Haptics.selectionEnd()
  } catch { /* ignore */ }
}

/** Light tap — nav, toggles */
export function hapticLight() {
  return impact('Light')
}

/** Medium — primary buttons, send message */
export function hapticMedium() {
  return impact('Medium')
}

// ─── Keep screen awake (voice / agent talking) ─────────────────────────────

let _wakeLock = null
let _wakeHolders = 0

/**
 * Prevent the phone from sleeping while the agent is talking or mic is open.
 * Uses Screen Wake Lock API on web/PWA; Capacitor KeepAwake when available.
 * Call releaseKeepAwake() when done (paired with each acquireKeepAwake).
 */
export async function acquireKeepAwake(reason = 'voice') {
  _wakeHolders += 1
  if (_wakeHolders > 1 && _wakeLock) return true
  try {
    // Optional Capacitor plugin — never static-import (may not be installed)
    if (isNative()) {
      try {
        // eslint-disable-next-line no-new-func
        const dynImport = new Function('m', 'return import(m)')
        const mod = await dynImport('@capacitor-community/keep-awake').catch(() => null)
        if (mod?.KeepAwake?.keepAwake) {
          await mod.KeepAwake.keepAwake()
          _wakeLock = { type: 'capacitor' }
          return true
        }
      } catch { /* optional plugin */ }
    }
    if (typeof navigator !== 'undefined' && navigator.wakeLock?.request) {
      try {
        const lock = await navigator.wakeLock.request('screen')
        _wakeLock = { type: 'wakelock', lock }
        lock.addEventListener?.('release', () => {
          if (_wakeLock?.lock === lock) _wakeLock = null
        })
        return true
      } catch {
        /* denied / unsupported */
      }
    }
  } catch (e) {
    console.warn('[native] keepAwake', reason, e)
  }
  return false
}

export async function releaseKeepAwake() {
  _wakeHolders = Math.max(0, _wakeHolders - 1)
  if (_wakeHolders > 0) return
  const cur = _wakeLock
  _wakeLock = null
  if (!cur) return
  try {
    if (cur.type === 'capacitor') {
      // eslint-disable-next-line no-new-func
      const dynImport = new Function('m', 'return import(m)')
      const mod = await dynImport('@capacitor-community/keep-awake').catch(() => null)
      await mod?.KeepAwake?.allowSleep?.()
    } else if (cur.type === 'wakelock' && cur.lock) {
      await cur.lock.release?.()
    }
  } catch { /* ignore */ }
}

/** Force allow sleep (e.g. leave chat page). */
export async function forceAllowSleep() {
  _wakeHolders = 0
  await releaseKeepAwake()
}

/** Heavy — destructive / important */
export function hapticHeavy() {
  return impact('Heavy')
}

export function hapticSuccess() {
  return notificationHaptic('SUCCESS')
}

export function hapticWarning() {
  return notificationHaptic('WARNING')
}

export function hapticError() {
  return notificationHaptic('ERROR')
}

export function hapticSelect() {
  return selectionChanged()
}

// ─── Local notifications ───────────────────────────────────────────────────

export async function notifyLocal({ title, body, id, extra } = {}) {
  if (!_native || !_notifEnabled) return { ok: false, reason: 'disabled' }
  try {
    const { LocalNotifications } = await import('@capacitor/local-notifications')
    const perm = await LocalNotifications.checkPermissions()
    if (perm.display !== 'granted') {
      const req = await LocalNotifications.requestPermissions()
      if (req.display !== 'granted') return { ok: false, reason: 'denied' }
    }
    const nid = id || Math.floor(Date.now() % 2_000_000_000)
    await LocalNotifications.schedule({
      notifications: [
        {
          id: nid,
          title: title || 'AI Assistant',
          body: body || '',
          extra: extra || {},
          schedule: { at: new Date(Date.now() + 250) },
        },
      ],
    })
    return { ok: true, id: nid }
  } catch (e) {
    console.warn('[native] local notify', e)
    return { ok: false, reason: String(e) }
  }
}

// ─── Push registration ─────────────────────────────────────────────────────

let _lastToken = null
let _registerApi = null

/** Call after login with (token) => api POST helper */
export function setPushRegisterHandler(fn) {
  _registerApi = fn
  if (_lastToken && fn) {
    try { fn(_lastToken) } catch { /* ignore */ }
  }
}

export async function registerPush() {
  if (!_native || !_notifEnabled) return { ok: false }
  try {
    const { PushNotifications } = await import('@capacitor/push-notifications')
    const { LocalNotifications } = await import('@capacitor/local-notifications')

    // Local first (always useful)
    try {
      let lp = await LocalNotifications.checkPermissions()
      if (lp.display !== 'granted') lp = await LocalNotifications.requestPermissions()
    } catch { /* ignore */ }

    let perm = await PushNotifications.checkPermissions()
    if (perm.receive !== 'granted') {
      perm = await PushNotifications.requestPermissions()
    }
    if (perm.receive !== 'granted') {
      return { ok: false, reason: 'push_denied' }
    }

    if (!_pushReady) {
      await PushNotifications.addListener('registration', (token) => {
        _lastToken = token?.value || token
        console.info('[native] push token', String(_lastToken).slice(0, 16) + '…')
        if (_registerApi && _lastToken) {
          try { _registerApi(_lastToken) } catch { /* ignore */ }
        }
      })
      await PushNotifications.addListener('registrationError', (err) => {
        console.warn('[native] push registration error', err)
      })
      await PushNotifications.addListener('pushNotificationReceived', (notification) => {
        // Foreground: light haptic + optional local mirror
        hapticLight()
        const t = notification?.title || notification?.data?.title
        const b = notification?.body || notification?.data?.body
        if (t || b) {
          notifyLocal({ title: t || 'AI Assistant', body: b || '' })
        }
      })
      await PushNotifications.addListener('pushNotificationActionPerformed', (action) => {
        hapticMedium()
        const data = action?.notification?.data || {}
        let path = data.path || data.url || data.link || data.route || data.click_action
        if (path && typeof path === 'string') {
          // Absolute URL → same-origin app path under /agents
          try {
            if (path.startsWith('http://') || path.startsWith('https://')) {
              const u = new URL(path)
              path = u.pathname + (u.search || '') + (u.hash || '')
            }
          } catch { /* keep path */ }
          // Strip /agents prefix for in-app router
          if (path.startsWith('/agents/')) path = path.slice('/agents'.length) || '/'
          else if (path === '/agents') path = '/'
          if (path.startsWith('#')) window.location.hash = path
          else if (path.startsWith('/')) {
            // BrowserRouter base is /agents/
            const base = (import.meta.env.BASE_URL || '/agents/').replace(/\/+$/, '') || '/agents'
            window.location.href = `${base}${path.startsWith('/') ? path : `/${path}`}`
          }
        }
      })
      _pushReady = true
    }

    await PushNotifications.register()
    return { ok: true }
  } catch (e) {
    console.warn('[native] push setup', e)
    return { ok: false, reason: String(e) }
  }
}

export function getPushToken() {
  return _lastToken
}

// ─── Bootstrap ─────────────────────────────────────────────────────────────

export async function initNativeShell() {
  try {
    const cap = window.Capacitor
    if (!cap?.isNativePlatform?.()) {
      _native = false
      _platform = 'web'
      return { native: false }
    }

    _native = true
    _platform = cap.getPlatform?.() || 'unknown'
    await loadPrefs()

    // CSS hooks for safe-area / full-viewport mobile shell (store builds)
    try {
      document.documentElement.classList.add('capacitor-native', `plt-${_platform}`)
      document.body.classList.add('capacitor-native', `plt-${_platform}`)
      document.querySelector('.aba-shell')?.classList.add('capacitor-ready')
    } catch { /* ignore */ }

    const [{ StatusBar, Style }, { SplashScreen }, { App }, { Keyboard }] = await Promise.all([
      import('@capacitor/status-bar'),
      import('@capacitor/splash-screen'),
      import('@capacitor/app'),
      import('@capacitor/keyboard'),
    ])

    try {
      await StatusBar.setStyle({ style: Style.Dark })
      if (_platform === 'android') {
        await StatusBar.setBackgroundColor({ color: '#0b1f3a' })
        try {
          await StatusBar.setOverlaysWebView({ overlay: false })
        } catch { /* older plugin */ }
      }
    } catch { /* simulator */ }

    try {
      await SplashScreen.hide()
    } catch { /* ignore */ }

    App.addListener('backButton', ({ canGoBack }) => {
      hapticLight()
      if (canGoBack || window.history.length > 1) {
        window.history.back()
      } else {
        App.exitApp()
      }
    })

    App.addListener('appStateChange', ({ isActive }) => {
      if (isActive && _notifEnabled) {
        // re-register quietly when returning to foreground
        registerPush().catch(() => {})
      }
    })

    Keyboard.addListener('keyboardWillShow', () => {
      document.documentElement.classList.add('keyboard-open')
    })
    Keyboard.addListener('keyboardWillHide', () => {
      document.documentElement.classList.remove('keyboard-open')
    })

    document.documentElement.classList.add('is-native', `is-${_platform}`)

    // Don't block boot on push permission dialog
    setTimeout(() => {
      if (_notifEnabled) registerPush().catch(() => {})
    }, 800)

    return { native: true, platform: _platform }
  } catch (err) {
    console.warn('[native] init skipped', err)
    return { native: false, error: String(err) }
  }
}
