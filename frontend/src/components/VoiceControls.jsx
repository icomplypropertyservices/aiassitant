import React, { useEffect, useRef, useState } from 'react'
import { Badge, Button, Space, Switch, Tag, Tooltip, Typography, message } from 'antd'
import {
  AudioOutlined, AudioMutedOutlined, SoundOutlined, StopOutlined, SendOutlined,
} from '@ant-design/icons'
import { api } from '../api'
import { acquireKeepAwake, releaseKeepAwake } from '../native'

/** Clamp a number into [lo, hi]; non-finite values fall back to `fallback`. */
function clampNum(value, lo, hi, fallback) {
  const n = Number(value)
  if (!Number.isFinite(n)) return fallback
  return Math.min(hi, Math.max(lo, n))
}

/** Always bill voice events so the token meter moves (STT + TTS). */
export async function meterVoice(kind, text = '') {
  try {
    const r = await api('/media/voice/meter', {
      method: 'POST',
      body: { kind, text: (text || ' ').slice(0, 4000) },
    })
    try {
      window.dispatchEvent(new CustomEvent('aba-usage', { detail: r }))
    } catch { /* ignore */ }
    return r
  } catch (e) {
    const msg = String(e?.message || e || '')
    if (
      msg.includes('402')
      || msg.toLowerCase().includes('token')
      || msg.toLowerCase().includes('credit')
      || msg.toLowerCase().includes('subscription')
    ) {
      message.warning(msg || 'Out of tokens for voice — top up to continue')
    }
    return null
  }
}

/**
 * Browser voice I/O for chat:
 * - Click mic → continuous speech-to-text (longer turns) → onTranscript
 * - Live volume bars while listening (Web Audio analyser)
 * - Optional TTS for assistant replies
 */
export function getSpeechRecognition() {
  if (typeof window === 'undefined') return null
  return window.SpeechRecognition || window.webkitSpeechRecognition || null
}

export function canSpeak() {
  return typeof window !== 'undefined' && !!window.speechSynthesis
}

export function speakText(text, { lang = 'en-GB', rate = 1, pitch = 1, volume = 1, onEnd, bill = true } = {}) {
  if (!canSpeak() || !text?.trim()) {
    onEnd?.()
    return null
  }
  try {
    window.speechSynthesis.cancel()
  } catch { /* ignore */ }
  const trimmed = String(text).trim()
  if (bill) meterVoice('voice_tts', trimmed)
  // Keep phone screen on while agent speaks (don't dim / lock)
  acquireKeepAwake('tts').catch(() => {})
  const onVis = () => {
    if (document.visibilityState === 'visible' && window.speechSynthesis?.speaking) {
      acquireKeepAwake('tts-resume').catch(() => {})
    }
  }
  try {
    document.addEventListener('visibilitychange', onVis)
  } catch { /* ignore */ }
  const done = () => {
    try { document.removeEventListener('visibilitychange', onVis) } catch { /* ignore */ }
    releaseKeepAwake().catch(() => {})
    try { onEnd?.() } catch { /* ignore */ }
  }
  const u = new SpeechSynthesisUtterance(trimmed)
  u.lang = lang
  u.rate = clampNum(rate, 0.1, 10, 1)
  u.pitch = clampNum(pitch, 0, 2, 1)
  // SpeechSynthesis volume is 0–1 only
  u.volume = clampNum(volume, 0, 1, 1)
  try {
    const voices = window.speechSynthesis.getVoices() || []
    const preferred = voices.find((v) => /en-GB/i.test(v.lang))
      || voices.find((v) => /en-US/i.test(v.lang))
      || voices.find((v) => /^en/i.test(v.lang))
    if (preferred) u.voice = preferred
  } catch { /* ignore voice pick */ }
  u.onend = done
  u.onerror = () => done()
  try {
    window.speechSynthesis.speak(u)
  } catch {
    done()
    return null
  }
  return u
}

export function stopSpeaking() {
  try {
    if (canSpeak()) window.speechSynthesis.cancel()
  } catch { /* ignore */ }
  releaseKeepAwake().catch(() => {})
}

const BAR_COUNT = 7
/** Visualization-only gain (not routed to speakers). Kept modest for analyser headroom. */
const METER_GAIN = 2.4
const IDLE_LEVELS = () => Array(BAR_COUNT).fill(0.08)

