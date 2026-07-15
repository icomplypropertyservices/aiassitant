import React, { useEffect, useRef, useState } from 'react'
import { Button, Space, Switch, Tag, Tooltip, Typography, message } from 'antd'
import {
  AudioOutlined, AudioMutedOutlined, SoundOutlined, StopOutlined,
} from '@ant-design/icons'

/**
 * Browser voice I/O for chat:
 * - Hold/click mic → speech-to-text → onTranscript(text) (usually send)
 * - Optional TTS for assistant replies via speak(text)
 *
 * Uses Web Speech API (Chrome/Edge best). No server keys required.
 */
export function getSpeechRecognition() {
  if (typeof window === 'undefined') return null
  return window.SpeechRecognition || window.webkitSpeechRecognition || null
}

export function canSpeak() {
  return typeof window !== 'undefined' && !!window.speechSynthesis
}

export function speakText(text, { lang = 'en-GB', rate = 1, pitch = 1, onEnd } = {}) {
  if (!canSpeak() || !text?.trim()) {
    onEnd?.()
    return null
  }
  window.speechSynthesis.cancel()
  const u = new SpeechSynthesisUtterance(text.trim())
  u.lang = lang
  u.rate = rate
  u.pitch = pitch
  // Prefer a British/English voice when available
  const voices = window.speechSynthesis.getVoices() || []
  const preferred = voices.find(v => /en-GB/i.test(v.lang))
    || voices.find(v => /en-US/i.test(v.lang))
    || voices.find(v => /^en/i.test(v.lang))
  if (preferred) u.voice = preferred
  if (onEnd) u.onend = onEnd
  u.onerror = () => onEnd?.()
  window.speechSynthesis.speak(u)
  return u
}

export function stopSpeaking() {
  if (canSpeak()) window.speechSynthesis.cancel()
}

/**
 * @param {object} props
 * @param {(text: string) => void} props.onTranscript — called with final transcript (send to agent)
 * @param {boolean} [props.disabled]
 * @param {boolean} [props.autoSend=true] — send as soon as recognition ends
 * @param {(partial: string) => void} [props.onPartial] — interim transcript for input box
 * @param {boolean} [props.speakReplies] — controlled: whether TTS is on
 * @param {(v: boolean) => void} [props.onSpeakRepliesChange]
 * @param {string} [props.lang='en-GB']
 */
export default function VoiceControls({
  onTranscript,
  disabled = false,
  autoSend = true,
  onPartial,
  speakReplies = false,
  onSpeakRepliesChange,
  lang = 'en-GB',
}) {
  const [supported, setSupported] = useState(true)
  const [listening, setListening] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [partial, setPartial] = useState('')
  const recRef = useRef(null)
  const finalRef = useRef('')

  useEffect(() => {
    const SR = getSpeechRecognition()
    setSupported(!!SR)
    // Chrome loads voices async
    if (canSpeak()) {
      window.speechSynthesis.getVoices()
      window.speechSynthesis.onvoiceschanged = () => window.speechSynthesis.getVoices()
    }
    return () => {
      try { recRef.current?.stop() } catch { /* ignore */ }
      stopSpeaking()
    }
  }, [])

  const stopListen = () => {
    try { recRef.current?.stop() } catch { /* ignore */ }
    setListening(false)
  }

  const startListen = () => {
    if (disabled) return
    const SR = getSpeechRecognition()
    if (!SR) {
      message.warning('Voice input is not supported in this browser. Try Chrome or Edge.')
      return
    }
    stopSpeaking()
    setSpeaking(false)
    finalRef.current = ''
    setPartial('')

    const rec = new SR()
    rec.lang = lang
    rec.interimResults = true
    rec.continuous = false
    rec.maxAlternatives = 1

    rec.onstart = () => setListening(true)
    rec.onerror = (ev) => {
      setListening(false)
      if (ev.error === 'not-allowed') {
        message.error('Microphone permission denied. Allow mic access for this site.')
      } else if (ev.error !== 'aborted' && ev.error !== 'no-speech') {
        message.error(`Voice error: ${ev.error}`)
      }
    }
    rec.onend = () => {
      setListening(false)
      const text = finalRef.current.trim()
      setPartial('')
      if (text && autoSend && onTranscript) {
        onTranscript(text)
      } else if (text && onPartial) {
        onPartial(text)
      }
    }
    rec.onresult = (event) => {
      let interim = ''
      let final = finalRef.current
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const r = event.results[i]
        const t = r[0]?.transcript || ''
        if (r.isFinal) final += t
        else interim += t
      }
      finalRef.current = final
      const display = (final + interim).trim()
      setPartial(display)
      onPartial?.(display)
    }

    recRef.current = rec
    try {
      rec.start()
    } catch (e) {
      message.error('Could not start microphone')
      setListening(false)
    }
  }

  const toggleMic = () => {
    if (listening) stopListen()
    else startListen()
  }

  if (!supported && !canSpeak()) {
    return (
      <Tag color="default">
        Voice not supported in this browser
      </Tag>
    )
  }

  return (
    <Space wrap align="center">
      {supported && (
        <Tooltip title={listening ? 'Stop listening' : 'Talk to the agent (speech → text)'}>
          <Button
            type={listening ? 'primary' : 'default'}
            danger={listening}
            shape="circle"
            size="large"
            icon={listening ? <AudioMutedOutlined /> : <AudioOutlined />}
            onClick={toggleMic}
            disabled={disabled && !listening}
            style={listening ? { boxShadow: '0 0 0 3px rgba(255,77,79,0.25)' } : undefined}
          />
        </Tooltip>
      )}
      {canSpeak() && (
        <>
          <Tooltip title="Read agent replies aloud">
            <Space size={4}>
              <SoundOutlined />
              <Switch
                size="small"
                checked={speakReplies}
                onChange={(v) => {
                  if (!v) {
                    stopSpeaking()
                    setSpeaking(false)
                  }
                  onSpeakRepliesChange?.(v)
                }}
                checkedChildren="Speak"
                unCheckedChildren="Mute"
              />
            </Space>
          </Tooltip>
          {speaking && (
            <Button
              size="small"
              icon={<StopOutlined />}
              onClick={() => { stopSpeaking(); setSpeaking(false) }}
            >
              Stop voice
            </Button>
          )}
        </>
      )}
      {listening && (
        <Tag color="red" icon={<AudioOutlined />}>
          Listening… {partial ? `"${partial.slice(0, 48)}${partial.length > 48 ? '…' : ''}"` : 'speak now'}
        </Tag>
      )}
      {!supported && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          Mic unavailable — TTS still works if enabled
        </Typography.Text>
      )}
    </Space>
  )
}

/** Hook helpers for parent pages to speak assistant text when a reply finishes */
export function useVoiceReply(speakReplies) {
  const [speaking, setSpeaking] = useState(false)
  const speakReply = (text) => {
    if (!speakReplies || !text?.trim()) return
    setSpeaking(true)
    speakText(text, {
      onEnd: () => setSpeaking(false),
    })
  }
  const stop = () => {
    stopSpeaking()
    setSpeaking(false)
  }
  useEffect(() => () => stopSpeaking(), [])
  return { speakReply, stop, speaking, setSpeaking }
}
