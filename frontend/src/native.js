/**
 * Capacitor native shell bootstrap (safe no-ops on web).
 */
export async function initNativeShell() {
  try {
    const cap = window.Capacitor
    if (!cap?.isNativePlatform?.()) return { native: false }

    const platform = cap.getPlatform?.() || 'unknown'

    // Dynamic imports so web bundle stays light if tree-shaken
    const [{ StatusBar, Style }, { SplashScreen }, { App }, { Keyboard }] = await Promise.all([
      import('@capacitor/status-bar'),
      import('@capacitor/splash-screen'),
      import('@capacitor/app'),
      import('@capacitor/keyboard'),
    ])

    try {
      await StatusBar.setStyle({ style: Style.Dark })
      if (platform === 'android') {
        await StatusBar.setBackgroundColor({ color: '#0b1f3a' })
      }
    } catch {
      /* StatusBar not available on all simulators */
    }

    try {
      await SplashScreen.hide()
    } catch {
      /* ignore */
    }

    // Hardware back button → history back, else exit only on root
    App.addListener('backButton', ({ canGoBack }) => {
      if (canGoBack || window.history.length > 1) {
        window.history.back()
      } else {
        App.exitApp()
      }
    })

    // Avoid layout jumps when keyboard opens
    Keyboard.addListener('keyboardWillShow', () => {
      document.documentElement.classList.add('keyboard-open')
    })
    Keyboard.addListener('keyboardWillHide', () => {
      document.documentElement.classList.remove('keyboard-open')
    })

    document.documentElement.classList.add('is-native', `is-${platform}`)
    return { native: true, platform }
  } catch (err) {
    console.warn('[native] init skipped', err)
    return { native: false, error: String(err) }
  }
}