/**
 * @param {object} props
 * @param {(text: string) => void} props.onTranscript
 * @param {boolean} [props.disabled]
 * @param {boolean} [props.autoSend=true]
 * @param {(partial: string) => void} [props.onPartial]
 * @param {boolean} [props.speakReplies]
 * @param {(v: boolean) => void} [props.onSpeakRepliesChange]
 * @param {string} [props.lang='en-GB']
 * @param {number} [props.maxListenMs=120000] — max continuous listen (default 2 min)
 * @param {number} [props.silenceMs=2800] — end turn after this much silence once speech heard
 */
export default function VoiceControls({
  onTranscript,
  disabled = false,
  autoSend = true,
  onPartial,
  speakReplies = false,
  onSpeakRepliesChange,
  lang = 'en-GB',
  maxListenMs = 120000,
  silenceMs = 2800,
}) {
  const [supported, setSupported] = useState(true)
  const [listening, setListening] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [partial, setPartial] = useState('')
  const [levels, setLevels] = useState(IDLE_LEVELS)

  const recRef = useRef(null)
  const finalRef = useRef('')
  /** Latest interim (non-final) words — browsers often never mark isFinal before silence */
  const interimRef = useRef('')
  const listeningRef = useRef(false)
  const wantListenRef = useRef(false)
  const heardSpeechRef = useRef(false)
  const silenceTimerRef = useRef(null)
  const maxTimerRef = useRef(null)
  const restartTimerRef = useRef(null)
  const mountedRef = useRef(true)
  /** Parent callbacks in refs so finishListening always uses latest send/busy handlers */
  const onTranscriptRef = useRef(onTranscript)
  const onPartialRef = useRef(onPartial)
  useEffect(() => { onTranscriptRef.current = onTranscript }, [onTranscript])
  useEffect(() => { onPartialRef.current = onPartial }, [onPartial])

  // Volume meter (Web Audio)
  const streamRef = useRef(null)
  const audioCtxRef = useRef(null)
  const analyserRef = useRef(null)
  const gainRef = useRef(null)
  const sourceRef = useRef(null)
  const rafRef = useRef(null)
  const meterDataRef = useRef(null)
  const meterGenRef = useRef(0)

  useEffect(() => {
    mountedRef.current = true
    const SR = getSpeechRecognition()
    setSupported(!!SR)
    if (canSpeak()) {
      try {
        window.speechSynthesis.getVoices()
        window.speechSynthesis.onvoiceschanged = () => {
          try { window.speechSynthesis.getVoices() } catch { /* ignore */ }
        }
      } catch { /* ignore */ }
    }
    return () => {
      mountedRef.current = false
      wantListenRef.current = false
      hardStopMic()
      stopSpeaking()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const clearTimers = () => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current)
      silenceTimerRef.current = null
    }
    if (maxTimerRef.current) {
      clearTimeout(maxTimerRef.current)
      maxTimerRef.current = null
    }
    if (restartTimerRef.current) {
      clearTimeout(restartTimerRef.current)
      restartTimerRef.current = null
    }
  }

  const safeDisconnect = (node) => {
    try { node?.disconnect?.() } catch { /* ignore */ }
  }

  const stopVolumeMeter = () => {
    meterGenRef.current += 1
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
    safeDisconnect(sourceRef.current)
    safeDisconnect(gainRef.current)
    safeDisconnect(analyserRef.current)
    sourceRef.current = null
    gainRef.current = null
    analyserRef.current = null
    meterDataRef.current = null
    try {
      streamRef.current?.getTracks?.().forEach((t) => {
        try { t.stop() } catch { /* ignore */ }
      })
    } catch { /* ignore */ }
    streamRef.current = null
    try {
      const ctx = audioCtxRef.current
      if (ctx && ctx.state !== 'closed') ctx.close?.()
    } catch { /* ignore */ }
    audioCtxRef.current = null
    if (mountedRef.current) setLevels(IDLE_LEVELS())
  }

  const startVolumeMeter = async () => {
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) return
    const gen = ++meterGenRef.current
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          // Prefer higher input level when browser supports it (hint only)
          autoGainControl: true,
        },
        video: false,
      })
      // Aborted while awaiting permission / getUserMedia
      if (gen !== meterGenRef.current || !wantListenRef.current) {
        try { stream.getTracks?.().forEach((t) => t.stop()) } catch { /* ignore */ }
        return
      }
      streamRef.current = stream

      const AC = window.AudioContext || window.webkitAudioContext
      if (!AC) {
        try { stream.getTracks?.().forEach((t) => t.stop()) } catch { /* ignore */ }
        streamRef.current = null
        return
      }

      let ctx
      try {
        ctx = new AC()
      } catch {
        try { stream.getTracks?.().forEach((t) => t.stop()) } catch { /* ignore */ }
        streamRef.current = null
        return
      }
      if (gen !== meterGenRef.current || !wantListenRef.current) {
        try { if (ctx.state !== 'closed') ctx.close?.() } catch { /* ignore */ }
        try { stream.getTracks?.().forEach((t) => t.stop()) } catch { /* ignore */ }
        streamRef.current = null
        return
      }
      audioCtxRef.current = ctx
      if (ctx.state === 'suspended') {
        try { await ctx.resume() } catch { /* ignore */ }
      }

      let source
      let gainNode
      let analyser
      try {
        source = ctx.createMediaStreamSource(stream)
        // Visualization-only gain — not routed to speakers, so safe across browsers
        gainNode = ctx.createGain()
        const g = clampNum(METER_GAIN, 0.01, 8, 1)
        try {
          if (gainNode.gain && typeof gainNode.gain.setValueAtTime === 'function') {
            gainNode.gain.setValueAtTime(g, ctx.currentTime || 0)
          } else if (gainNode.gain) {
            gainNode.gain.value = g
          }
        } catch {
          try { if (gainNode.gain) gainNode.gain.value = 1 } catch { /* ignore */ }
        }
        analyser = ctx.createAnalyser()
        analyser.fftSize = 512
        analyser.smoothingTimeConstant = 0.55
        // Wider dynamic range so quiet speech still moves the bars
        try {
          analyser.minDecibels = -90
          analyser.maxDecibels = -20
        } catch { /* ignore */ }
        source.connect(gainNode)
        gainNode.connect(analyser)
      } catch {
        try { if (ctx.state !== 'closed') ctx.close?.() } catch { /* ignore */ }
        try { stream.getTracks?.().forEach((t) => t.stop()) } catch { /* ignore */ }
        streamRef.current = null
        audioCtxRef.current = null
        return
      }

      if (gen !== meterGenRef.current || !wantListenRef.current) {
        safeDisconnect(source)
        safeDisconnect(gainNode)
        safeDisconnect(analyser)
        try { if (ctx.state !== 'closed') ctx.close?.() } catch { /* ignore */ }
        try { stream.getTracks?.().forEach((t) => t.stop()) } catch { /* ignore */ }
        streamRef.current = null
        audioCtxRef.current = null
        return
      }

      sourceRef.current = source
      gainRef.current = gainNode
      analyserRef.current = analyser
      try {
        meterDataRef.current = new Uint8Array(analyser.fftSize)
      } catch {
        meterDataRef.current = new Uint8Array(512)
      }

      const tick = () => {
        if (gen !== meterGenRef.current || !listeningRef.current) return
        const a = analyserRef.current
        const data = meterDataRef.current
        if (!a || !data) return
        try {
          // Time-domain RMS tracks speech energy better than sparse frequency bins
          a.getByteTimeDomainData(data)
          let sumSq = 0
          const len = data.length || 1
          for (let i = 0; i < len; i++) {
            const v = (data[i] - 128) / 128
            sumSq += v * v
          }
          const rms = Math.sqrt(sumSq / len)
          // Soft boost: quiet speech ~0.3–0.7, loud speech caps at 1
          const level = Math.min(1, 0.08 + rms * 3.6)
          // Spread energy across bars with slight center emphasis for a live look
          const next = []
          const mid = (BAR_COUNT - 1) / 2 || 1
          const now = Date.now()
          for (let i = 0; i < BAR_COUNT; i++) {
            const weight = 0.65 + 0.35 * (1 - Math.abs(i - mid) / mid)
            const jitter = 0.85 + 0.15 * Math.sin(now / 90 + i)
            next.push(Math.min(1, level * weight * jitter))
          }
          if (mountedRef.current && listeningRef.current) setLevels(next)
        } catch { /* ignore frame errors */ }
        rafRef.current = requestAnimationFrame(tick)
      }
      rafRef.current = requestAnimationFrame(tick)
    } catch {
      // Mic permission may still work for SpeechRecognition alone
    }
  }

  const combinedTranscript = () => {
    const fin = String(finalRef.current || '').trim()
    const inter = String(interimRef.current || '').trim()
    return `${fin}${fin && inter ? ' ' : ''}${inter}`.replace(/\s+/g, ' ').trim()
  }

  const finishListening = (sendText, { forceSend = false } = {}) => {
    wantListenRef.current = false
    listeningRef.current = false
    if (mountedRef.current) setListening(false)
    clearTimers()
    try { recRef.current?.stop() } catch { /* ignore */ }
    recRef.current = null
    stopVolumeMeter()
    releaseKeepAwake().catch(() => {})

    // Prefer explicit text; else final + interim (interim alone is common on mobile Chrome)
    const text = String(
      sendText != null && String(sendText).trim()
        ? sendText
        : combinedTranscript(),
    ).trim()
    if (mountedRef.current) setPartial('')
    finalRef.current = ''
    interimRef.current = ''
    heardSpeechRef.current = false
    if (!text) {
      message.info('No speech captured — hold the mic a moment longer, then pause or tap Send')
      return
    }
    meterVoice('voice_stt', text)
    // Always put text in the composer first so a failed auto-send is not lost
    try { onPartialRef.current?.(text) } catch { /* ignore */ }
    // forceSend = user tapped the Send button while talking
    if ((autoSend || forceSend) && onTranscriptRef.current) {
      try {
        onTranscriptRef.current(text)
      } catch (e) {
        message.warning(e?.message || 'Could not send voice message — text is in the box, tap Send')
      }
    }
  }

  const armSilenceTimer = () => {
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
    // Only auto-end after user has actually spoken
    if (!heardSpeechRef.current) return
    silenceTimerRef.current = setTimeout(() => {
      if (wantListenRef.current) finishListening()
    }, clampNum(silenceMs, 500, 30000, 2800))
  }

  const attachRecHandlers = (rec) => {
    rec.onstart = () => {
      listeningRef.current = true
      if (mountedRef.current) setListening(true)
    }
    rec.onerror = (ev) => {
      const err = ev?.error || ''
      // continuous sessions often emit no-speech / aborted — ignore those
      if (err === 'not-allowed') {
        message.error('Microphone permission denied. Allow mic access for this site.')
        wantListenRef.current = false
        finishListening('')
        return
      }
      if (err === 'aborted' || err === 'no-speech') return
      if (err === 'network') {
        message.warning('Voice network glitch — try the mic again')
      }
    }
    rec.onend = () => {
      // Fold non-final words into the committed buffer before Chrome restarts
      if (interimRef.current) {
        const fin = String(finalRef.current || '').trim()
        const inter = String(interimRef.current || '').trim()
        finalRef.current = `${fin}${fin && inter ? ' ' : ''}${inter} `.replace(/\s+/g, ' ')
        interimRef.current = ''
      }
      // Chrome ends continuous sessions periodically — restart while user still wants mic
      if (wantListenRef.current) {
        restartTimerRef.current = setTimeout(() => {
          if (!wantListenRef.current) return
          try {
            const SR = getSpeechRecognition()
            if (!SR) return
            const next = new SR()
            next.lang = lang
            next.interimResults = true
            next.continuous = true
            next.maxAlternatives = 1
            attachRecHandlers(next)
            recRef.current = next
            next.start()
          } catch {
            finishListening()
          }
        }, 120)
        return
      }
      // User already called finishListening/hardStop — do not double-send
      listeningRef.current = false
      if (mountedRef.current) setListening(false)
    }
    rec.onresult = (event) => {
      let interim = ''
      let final = finalRef.current
      try {
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const r = event.results[i]
          const t = (r?.[0]?.transcript || '').trim()
          if (!t) continue
          if (r.isFinal) {
            final = `${final}${final.endsWith(' ') || !final ? '' : ' '}${t} `.replace(/\s+/g, ' ')
            heardSpeechRef.current = true
            // Clear interim when a final segment lands (avoids double words)
            interim = ''
          } else {
            interim = interim ? `${interim} ${t}` : t
            heardSpeechRef.current = true
          }
        }
      } catch { /* ignore malformed result */ }
      finalRef.current = final
      interimRef.current = interim
      const display = combinedTranscript()
      if (mountedRef.current) setPartial(display)
      try { onPartialRef.current?.(display) } catch { /* ignore parent errors */ }
      armSilenceTimer()
    }
  }

  const hardStopMic = () => {
    wantListenRef.current = false
    listeningRef.current = false
    clearTimers()
    try { recRef.current?.abort?.() } catch { /* ignore */ }
    try { recRef.current?.stop?.() } catch { /* ignore */ }
    recRef.current = null
    stopVolumeMeter()
    releaseKeepAwake().catch(() => {})
    if (mountedRef.current) {
      setListening(false)
      setPartial('')
    }
  }

  const startListen = async () => {
    if (disabled) return
    const SR = getSpeechRecognition()
    if (!SR) {
      message.warning('Voice input is not supported in this browser. Try Chrome or Edge.')
      return
    }
    stopSpeaking()
    if (mountedRef.current) setSpeaking(false)
    finalRef.current = ''
    interimRef.current = ''
    if (mountedRef.current) setPartial('')
    heardSpeechRef.current = false
    wantListenRef.current = true
    clearTimers()
    // Don't let the phone sleep while the mic is open
    acquireKeepAwake('mic').catch(() => {})

    // Volume bars (separate from SpeechRecognition so UI always animates)
    startVolumeMeter()

    let rec
    try {
      rec = new SR()
      rec.lang = lang
      rec.interimResults = true
      rec.continuous = true // longer multi-sentence turns
      rec.maxAlternatives = 1
      attachRecHandlers(rec)
      recRef.current = rec
    } catch {
      message.error('Could not start microphone')
      hardStopMic()
      return
    }

    maxTimerRef.current = setTimeout(() => {
      if (wantListenRef.current) {
        message.info('Mic stopped after 2 minutes — tap again to continue')
        finishListening()
      }
    }, clampNum(maxListenMs, 5000, 600000, 120000))

    try {
      rec.start()
      if (mountedRef.current) setListening(true)
      listeningRef.current = true
    } catch {
      message.error('Could not start microphone')
      hardStopMic()
    }
  }

  const toggleMic = () => {
    if (listening || wantListenRef.current) {
      // Manual stop → send whatever we have
      finishListening()
    } else {
      startListen()
    }
  }

  if (!supported && !canSpeak()) {
    return (
      <Tag color="default">
        Voice not supported in this browser
      </Tag>
    )
  }

  const micButton = supported ? (
    <Tooltip title={listening ? 'Stop & send what you said' : 'Talk longer — mic stays on until you pause or tap stop'}>
      <Badge
        dot={listening}
        color={listening ? 'var(--aba-danger, #dc2626)' : undefined}
        offset={[-4, 4]}
      >
        <Button
          type={listening ? 'primary' : 'default'}
          danger={listening}
          shape="circle"
          size="large"
          icon={listening ? <AudioMutedOutlined /> : <AudioOutlined />}
          onClick={toggleMic}
          disabled={disabled && !listening}
          aria-label={listening ? 'Stop microphone' : 'Start microphone'}
          aria-pressed={listening}
          className={listening ? 'aba-voice-mic-active' : 'aba-voice-mic'}
        />
      </Badge>
    </Tooltip>
  ) : null

  return (
    <Space wrap size="small" align="center" className="aba-voice-controls">
      {micButton}

      {/* Live volume indicator */}
      {listening && (
        <div
          className="aba-voice-meter"
          role="status"
          aria-live="polite"
          aria-label="Microphone volume"
          title="Mic level"
        >
          {levels.map((lv, i) => {
            const safe = clampNum(lv, 0, 1, 0.08)
            return (
              <span
                key={i}
                className="aba-voice-meter-bar"
                style={{
                  height: `${Math.round(10 + safe * 22)}px`,
                  opacity: 0.45 + safe * 0.55,
                }}
              />
            )
          })}
        </div>
      )}

      {canSpeak() && (
        <Space size={6} align="center" className="aba-voice-tts">
          <Tooltip title="Read agent replies aloud">
            <Space size={4} align="center">
              <SoundOutlined style={{ color: 'var(--aba-muted, #64748b)', fontSize: 14 }} />
              <Switch
                size="small"
                checked={!!speakReplies}
                onChange={(v) => {
                  if (!v) {
                    stopSpeaking()
                    if (mountedRef.current) setSpeaking(false)
                  }
                  onSpeakRepliesChange?.(!!v)
                }}
                checkedChildren="Speak"
                unCheckedChildren="Mute"
              />
            </Space>
          </Tooltip>
          {speaking && (
            <Button
              type="default"
              size="small"
              danger
              icon={<StopOutlined />}
              onClick={() => {
                stopSpeaking()
                if (mountedRef.current) setSpeaking(false)
              }}
            >
              Stop voice
            </Button>
          )}
        </Space>
      )}

      {listening && (
        <Tag color="error" icon={<AudioOutlined />} className="aba-voice-listening-tag">
          Listening… {partial
            ? `"${partial.slice(0, 64)}${partial.length > 64 ? '…' : ''}"`
            : 'keep talking — then tap Send'}
        </Tag>
      )}

      {/* Explicit Send while talking — stops mic and sends to the agent */}
      {listening && (
        <Button
          type="primary"
          size="large"
          icon={<SendOutlined />}
          className="aba-voice-send-btn"
          onClick={() => finishListening(undefined, { forceSend: true })}
          disabled={disabled}
        >
          Send
        </Button>
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
