/**
 * Wire push token registration after auth + helpers for screens.
 */
import { useEffect } from 'react'
import { api, getToken, IS_NATIVE } from '../api'
import {
  isNative,
  getNativePlatform,
  setPushRegisterHandler,
  registerPush,
  hapticLight,
  hapticMedium,
  hapticSuccess,
  hapticError,
  hapticSelect,
  notifyLocal,
  getNotificationsEnabled,
} from '../native'

export function usePushRegistration() {
  useEffect(() => {
    if (!isNative() || !getToken()) return

    setPushRegisterHandler(async (token) => {
      if (!token) return
      try {
        await api('/devices/push/register', {
          method: 'POST',
          body: {
            token: String(token),
            platform: getNativePlatform(),
            device_label: `${getNativePlatform()} device`,
            enabled: true,
          },
        })
      } catch (e) {
        console.warn('[push] register failed', e)
      }
    })

    registerPush().catch(() => {})
  }, [])
}

export function useNativeFeedback() {
  return {
    isNative: isNative() || IS_NATIVE,
    platform: getNativePlatform(),
    light: hapticLight,
    medium: hapticMedium,
    success: hapticSuccess,
    error: hapticError,
    select: hapticSelect,
    notify: async (title, body, extra) => {
      if (!getNotificationsEnabled()) return
      return notifyLocal({ title, body, extra })
    },
  }
}
