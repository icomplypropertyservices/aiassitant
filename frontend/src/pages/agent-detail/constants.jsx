import React from 'react'
import {
  BulbOutlined, ThunderboltOutlined, MailOutlined, MessageOutlined,
  PhoneOutlined, CheckCircleOutlined, InfoCircleOutlined,
} from '@ant-design/icons'

export const ICONS = {
  thinking: <BulbOutlined style={{ color: '#faad14' }} />,
  action: <ThunderboltOutlined style={{ color: '#1668dc' }} />,
  email: <MailOutlined style={{ color: '#52c41a' }} />,
  sms: <MessageOutlined style={{ color: '#52c41a' }} />,
  call: <PhoneOutlined style={{ color: '#52c41a' }} />,
  done: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  info: <InfoCircleOutlined style={{ color: '#8c8c8c' }} />,
}

export const PROMPTS = [
  'Summarise what you can do for me',
  'Draft a professional follow-up email',
  'What tasks are you working on?',
  'Give me 3 next actions for this week',
]

export const STATUS_COLOR = {
  todo: 'default', queued: 'processing', in_progress: 'gold',
  review: 'purple', completed: 'success', failed: 'error',
}
