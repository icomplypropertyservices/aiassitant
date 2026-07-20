import { useEffect, useRef, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, getUser, getToken, setAuth, connectAuthedWs } from '../../api'

const SNOOZE_KEY = 'topup_modal_snooze_until'
/** Sparse background poll when WS is quiet (was 25s). */
const METER_POLL_MS = 45000
/** Debounce window for WS/aba-usage → REST reconcile (was immediate every event). */
const METER_DEBOUNCE_MS = 3000
/** Skip poll if a fetch ran more recently than this. */
const METER_MIN_GAP_MS = 12000

function isSnoozed() {
  try {
    return Number(localStorage.getItem(SNOOZE_KEY) || 0) > Date.now()
  } catch {
    return false
  }
}

export function snoozeTopup(minutes = 45) {
  try {
    localStorage.setItem(SNOOZE_KEY, String(Date.now() + minutes * 60 * 1000))
  } catch { /* ignore */ }
}

/**
 * Shared session + billing meter for the app shell (mobile-first v2).
 */
export function useShellSession() {
  const nav = useNavigate()
  const [user, setUser] = useState(getUser())
  const [meter, setMeter] = useState(null)
  const [topupOpen, setTopupOpen] = useState(false)
  const autoTrigRef = useRef(false)
  const meterFetchTimer = useRef(null)
  const meterInflight = useRef(null)
  const lastMeterFetchAt = useRef(0)
  const maybeOpenTopupRef = useRef(null)

  const maybeOpenTopup = useCallback((m) => {
    const u = getUser()
    if (!m || u?.role === 'admin') return
    const pathNow = window.location.pathname || ''
    if (pathNow.includes('/billing') || pathNow.includes('/subscribe')) return
    // Empty fuel still allows browsing — only show promo modal (always dismissible)
    if (isSnoozed()) return
    if (m.needs_topup || m.hard_block || m.hard_block_soon || (m.warn && (m.credits || 0) < 10)) {
      setTopupOpen(true)
    }
    if (m.auto_topup?.should_trigger && m.auto_topup?.enabled && !autoTrigRef.current) {
      autoTrigRef.current = true
      api('/billing/auto-topup/trigger', { method: 'POST', body: {} })
        .then((r) => {
          if (r.checkout_url) {
            setTopupOpen(true)
            setMeter((prev) => (prev ? { ...prev, auto_checkout_url: r.checkout_url } : prev))
          } else if (r.dev_mode) {
            // One-off reconcile after dev auto-topup (not per usage tick)
            if (!getToken()) return
            api('/billing/meter').then(setMeter).catch(() => {})
          }
        })
        .catch(() => {})
    }
  }, [])

  maybeOpenTopupRef.current = maybeOpenTopup

  // Coalesce meter REST calls: WS events used to fire /billing/meter on every token tick.
  const fetchMeter = useCallback(() => {
    if (!getToken()) return Promise.resolve(null)
    if (meterInflight.current) return meterInflight.current
    lastMeterFetchAt.current = Date.now()
    meterInflight.current = api('/billing/meter')
      .then((full) => {
        setMeter(full)
        maybeOpenTopupRef.current?.(full)
        return full
      })
      .catch(() => null)
      .finally(() => {
        meterInflight.current = null
      })
    return meterInflight.current
  }, [])

  const scheduleMeterRefresh = useCallback((delayMs = METER_DEBOUNCE_MS) => {
    if (meterFetchTimer.current) clearTimeout(meterFetchTimer.current)
    meterFetchTimer.current = setTimeout(() => {
      meterFetchTimer.current = null
      fetchMeter()
    }, delayMs)
  }, [fetchMeter])

  useEffect(() => {
    api('/auth/me')
      .then((me) => {
        setUser(me)
        setAuth(getToken(), me)
        if (me.meter) {
          setMeter(me.meter)
          maybeOpenTopup(me.meter)
        } else {
          fetchMeter()
        }
        if (me.needs_subscription) nav('/subscribe', { replace: true })
      })
      .catch(() => {
        fetchMeter()
      })

    const applyUsage = (m) => {
      if (!m) return
      // Prefer authoritative meter snapshot from server (task_runner / chat)
      if (m.meter && typeof m.meter === 'object' && m.meter.tokens_used_period != null) {
        setMeter((prev) => {
          const next = { ...(prev || {}), ...m.meter }
          setTimeout(() => maybeOpenTopup(next), 0)
          return next
        })
        // Debounced reconcile only — do not double-fetch on every WS usage event
        scheduleMeterRefresh(METER_DEBOUNCE_MS)
        return
      }
      setMeter((prev) => {
        if (!prev && m.meter) {
          setTimeout(() => maybeOpenTopup(m.meter), 0)
          scheduleMeterRefresh(METER_DEBOUNCE_MS)
          return m.meter
        }
        if (!prev) {
          // No prior meter — one coalesced fetch (not per-event)
          scheduleMeterRefresh(0)
          return prev
        }
        const used =
          m.tokens_used_period != null
            ? Number(m.tokens_used_period)
            : (prev.tokens_used_period || 0) + (Number(m.tokens) || 0)
        const included = Number(prev.tokens_included || 0)
        const usage_percent = included ? Math.min(100, (used / included) * 100) : 0
        const next = {
          ...prev,
          ...(m.meter || {}),
          tokens_used_period: used,
          tokens_remaining_included: Math.max(0, included - used),
          credits: m.credits != null ? m.credits : (m.meter?.credits ?? prev.credits),
          usage_percent: m.meter?.usage_percent ?? usage_percent,
          warn: m.meter?.warn != null ? m.meter.warn : usage_percent >= 80 && usage_percent < 100,
          hard_block: m.meter?.hard_block != null ? m.meter.hard_block : usage_percent >= 100,
          hard_block_soon:
            m.meter?.hard_block_soon != null ? m.meter.hard_block_soon : usage_percent >= 95,
          needs_topup: m.meter?.needs_topup ?? prev.needs_topup,
          urgency: m.meter?.urgency ?? prev.urgency,
          headline: m.meter?.headline ?? prev.headline,
          sales_message: m.meter?.sales_message ?? prev.sales_message,
          cta: m.meter?.cta ?? prev.cta,
          auto_topup: m.meter?.auto_topup || prev.auto_topup,
        }
        setTimeout(() => maybeOpenTopup(next), 0)
        return next
      })
      // Debounced server reconcile instead of immediate fetch on every usage tick
      if (m.tokens || m.meter || m.tokens_used_period != null) {
        scheduleMeterRefresh(METER_DEBOUNCE_MS)
      }
    }

    const onAbaUsage = (ev) => applyUsage(ev.detail || {})
    window.addEventListener('aba-usage', onAbaUsage)

    // Live token meter in all environments (chat + background autonomy when connected)
    let ws
    try {
      ws = connectAuthedWs('/billing/ws/tokens')
      ws.onmessage = (e) => {
        try {
          const m = JSON.parse(e.data)
          if (m.type === 'auth_ok') return
          if (m.event === 'usage' || m.tokens != null || m.meter || m.tokens_used_period != null) {
            applyUsage(m)
          }
        } catch { /* ignore */ }
      }
    } catch { /* ignore */ }

    // Sparse poll so background agent runs update the header if WS drops.
    const poll = setInterval(() => {
      if (!getToken()) return
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
      // Skip if we just reconciled via WS debounce or focus
      if (Date.now() - lastMeterFetchAt.current < METER_MIN_GAP_MS) return
      fetchMeter()
    }, METER_POLL_MS)

    // Refresh when user returns after agents ran offline (coalesced)
    const onFocus = () => {
      if (!getToken()) return
      if (Date.now() - lastMeterFetchAt.current < 5000) return
      fetchMeter()
    }
    window.addEventListener('focus', onFocus)
    const onVisibility = () => {
      if (document.visibilityState === 'visible') onFocus()
    }
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      window.removeEventListener('aba-usage', onAbaUsage)
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVisibility)
      clearInterval(poll)
      if (meterFetchTimer.current) clearTimeout(meterFetchTimer.current)
      try {
        ws?.close()
      } catch { /* ignore */ }
    }
  }, [nav, maybeOpenTopup, fetchMeter, scheduleMeterRefresh])

  return {
    user,
    setUser,
    meter,
    setMeter,
    topupOpen,
    setTopupOpen,
    maybeOpenTopup,
  }
}

export default useShellSession
