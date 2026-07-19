import React from 'react'
import {
  Card, Button, Space, Tag, Input, Typography, Empty,
} from 'antd'
import { ThunderboltOutlined, MessageOutlined, SendOutlined } from '@ant-design/icons'
import VoiceControls from '../../components/VoiceControls'
import MediaActions from '../../components/MediaActions'
import MessageActions from '../../components/MessageActions'
import { PROMPTS } from './constants'

/** Agent manage page — Live chat tab body. */
export default function AgentChatTab({
  agent, messages, input, setInput, send, busy,
  speakReplies, setSpeakReplies, bottomRef,
}) {
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card
        bordered
        size="small"
        className="aba-soft-card"
        title={<Space size={8}><ThunderboltOutlined /><span>Quick prompts</span></Space>}
      >
        <Space wrap size={[6, 6]} style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space wrap size={[6, 6]}>
            {PROMPTS.map((p) => (
              <Button key={p} size="small" onClick={() => send(p)} disabled={busy}>{p}</Button>
            ))}
          </Space>
          <Space wrap size={[6, 6]}>
            <VoiceControls
              disabled={busy}
              onTranscript={(text) => send(text)}
              onPartial={(t) => setInput(t)}
              speakReplies={speakReplies}
              onSpeakRepliesChange={(v) => {
                setSpeakReplies(v)
                localStorage.setItem('voice_speak_replies', v ? '1' : '0')
              }}
            />
            <MediaActions disabled={busy} />
          </Space>
        </Space>
      </Card>

      <Card
        bordered
        size="small"
        className="aba-soft-card"
        title={(
          <Space size={8}>
            <MessageOutlined />
            <span>Messages</span>
            {messages.length > 0 && <Tag style={{ marginInlineStart: 4 }}>{messages.length}</Tag>}
          </Space>
        )}
        styles={{
          body: {
            padding: messages.length === 0 ? 24 : 12,
            minHeight: 280,
            maxHeight: 'min(50vh, 480px)',
            overflowY: 'auto',
          },
        }}
      >
        {messages.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={`Start a live conversation with ${agent.name}`}
          />
        ) : (
          messages.map((m, i) => (
            <div
              key={i}
              style={{
                display: 'flex',
                justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start',
                marginBottom: 8,
              }}
            >
              <div style={{ maxWidth: '75%', minWidth: 0 }}>
                <div style={{
                  padding: '8px 14px',
                  borderRadius: 12,
                  whiteSpace: 'pre-wrap',
                  background: m.role === 'user' ? '#1668dc' : '#fff',
                  color: m.role === 'user' ? '#fff' : 'var(--aba-ink, #000)',
                  border: m.role === 'user' ? 'none' : '1px solid var(--aba-border, #e8e8e8)',
                  opacity: m.streaming ? 0.95 : 1,
                }}
                >
                  {m.content || (m.streaming ? '…' : '')}
                </div>
                {m.role === 'assistant' && !m.streaming && m.content && (
                  <MessageActions
                    text={m.content}
                    filename={`${(agent?.name || 'agent').replace(/\s+/g, '-')}-reply`}
                  />
                )}
              </div>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </Card>

      <Card
        bordered
        size="small"
        className="aba-soft-card"
        title={<Space size={8}><SendOutlined /><span>Message {agent.name}</span></Space>}
        styles={{ body: { padding: '12px 16px' } }}
      >
        <Space.Compact style={{ width: '100%' }}>
          <Input
            size="large"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={() => send()}
            placeholder={`Message ${agent.name}… or use the mic to talk`}
            disabled={busy}
          />
          <Button size="large" type="primary" icon={<SendOutlined />} loading={busy} onClick={() => send()}>
            Send
          </Button>
        </Space.Compact>
        <Typography.Text type="secondary" style={{ fontSize: 11, marginTop: 8, display: 'block' }}>
          Prefer full chat? Use Talk in the header. Voice works best in Chrome/Edge.
        </Typography.Text>
      </Card>
    </Space>
  )
}
