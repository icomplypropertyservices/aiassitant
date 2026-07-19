import React from 'react'
import {
  DashboardOutlined,
  MessageOutlined,
  RobotOutlined,
  AppstoreOutlined,
  BarChartOutlined,
  CreditCardOutlined,
  SettingOutlined,
  CrownOutlined,
  ApartmentOutlined,
  CheckSquareOutlined,
  ClusterOutlined,
  BookOutlined,
  UserOutlined,
  ThunderboltOutlined,
  ShopOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  GlobalOutlined,
  CommentOutlined,
  PhoneOutlined,
  AppstoreAddOutlined,
  MenuOutlined,
} from '@ant-design/icons'

const MAP = {
  home: <DashboardOutlined />,
  agents: <RobotOutlined />,
  tasks: <CheckSquareOutlined />,
  business: <ShopOutlined />,
  more: <MenuOutlined />,
  meetings: <CommentOutlined />,
  comms: <PhoneOutlined />,
  ops: <ThunderboltOutlined />,
  chat: <MessageOutlined />,
  workspace: <ApartmentOutlined />,
  hierarchy: <ClusterOutlined />,
  team: <TeamOutlined />,
  permissions: <SafetyCertificateOutlined />,
  templates: <AppstoreOutlined />,
  training: <BookOutlined />,
  analytics: <BarChartOutlined />,
  billing: <CreditCardOutlined />,
  bay: <GlobalOutlined />,
  profile: <UserOutlined />,
  settings: <SettingOutlined />,
  admin: <CrownOutlined />,
  explore: <AppstoreAddOutlined />,
}

export function navIcon(name) {
  return MAP[name] || <AppstoreOutlined />
}

export default navIcon
