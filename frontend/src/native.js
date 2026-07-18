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
        const path = data.path || data.url || data.route
        if (path && typeof path === 'string') {
          // HashRouter
          if (path.startsWith('#')) window.location.hash = path
          else if (path.startsWith('/')) window.location.hash = `#${path}`
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
