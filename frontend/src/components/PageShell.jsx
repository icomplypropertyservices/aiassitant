import React from 'react'
import { Flex } from 'antd'
import PageHeader from './PageHeader'

/**
 * Page-level container for the centered / boxed app shell.
 *
 * AppLayout already wraps every protected route in:
 *   .aba-page-center > .aba-page-shell (max-width 1120, centered) > <Outlet />
 *
 * PageShell adds the inner column + optional header / width / box surface:
 *   .aba-page-shell-inner[.is-wide|.is-narrow] > [PageHeader] > [.aba-box] > children
 *
 * Prefer Ant Design Card / Space / Flex for page body content.
 *
 * @param {object} props
 * @param {React.ReactNode} props.children
 * @param {boolean} [props.wide=false] — expand outer shell to ~1480 (tasks / chat tools)
 * @param {boolean} [props.narrow=false] — ~720px centered form column
 * @param {React.ReactNode} [props.title] — optional PageHeader title
 * @param {React.ReactNode} [props.subtitle]
 * @param {React.ReactNode} [props.extra] — right-side header actions
 * @param {boolean} [props.showBack=false] — PageHeader back (global AppLayout back is always on)
 * @param {string|function} [props.backTo]
 * @param {boolean} [props.boxed=false] — wrap children in .aba-box
 * @param {boolean} [props.boxedLg=false] — wrap children in .aba-box-lg
 * @param {number|string} [props.gap] — vertical gap between header and body (Flex gap)
 * @param {string} [props.className]
 * @param {React.CSSProperties} [props.style]
 * @param {React.CSSProperties} [props.headerStyle]
 * @param {string} [props.id]
 */
export default function PageShell({
  children,
  wide = false,
  narrow = false,
  title,
  subtitle,
  extra,
  showBack = false,
  backTo,
  boxed = false,
  boxedLg = false,
  gap,
  className = '',
  style,
  headerStyle,
  id,
}) {
  const classes = [
    'aba-page-shell-inner',
    wide ? 'is-wide' : '',
    narrow ? 'is-narrow' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  const showHeader = title != null || subtitle != null || extra != null || showBack

  let body = children
  if (boxedLg) {
    body = <div className="aba-box-lg">{children}</div>
  } else if (boxed) {
    body = <div className="aba-box">{children}</div>
  }

  // Prefer CSS --aba-shell-stack-gap on .aba-page-shell-inner; prop overrides when set
  const flexProps = gap != null ? { gap } : {}

  return (
    <Flex
      id={id}
      vertical
      className={classes}
      style={{
        width: '100%',
        maxWidth: '100%',
        minWidth: 0,
        boxSizing: 'border-box',
        ...style,
      }}
      {...flexProps}
      data-aba-layout="page-shell-inner"
      data-wide={wide ? 'true' : undefined}
      data-narrow={narrow ? 'true' : undefined}
    >
      {showHeader ? (
        <PageHeader
          title={title}
          subtitle={subtitle}
          extra={extra}
          showBack={showBack}
          backTo={backTo}
          style={headerStyle}
        />
      ) : null}
      {/*
        Wrap loose children so mobile always stacks full-width Ant Design blocks.
        Single child (typical Card/Space) stays as-is.
      */}
      {Array.isArray(body)
        ? body.map((child, i) => (
            <div key={child?.key ?? i} className="aba-shell-block" style={{ width: '100%', minWidth: 0 }}>
              {child}
            </div>
          ))
        : body}
    </Flex>
  )
}

/**
 * Soft surface box for grouping sections without a full page shell.
 * Prefer Ant Design Card for primary content; use PageBox for kanban strips, etc.
 */
export function PageBox({ children, large = false, className = '', style, ...rest }) {
  const cls = [
    large ? 'aba-box-lg' : 'aba-box',
    className,
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <div className={cls} style={style} {...rest}>
      {children}
    </div>
  )
}
