/**
 * Native (iOS/Android Capacitor) subscription + top-up billing helpers.
 *
 * Strategy (multi-platform SaaS, store-safe):
 *  1. Free trial activates via API inside the app.
 *  2. Paid plans / top-ups open Stripe Checkout in the system browser
 *     (SFSafariViewController / Chrome Custom Tabs) via @capacitor/browser.
 *  3. After payment, deep link or app resume refreshes /auth/me + meter.
 *  4. Product IDs below map to App Store / Play Console for optional IAP later.
 *
 * Custom scheme: aiba://billing/success|cancel
 * HTTPS app link: https://aibusinessagent.xyz/agents/billing?checkout=...
 */

import { api, getToken, setAuth, IS_NATIVE } from './api'
import { absoluteAppUrl } from './publicPaths'

/** App Store / Play product IDs — create matching products in each console. */
export const STORE_PRODUCTS = {
  starter_month: {
    plan: 'starter',
    interval: 'month',
    apple: 'com.icomply.aibusinessassistant.starter.month',
    google: 'starter_month',
    label: 'Starter monthly',
  },
  starter_year: {
    plan: 'starter',
    interval: 'year',
    apple: 'com.icomply.aibusinessassistant.starter.year',
    google: 'starter_year',
    label: 'Starter annual',
  },
  pro_month: {
    plan: 'pro',
    interval: 'month',
    apple: 'com.icomply.aibusinessassistant.pro.month',
    google: 'pro_month',
    label: 'Pro monthly',
  },
  pro_year: {
    plan: 'pro',
    interval: 'year',
    apple: 'com.icomply.aibusinessassistant.pro.year',
    google: 'pro_year',
    label: 'Pro annual',
  },
  business_month: {
    plan: 'business',
    interval: 'month',
    apple: 'com.icomply.aibusinessassistant.business.month',
    google: 'business_month',
    label: 'Business monthly',
  },
  business_year: {
    plan: 'business',
    interval: 'year',
    apple: 'com.icomply.aibusinessassistant.business.year',
    google: 'business_year',
    label: 'Business annual',
  },
  credits_10: {
    kind: 'topup',
    amount: 10,
    apple: 'com.icomply.aibusinessassistant.credits.10',
    google: 'credits_10',
    label: '$10 credits',
  },
  credits_25: {
    kind: 'topup',
    amount: 25,
    apple: 'com.icomply.aibusinessassistant.credits.25',
    google: 'credits_25',
    label: '$25 credits',
  },
  credits_50: {
    kind: 'topup',
    amount: 50,
    apple: 'com.icomply.aibusinessassistant.credits.50',
    google: 'credits_50',
    label: '$50 credits',
  },
}

export function storeProductKey(plan, interval = 'month') {
  const p = String(plan || '').toLowerCase()
  const iv = interval === 'year' || interval === 'annual' ? 'year' : 'month'
  return `${p}_${iv}`
}

export function getStoreProduct(plan, interval = 'month') {
  return STORE_PRODUCTS[storeProductKey(plan, interval)] || null
}

async function getBrowser() {
  try {
    const mod = await import('@capacitor/browser')
    return mod.Browser
  } catch {
    return null
  }
}

async function getAppPlugin() {
  try {
    const mod = await import('@capacitor/app')
    return mod.App
  } catch {
    return null
  }
}

/** Open a URL in the system in-app browser (preferred on native). */
export async function openNativeBrowser(url, { toolbarColor = '#0b1f3a' } = {}) {
  if (!url) throw new Error('No checkout URL')
  if (!IS_NATIVE) {
    window.location.href = url
    return { mode: 'web' }
  }
  const Browser = await getBrowser()
  if (Browser?.open) {
    await Browser.open({
      url,
      presentationStyle: 'popover',
      toolbarColor,
    })
    return { mode: 'browser' }
  }
  window.open(url, '_blank')
  return { mode: 'window' }
}

export async function closeNativeBrowser() {
  try {
    const Browser = await getBrowser()
    if (Browser?.close) await Browser.close()
  } catch {
    /* ignore */
  }
}

/**
 * Start a paid plan subscription from the native app.
 * Free trial still uses the API directly (caller handles trial).
 */
export async function startNativePlanCheckout({
  plan,
  interval = 'month',
  company_name,
} = {}) {
  const r = await api('/billing/plan', {
    method: 'POST',
    body: {
      plan,
      interval,
      company_name: company_name || undefined,
      platform: IS_NATIVE ? (window.Capacitor?.getPlatform?.() || 'native') : 'web',
      client: 'mobile',
    },
  })
  if (r.checkout_url) {
    await openNativeBrowser(r.checkout_url)
    return { ...r, opened: true }
  }
  return { ...r, opened: false }
}

