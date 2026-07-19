import React from 'react'
import { Card, Col, Row, Typography, Tag, Space } from 'antd'
import {
  DashboardOutlined, MessageOutlined, RobotOutlined, AppstoreOutlined,
  BarChartOutlined, CreditCardOutlined, SettingOutlined, CrownOutlined,
  ApartmentOutlined, CheckSquareOutlined, ClusterOutlined, BookOutlined,
  UserOutlined, ThunderboltOutlined, ShopOutlined, SafetyCertificateOutlined,
  TeamOutlined, GlobalOutlined, CommentOutlined, RightOutlined, PhoneOutlined,
  HomeOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { getUser } from '../api'
import { goBay, goMarketing } from '../publicPaths'

/**
 * Every major surface of the product — single source of truth for
 * Dashboard “Explore”, mobile More drawer, and Settings hub.
 */
export function getSystemNavItems({ isAdmin = false } = {}) {
  const items = [
    { key: '/', icon: <DashboardOutlined />, title: 'Dashboard', blurb: 'Home overview & KPIs', group: 'Home' },
    { key: '/workspace', icon: <ApartmentOutlined />, title: 'Workspace', blurb: 'Companies, projects, tasks', group: 'Work' },
    { key: '/business', icon: <ShopOutlined />, title: 'Business CRM', blurb: 'Customers, deals, diary', group: 'Work' },
    { key: '/tasks', icon: <CheckSquareOutlined />, title: 'Tasks board', blurb: 'Kanban pipeline', group: 'Work' },
    { key: '/meetings', icon: <CommentOutlined />, title: 'Meetings', blurb: 'Rooms with agents & humans', group: 'Work' },
    { key: '/console', icon: <RobotOutlined />, title: 'Agent Console', blurb: 'Core Team, spawn, chat', group: 'Agents' },
    { key: '/comms', icon: <PhoneOutlined />, title: 'Calls · SMS · Email', blurb: 'Train pitches with humans', group: 'Agents' },
    { key: '/hierarchy', icon: <ClusterOutlined />, title: 'Hierarchy', blurb: 'Org tree & leads', group: 'Agents' },
    { key: '/templates', icon: <AppstoreOutlined />, title: 'Templates', blurb: 'Role packs to spawn from', group: 'Agents' },
    { key: '/training', icon: <BookOutlined />, title: 'Training', blurb: 'Knowledge library', group: 'Agents' },
    { key: '/ops', icon: <ThunderboltOutlined />, title: 'Live ops', blurb: 'Real-time agent actions', group: 'Agents' },
    { key: '/chat', icon: <MessageOutlined />, title: 'AI Chat', blurb: 'General assistant thread', group: 'Agents' },
    { key: '/humans', icon: <TeamOutlined />, title: 'Team / Humans', blurb: 'People & My Human', group: 'People' },
    { key: '/permissions', icon: <SafetyCertificateOutlined />, title: 'Permissions', blurb: 'Who can do what', group: 'People' },
    { key: '/profile', icon: <UserOutlined />, title: 'Your profile', blurb: 'Account details', group: 'Account' },
    { key: '/billing', icon: <CreditCardOutlined />, title: 'Billing', blurb: 'Plans, tokens, storage', group: 'Account' },
    { key: '/analytics', icon: <BarChartOutlined />, title: 'Analytics', blurb: 'Usage charts', group: 'Account' },
    { key: '/settings', icon: <SettingOutlined />, title: 'Settings', blurb: 'Keys, apps, mobile', group: 'Account' },
    { key: '__bay__', icon: <GlobalOutlined />, title: 'AgentBay', blurb: 'Marketplace at /bay', group: 'More', external: true },
    { key: '__site__', icon: <HomeOutlined />, title: 'Website', blurb: 'Marketing landing at /', group: 'More', external: true },
  ]
  if (isAdmin) {
    items.push({
      key: '/admin',
      icon: <CrownOutlined />,
      title: 'Staff Admin',
      blurb: 'Platform controls',
      group: 'More',
    })
  }
  return items
}

/**
 * Grid of clickable destination cards.
 * @param {{ compact?: boolean, groups?: boolean, onNavigate?: () => void, className?: string }} props
 */
export default function SystemNav({ compact = false, groups = true, onNavigate, className = '' }) {
  const nav = useNavigate()
  const user = getUser()
  const items = getSystemNavItems({ isAdmin: user?.role === 'admin' })

  const go = (item) => {
    if (item.key === '__bay__') {
      goBay('/browse')
      onNavigate?.()
      return
    }
    if (item.key === '__site__') {
      goMarketing('/')
      onNavigate?.()
      return
    }
    if (item.external && typeof item.key === 'string' && item.key.startsWith('http')) {
      window.location.href = item.key
      onNavigate?.()
      return
    }
    nav(item.key)
    onNavigate?.()
  }

  const byGroup = {}
  for (const it of items) {
    const g = it.group || 'More'
    if (!byGroup[g]) byGroup[g] = []
    byGroup[g].push(it)
  }
  const groupOrder = ['Home', 'Work', 'Agents', 'People', 'Account', 'More']

  const renderCard = (item) => (
    <Col
      key={item.key}
      xs={12}
      sm={compact ? 12 : 8}
      md={compact ? 8 : 6}
      lg={compact ? 6 : 4}
    >
      <Card
        size="small"
        hoverable
        className="aba-soft-card aba-card-clickable aba-system-nav-card"
        onClick={() => go(item)}
        styles={{ body: { padding: compact ? 12 : 14 } }}
      >
        <Space direction="vertical" size={6} style={{ width: '100%' }}>
          <Space>
            <span className="aba-system-nav-icon" aria-hidden>
              {item.icon}
            </span>
            <Typography.Text strong style={{ fontSize: compact ? 13 : 14 }}>
              {item.title}
            </Typography.Text>
          </Space>
          {!compact && (
            <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', lineHeight: 1.35 }}>
              {item.blurb}
            </Typography.Text>
          )}
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            Open <RightOutlined style={{ fontSize: 10 }} />
          </Typography.Text>
        </Space>
      </Card>
    </Col>
  )

  if (!groups) {
    return (
      <Row gutter={[12, 12]} className={className}>
        {items.map(renderCard)}
      </Row>
    )
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }} className={className}>
      {groupOrder.filter((g) => byGroup[g]?.length).map((g) => (
        <div key={g}>
          <Tag color="blue" style={{ marginBottom: 10 }}>{g}</Tag>
          <Row gutter={[12, 12]}>
            {byGroup[g].map(renderCard)}
          </Row>
        </div>
      ))}
    </Space>
  )
}
