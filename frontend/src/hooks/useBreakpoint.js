import { useEffect, useState } from 'react'

/**
 * Mobile-first breakpoint hook.
 * Default assumption: phone. Desktop only after min-width match.
 *
 * Breakpoints (aligned with CSS tokens):
 * - phone:  < 768px  (default)
 * - tablet: 768–1023
 * - desktop: ≥ 1024  (sider + multi-column)
 */
export const BP = {
  tablet: 768,
  desktop: 1024,
}

function compute(width) {
  const w = width || (typeof window !== 'undefined' ? window.innerWidth : BP.desktop)
  return {
    width: w,
    isPhone: w < BP.tablet,
    isTablet: w >= BP.tablet && w < BP.desktop,
    isDesktop: w >= BP.desktop,
    /** Show permanent sider (desktop only) */
    showSider: w >= BP.desktop,
    /** Bottom tab bar (phone + tablet portrait-friendly) */
    showBottomNav: w < BP.desktop,
  }
}

export function useBreakpoint() {
  const [bp, setBp] = useState(() =>
    typeof window !== 'undefined' ? compute(window.innerWidth) : compute(BP.desktop),
  )

  useEffect(() => {
    if (typeof window === 'undefined') return undefined
    const mqDesktop = window.matchMedia(`(min-width: ${BP.desktop}px)`)
    const mqTablet = window.matchMedia(`(min-width: ${BP.tablet}px)`)
    const update = () => setBp(compute(window.innerWidth))
    update()
    // matchMedia + resize for orientation changes
    mqDesktop.addEventListener?.('change', update)
    mqTablet.addEventListener?.('change', update)
    window.addEventListener('resize', update, { passive: true })
    return () => {
      mqDesktop.removeEventListener?.('change', update)
      mqTablet.removeEventListener?.('change', update)
      window.removeEventListener('resize', update)
    }
  }, [])

  return bp
}

export default useBreakpoint