/** Wallet top-up via Stripe Checkout in system browser. */
export async function startNativeTopupCheckout(amount) {
  const r = await api('/billing/topup', {
    method: 'POST',
    body: {
      amount: Number(amount),
      platform: IS_NATIVE ? (window.Capacitor?.getPlatform?.() || 'native') : 'web',
      client: 'mobile',
    },
  })
  if (r.checkout_url) {
    await openNativeBrowser(r.checkout_url)
    return { ...r, opened: true }
  }
  return { ...r, opened: false }
}

/** Open Customer Portal / manage subscription on web for store compliance options. */
export async function openNativeManageBilling() {
  try {
    const r = await api('/billing/portal', { method: 'POST', body: {} })
    if (r?.url) {
      await openNativeBrowser(r.url)
      return true
    }
  } catch {
    /* fall through */
  }
  await openNativeBrowser(absoluteAppUrl('/billing'))
  return false
}

/**
 * After Stripe redirect / app resume: refresh session + optional checkout confirm.
 */
export async function refreshAfterCheckout({ sessionId } = {}) {
  try {
    if (sessionId) {
      await api('/billing/checkout/confirm', {
        method: 'POST',
        body: { session_id: sessionId },
      }).catch(() => null)
    }
  } catch {
    /* webhook may already have applied */
  }
  try {
    const me = await api('/auth/me')
    if (me && getToken()) setAuth(getToken(), me)
    return me
  } catch {
    return null
  }
}

function parseBillingDeepLink(url) {
  if (!url || typeof url !== 'string') return null
  try {
    // aiba://billing/success?session_id=...
    // https://aibusinessagent.xyz/agents/billing?checkout=success&session_id=...
    const lower = url.toLowerCase()
    const isOurs =
      lower.startsWith('aiba://') ||
      lower.includes('aibusinessagent.xyz') ||
      lower.includes('/billing') ||
      lower.includes('checkout=')
    if (!isOurs) return null

    let checkout = null
    let sessionId = null
    try {
      const u = new URL(url.replace(/^aiba:\/\//i, 'https://aiba.local/'))
      checkout = u.searchParams.get('checkout')
      sessionId = u.searchParams.get('session_id') || u.searchParams.get('sessionId')
      const path = (u.pathname || '').toLowerCase()
      if (!checkout) {
        if (path.includes('success')) checkout = 'success'
        if (path.includes('cancel')) checkout = 'cancelled'
      }
    } catch {
      if (/success/i.test(url)) checkout = 'success'
      if (/cancel/i.test(url)) checkout = 'cancelled'
      const m = url.match(/session_id=([^&]+)/i)
      if (m) sessionId = decodeURIComponent(m[1])
    }
    return { checkout, sessionId, raw: url }
  } catch {
    return null
  }
}

let _billingListenerReady = false

/**
 * Call once from app shell on native: listen for return from Stripe browser.
 * onResult({ checkout, sessionId, me })
 */
export function installNativeBillingListeners(onResult) {
  if (!IS_NATIVE || _billingListenerReady) return () => {}
  _billingListenerReady = true
  const unsubs = []

  ;(async () => {
    try {
      const App = await getAppPlugin()
      if (!App) return

      const handleUrl = async (url) => {
        const parsed = parseBillingDeepLink(url)
        if (!parsed) return
        await closeNativeBrowser()
        const me = await refreshAfterCheckout({ sessionId: parsed.sessionId })
        onResult?.({ ...parsed, me })
      }

      const sub = await App.addListener('appUrlOpen', (ev) => {
        handleUrl(ev?.url || '')
      })
      unsubs.push(() => sub?.remove?.())

      // Cold start with deep link
      try {
        const launch = await App.getLaunchUrl?.()
        if (launch?.url) handleUrl(launch.url)
      } catch {
        /* ignore */
      }

      // Resume after browser checkout (user closed tab without deep link)
      const resSub = await App.addListener('appStateChange', ({ isActive }) => {
        if (isActive) {
          refreshAfterCheckout({}).then((me) => {
            if (me) onResult?.({ checkout: 'resume', sessionId: null, me })
          })
        }
      })
      unsubs.push(() => resSub?.remove?.())
    } catch (e) {
      console.warn('native billing listeners', e)
    }
  })()

  return () => {
    _billingListenerReady = false
    unsubs.forEach((fn) => {
      try {
        fn()
      } catch {
        /* ignore */
      }
    })
  }
}
