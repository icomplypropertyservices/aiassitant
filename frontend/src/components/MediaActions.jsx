import React, { useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Divider,
  Image,
  Input,
  Modal,
  Segmented,
  Select,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  CopyOutlined,
  DownloadOutlined,
  PictureOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import { api } from '../api'

const { Text, Paragraph } = Typography

const IMAGE_SIZES = [
  { value: '1024x1024', label: 'Square · 1024' },
  { value: '1792x1024', label: 'Landscape · 1792' },
  { value: '1024x1792', label: 'Portrait · 1024' },
]

const IMAGE_STYLES = [
  { value: 'vivid', label: 'Vivid' },
  { value: 'natural', label: 'Natural' },
]

const VIDEO_DURATIONS = [
  { value: 4, label: '4s' },
  { value: 6, label: '6s' },
  { value: 8, label: '8s' },
  { value: 12, label: '12s' },
]

function emitUsage(detail) {
  if (!detail) return
  try {
    window.dispatchEvent(new CustomEvent('aba-usage', { detail }))
  } catch {
    /* ignore */
  }
}

function downloadUrl(url, filename) {
  if (!url) return
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = filename || 'media'
    a.target = '_blank'
    a.rel = 'noopener noreferrer'
    document.body.appendChild(a)
    a.click()
    a.remove()
  } catch {
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}

/**
 * Image + Video generation toolbar + modal.
 * Always billed on the token meter; mirrors VoiceControls event + Ant Design patterns.
 *
 * @param {object} props
 * @param {boolean} [props.disabled]
 * @param {(usage: object) => void} [props.onUsage]
 * @param {(asset: object) => void} [props.onAsset]
 * @param {boolean} [props.compact=false] — icon-first buttons for tight toolbars
 */
export default function MediaActions({ disabled, onUsage, onAsset, compact = false }) {
  const [open, setOpen] = useState(null) // 'image' | 'video' | null
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [size, setSize] = useState('1024x1024')
  const [style, setStyle] = useState('vivid')
  const [duration, setDuration] = useState(4)

  const isVideo = open === 'video'
  const title = isVideo ? 'Generate video' : 'Generate image'
  const placeholder = isVideo
    ? 'Describe the video scene, motion, and mood…'
    : 'Describe the image, style, subject, and lighting…'

  const previewSrc = useMemo(
    () => result?.url || result?.poster_url || null,
    [result],
  )

  const resetForm = (mode) => {
    setOpen(mode)
    setResult(null)
    setPrompt('')
    setSize('1024x1024')
    setStyle('vivid')
    setDuration(4)
  }

  const close = () => {
    if (busy) return
    setOpen(null)
    setResult(null)
    setPrompt('')
  }

  const run = async () => {
    const p = prompt.trim()
    if (p.length < 3) {
      message.warning('Enter a prompt (at least 3 characters)')
      return
    }
    setBusy(true)
    setResult(null)
    try {
      const path = isVideo ? '/media/video' : '/media/image'
      const body = isVideo
        ? { prompt: p, duration_sec: duration }
        : { prompt: p, size, style }
      const data = await api(path, { method: 'POST', body })
      setResult(data)
      const usage = data.usage || data.meter
      onUsage?.(usage)
      onAsset?.(data)
      emitUsage(data.usage ? { ...data, ...data.usage } : data)
      message.success(
        isVideo
          ? 'Video job billed — poster ready'
          : 'Image generated (tokens used)',
      )
    } catch (e) {
      const msg = String(e.message || e || '')
      if (
        msg.includes('402')
        || /token|credit|subscription|balance/i.test(msg)
      ) {
        message.warning(msg || 'Out of tokens — top up to continue')
      } else {
        message.error(msg || 'Media generation failed')
      }
    } finally {
      setBusy(false)
    }
  }

  const copyPrompt = async () => {
    const text = (result?.prompt || prompt || '').trim()
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      message.success('Prompt copied')
    } catch {
      message.error('Could not copy')
    }
  }

  const actionButtons = (
    <Space wrap size={4} className="aba-media-actions">
      <Tooltip title="Generate an image (uses tokens)">
        <Button
          size="small"
          type={compact ? 'text' : 'default'}
          icon={<PictureOutlined />}
          disabled={disabled}
          onClick={() => resetForm('image')}
          aria-label="Generate image"
        >
          {compact ? null : 'Image'}
        </Button>
      </Tooltip>
      <Tooltip title="Generate a short video concept (uses tokens)">
        <Button
          size="small"
          type={compact ? 'text' : 'default'}
          icon={<VideoCameraOutlined />}
          disabled={disabled}
          onClick={() => resetForm('video')}
          aria-label="Generate video"
        >
          {compact ? null : 'Video'}
        </Button>
      </Tooltip>
    </Space>
  )

  const modalFooter = (
    <Space wrap style={{ width: '100%', justifyContent: 'space-between' }}>
      <Space size={4}>
        {result && (
          <>
            <Tooltip title="Generate again with the same prompt">
              <Button
                icon={<ReloadOutlined />}
                onClick={run}
                disabled={busy || prompt.trim().length < 3}
              >
                Regenerate
              </Button>
            </Tooltip>
            {previewSrc && (
              <Button
                icon={<DownloadOutlined />}
                onClick={() =>
                  downloadUrl(
                    previewSrc,
                    isVideo ? 'video-poster.png' : 'generated-image.png',
                  )
                }
              >
                Download
              </Button>
            )}
            <Button icon={<CopyOutlined />} onClick={copyPrompt}>
              Copy prompt
            </Button>
          </>
        )}
      </Space>
      <Space>
        <Button onClick={close} disabled={busy}>
          {result ? 'Close' : 'Cancel'}
        </Button>
        <Button
          type="primary"
          icon={<ThunderboltOutlined />}
          onClick={run}
          loading={busy}
          disabled={prompt.trim().length < 3}
        >
          {busy ? 'Working…' : 'Generate (uses tokens)'}
        </Button>
      </Space>
    </Space>
  )

  return (
    <>
      {actionButtons}

      <Modal
        title={
          <Space>
            {isVideo ? <VideoCameraOutlined /> : <PictureOutlined />}
            <span>{title}</span>
            <Tag color="processing" icon={<ThunderboltOutlined />}>
              Billed
            </Tag>
          </Space>
        }
        open={!!open}
        onCancel={close}
        footer={modalFooter}
        destroyOnClose
        maskClosable={!busy}
        keyboard={!busy}
        width={Math.min(560, typeof window !== 'undefined' ? window.innerWidth - 32 : 560)}
        styles={{ body: { paddingTop: 12 } }}
        className="aba-media-modal"
      >
        <Alert
          type="info"
          showIcon
          icon={<ThunderboltOutlined />}
          style={{ marginBottom: 12 }}
          message="Every generation advances your token meter and uses wallet credits when required."
        />

        <div style={{ marginBottom: 12 }}>
          {isVideo ? (
            <Space wrap size={[12, 8]} style={{ width: '100%' }}>
              <div>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                  Duration
                </Text>
                <Segmented
                  size="small"
                  value={duration}
                  onChange={setDuration}
                  options={VIDEO_DURATIONS}
                  disabled={busy}
                />
              </div>
            </Space>
          ) : (
            <Space wrap size={[12, 8]} style={{ width: '100%' }}>
              <div>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                  Size
                </Text>
                <Select
                  size="small"
                  value={size}
                  onChange={setSize}
                  options={IMAGE_SIZES}
                  disabled={busy}
                  style={{ minWidth: 160 }}
                />
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                  Style
                </Text>
                <Segmented
                  size="small"
                  value={style}
                  onChange={setStyle}
                  options={IMAGE_STYLES}
                  disabled={busy}
                />
              </div>
            </Space>
          )}
        </div>

        <Input.TextArea
          rows={3}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onPressEnter={(e) => {
            if (e.shiftKey) return
            e.preventDefault()
            if (!busy && prompt.trim().length >= 3) run()
          }}
          placeholder={placeholder}
          disabled={busy}
          showCount
          maxLength={2000}
          style={{ marginBottom: 4 }}
        />

        {busy && (
          <div style={{ textAlign: 'center', marginTop: 20, marginBottom: 8 }}>
            <Spin tip={isVideo ? 'Creating video job…' : 'Generating image…'} />
          </div>
        )}

        {result && (
          <div className="aba-media-result" style={{ marginTop: 16 }}>
            <Divider style={{ margin: '8px 0 16px' }} />
            {previewSrc && (
              <Image
                src={previewSrc}
                alt={result.prompt || 'generated'}
                style={{ maxWidth: '100%', borderRadius: 8 }}
              />
            )}
            {result.video_url && (
              <video
                src={result.video_url}
                controls
                style={{ width: '100%', marginTop: 8, borderRadius: 8, display: 'block' }}
              />
            )}
            {result.note && (
              <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}>
                {result.note}
              </Paragraph>
            )}
            {result.usage && (
              <Tag color="blue" style={{ marginTop: 10 }}>
                Used {result.usage.tokens?.toLocaleString?.() ?? result.usage.tokens} tokens
                {result.usage.cost != null
                  ? ` · $${Number(result.usage.cost || 0).toFixed(4)}`
                  : ''}
              </Tag>
            )}
            {result.provider && (
              <Text type="secondary" style={{ display: 'block', marginTop: 6, fontSize: 11 }}>
                Provider: {result.provider}
                {isVideo && result.duration_sec != null ? ` · ${result.duration_sec}s` : ''}
                {!isVideo && size ? ` · ${size}` : ''}
              </Text>
            )}
          </div>
        )}
      </Modal>
    </>
  )
}
