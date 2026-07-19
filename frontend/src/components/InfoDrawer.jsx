import React from 'react'
import { Drawer, Button, Space, Typography, Divider } from 'antd'
import { CloseOutlined } from '@ant-design/icons'

const { Title, Paragraph, Text } = Typography

/**
 * Full-width mobile-friendly information panel (Drawer).
 * Use for cards/list rows that should open detail boxes on tap.
 */
export default function InfoDrawer({
  open,
  onClose,
  title,
  subtitle,
  children,
  extra,
  footer,
  width,
  placement = 'bottom',
}) {
  // Bottom sheet on narrow viewports; right drawer on desktop
  const isMobile = typeof window !== 'undefined' && window.innerWidth <= 768
  const place = isMobile ? 'bottom' : (placement === 'bottom' ? 'right' : placement)
  const w = isMobile ? '100%' : (width || 420)
  const h = isMobile ? '88%' : undefined

  return (
    <Drawer
      open={!!open}
      onClose={onClose}
      title={null}
      placement={place}
      width={w}
      height={h}
      destroyOnClose
      className="aba-info-drawer"
      styles={{
        body: { paddingTop: 8, paddingBottom: 24 },
        header: { display: 'none' },
      }}
      closeIcon={null}
    >
      <div className="aba-info-drawer-head">
        <div className="aba-info-drawer-titles">
          {title != null && (
            <Title level={4} className="aba-info-drawer-title">
              {title}
            </Title>
          )}
          {subtitle ? (
            <Text type="secondary" className="aba-info-drawer-sub">
              {subtitle}
            </Text>
          ) : null}
        </div>
        <Space size={8} wrap className="aba-info-drawer-actions">
          {extra}
          <Button
            type="text"
            icon={<CloseOutlined />}
            onClick={onClose}
            aria-label="Close"
            className="aba-touch-btn"
          />
        </Space>
      </div>
      <Divider style={{ margin: '12px 0 16px' }} />
      <div className="aba-info-drawer-body">{children}</div>
      {footer != null && (
        <>
          <Divider style={{ margin: '16px 0 12px' }} />
          <div className="aba-info-drawer-footer">{footer}</div>
        </>
      )}
    </Drawer>
  )
}

/** Simple centered empty/info state inside a Card */
export function InfoEmpty({ title, description, action }) {
  return (
    <div className="aba-info-empty">
      {title && <Title level={5} style={{ marginBottom: 8 }}>{title}</Title>}
      {description && (
        <Paragraph type="secondary" style={{ marginBottom: action ? 16 : 0, maxWidth: 360 }}>
          {description}
        </Paragraph>
      )}
      {action}
    </div>
  )
}
