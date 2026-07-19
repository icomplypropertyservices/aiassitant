import React from 'react'

/**
 * Canonical product logo (public/logo.png — full art).
 * Use size="lg" on auth/splash; "md" header; "sm" chips.
 */
export function logoSrc(preferFull = true) {
  const base = import.meta.env.BASE_URL || '/'
  // logo.png is the full brand mark; logo-256 is a smaller export of the same art
  return `${base}${preferFull ? 'logo.png' : 'logo-256.png'}`
}

export default function BrandLogo({
  size = 'md',
  alt = 'AI Business Assistant',
  className = '',
  style,
  preferFull = true,
  rounded = true,
}) {
  const px = size === 'xl' ? 120
    : size === 'lg' ? 88
    : size === 'md' ? 48
    : size === 'sm' ? 36
    : typeof size === 'number' ? size : 48

  return (
    <img
      src={logoSrc(preferFull)}
      alt={alt}
      width={px}
      height={px}
      className={`aba-brand-logo${rounded ? ' is-rounded' : ''}${className ? ` ${className}` : ''}`}
      style={{
        width: px,
        height: px,
        objectFit: 'contain',
        display: 'block',
        ...style,
      }}
      decoding="async"
      // Full logo is larger; splash can preload; auth/home should load eagerly
      loading="eager"
      fetchPriority="high"
    />
  )
}

/** Full-screen / page loading state with brand logo */
export function LogoLoading({ tip = 'Loading…', minHeight = 280 }) {
  return (
    <div className="aba-logo-loading" style={{ minHeight }}>
      <div className="aba-logo-loading-mark">
        <BrandLogo size="xl" />
      </div>
      <div className="aba-logo-loading-tip">{tip}</div>
      <div className="aba-logo-loading-bar" aria-hidden="true" />
    </div>
  )
}
