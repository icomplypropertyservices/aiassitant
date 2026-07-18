import React, { useState } from 'react'
import { Button, Modal, Input, Space, Image, Typography, message, Spin } from 'antd'
import { PictureOutlined, VideoCameraOutlined } from '@ant-design/icons'
import { api } from '../api'

/**
 * Image + Video generation (billed on token meter every time).
 */
export default function MediaActions({ disabled, onUsage, onAsset }) {
  const [open, setOpen] = useState(null) // 'image' | 'video' | null
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  const run = async () => {
    const p = prompt.trim()
    if (p.length < 3) return message.warning('Enter a prompt')
    setBusy(true)
    setResult(null)
    try {
      const path = open === 'video' ? '/media/video' : '/media/image'
      const data = await api(path, { method: 'POST', body: { prompt: p } })
      setResult(data)
      onUsage?.(data.usage || data.meter)
      onAsset?.(data)
      message.success(open === 'video' ? 'Video job billed & poster ready' : 'Image generated (tokens used)')
    } catch (e) {
      message.error(e.message || 'Media generation failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Space wrap size={4}>
        <Button
          size="small"
          icon={<PictureOutlined />}
          disabled={disabled}
          onClick={() => { setOpen('image'); setResult(null); setPrompt('') }}
        >
          Image
        </Button>
        <Button
          size="small"
          icon={<VideoCameraOutlined />}
          disabled={disabled}
          onClick={() => { setOpen('video'); setResult(null); setPrompt('') }}
        >
          Video
        </Button>
      </Space>

      <Modal
        title={open === 'video' ? 'Generate video' : 'Generate image'}
        open={!!open}
        onCancel={() => !busy && setOpen(null)}
        onOk={run}
        okText={busy ? 'Working…' : 'Generate (uses tokens)'}
        confirmLoading={busy}
        destroyOnClose
        width={Math.min(560, typeof window !== 'undefined' ? window.innerWidth - 32 : 560)}
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          Every generation advances your token meter and uses wallet credits when required.
        </Typography.Paragraph>
        <Input.TextArea
          rows={3}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder={open === 'video' ? 'Describe the video scene…' : 'Describe the image…'}
          disabled={busy}
        />
        {busy && <div style={{ textAlign: 'center', marginTop: 16 }}><Spin /></div>}
        {result && (
          <div style={{ marginTop: 16 }}>
            {(result.url || result.poster_url) && (
              <Image
                src={result.url || result.poster_url}
                alt="generated"
                style={{ maxWidth: '100%', borderRadius: 8 }}
              />
            )}
            {result.video_url && (
              <video src={result.video_url} controls style={{ width: '100%', marginTop: 8, borderRadius: 8 }} />
            )}
            {result.note && (
              <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
                {result.note}
              </Typography.Text>
            )}
            {result.usage && (
              <Typography.Text style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
                Used {result.usage.tokens} tokens · ${Number(result.usage.cost || 0).toFixed(4)}
              </Typography.Text>
            )}
          </div>
        )}
      </Modal>
    </>
  )
}
