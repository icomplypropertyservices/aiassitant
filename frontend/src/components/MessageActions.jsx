import React, { useState } from 'react'
import { Button, Space, Tooltip, message } from 'antd'
import {
  SoundOutlined, CopyOutlined, DownloadOutlined, StopOutlined,
} from '@ant-design/icons'
import { speakText, stopSpeaking, canSpeak } from './VoiceControls'
import { hapticLight, hapticSuccess, hapticSelect } from '../native'

/**
 * Play (TTS) · Copy · Download under each assistant response.
 *
 * @param {object} props
 * @param {string} props.text — full message body to act on
 * @param {string} [props.filename] — download basename (no extension)
 * @param {string} [props.className]
 */
export default function MessageActions({
  text = '',
  filename = 'agent-response',
  className = '',
}) {
  const [playing, setPlaying] = useState(false)
  const body = String(text || '').trim()
  if (!body) return null

  const onPlay = () => {
    try {
      if (playing) {
        stopSpeaking()
        setPlaying(false)
        try { hapticSelect() } catch { /* ignore */ }
        return
      }
      if (!canSpeak()) {
        message.warning('Speech playback is not supported in this browser')
        return
      }
      try { hapticLight() } catch { /* ignore */ }
      setPlaying(true)
      // Cap spoken length — very long TTS can freeze mobile WebViews
      const spoken = body.length > 4000 ? `${body.slice(0, 4000)}…` : body
      speakText(spoken, {
        bill: true,
        onEnd: () => {
          try { setPlaying(false) } catch { /* unmounted */ }
        },
      })
    } catch (e) {
      setPlaying(false)
      message.error(e?.message || 'Playback failed')
    }
  }

  const onCopy = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(body)
      } else {
        const ta = document.createElement('textarea')
        ta.value = body
        ta.style.position = 'fixed'
        ta.style.left = '-9999px'
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        document.body.removeChild(ta)
      }
      try { hapticSuccess() } catch { /* ignore */ }
      message.success('Copied to clipboard')
    } catch (e) {
      message.error(e?.message || 'Copy failed')
    }
  }

  const onDownload = () => {
    try {
      const safe = String(filename || 'agent-response')
        .replace(/[^\w\-]+/g, '_')
        .slice(0, 60) || 'agent-response'
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
      const blob = new Blob([body], { type: 'text/plain;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${safe}-${stamp}.txt`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      try { hapticLight() } catch { /* ignore */ }
      message.success('Download started')
    } catch (e) {
      message.error(e?.message || 'Download failed')
    }
  }

  return (
    <Space size={4} wrap className={`aba-msg-actions ${className}`.trim()}>
      <Tooltip title={playing ? 'Stop playback' : 'Play response aloud'}>
        <Button
          type="text"
          size="small"
          icon={playing ? <StopOutlined /> : <SoundOutlined />}
          onClick={onPlay}
          aria-label={playing ? 'Stop playback' : 'Play response'}
          className="aba-msg-action-btn"
        >
          {playing ? 'Stop' : 'Play'}
        </Button>
      </Tooltip>
      <Tooltip title="Copy response">
        <Button
          type="text"
          size="small"
          icon={<CopyOutlined />}
          onClick={onCopy}
          aria-label="Copy response"
          className="aba-msg-action-btn"
        >
          Copy
        </Button>
      </Tooltip>
      <Tooltip title="Download as text file">
        <Button
          type="text"
          size="small"
          icon={<DownloadOutlined />}
          onClick={onDownload}
          aria-label="Download response"
          className="aba-msg-action-btn"
        >
          Download
        </Button>
      </Tooltip>
    </Space>
  )
}
