import React from 'react'
import { Button, Space, Typography } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'

const { Title, Text } = Typography

/**
 * Consistent page title + optional subtitle + right-aligned actions.
 * Designed for the centered / boxed shell (aba-page-shell).
 *
 * @param {boolean} [showBack=false] — in-page back (AppLayout already has global header back)
 * @param {string|function} [backTo] — path string or custom handler when showBack is true
 */
export default function PageHeader({
  title,
  subtitle,
  extra,
  style,
  className = '',
  showBack = false,
  backTo,
}) {
  const nav = useNavigate()
  const loc = useLocation()

  const handleBack = () => {
    if (typeof backTo === 'function') {
      backTo()
      return
    }
    if (typeof backTo === 'string' && backTo) {
      nav(backTo)
      return
    }
    if (loc.key && loc.key !== 'default') {
      nav(-1)
    } else {
      nav('/')
    }
  }

  return (
    <div className={`aba-page-header${className ? ` ${className}` : ''}`} style={style}>
      <div className="aba-page-header-text" style={{ display: 'flex', alignItems: 'flex-start', gap: 8, minWidth: 0, width: '100%' }}>
        {showBack ? (
          <Button
            type="text"
            className="aba-touch-btn"
            icon={<ArrowLeftOutlined />}
            onClick={handleBack}
            aria-label="Go back"
            style={{ marginTop: 2, flexShrink: 0 }}
          />
        ) : null}
        <div style={{ minWidth: 0, flex: 1 }}>
          <Title level={3} className="aba-page-header-title">
            {title}
          </Title>
          {subtitle ? (
            <Text type="secondary" className="aba-page-header-subtitle">
              {subtitle}
            </Text>
          ) : null}
        </div>
      </div>
      {extra ? (
        <div className="aba-page-header-extra">
          <Space wrap size={[8, 8]} style={{ justifyContent: 'center', width: '100%' }}>
            {extra}
          </Space>
        </div>
      ) : null}
    </div>
  )
}
