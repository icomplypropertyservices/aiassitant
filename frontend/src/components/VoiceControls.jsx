import React, { useEffect, useRef, useState } from 'react'
import { Badge, Button, Space, Switch, Tag, Tooltip, Typography, message } from 'antd'
import {
  AudioOutlined, AudioMutedOutlined, SoundOutlined, StopOutlined, SendOutlined,
} from '@ant-design/icons'
import { api } from '../api'
import {
  acquireKeepAwake,
  releaseKeepAwake,
  hapticLight,
  hapticMedium,
  hapticSuccess,
  hapticError,
  hapticSelect,
} from '../native'

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

/** Prefer device language; en-GB alone often fails offline STT packs on phones. */
export function defaultSpeechLang() {
  try {
    const l = (typeof navigator !== 'undefined' && (navigator.language || navigator.userLanguage)) || 'en-US'
    return String(l || 'en-US')
  } catch {
    return 'en-US'
  }
}

function prefersNonContinuousSpeech() {
  try {
    const ua = navigator.userAgent || ''
    // continuous=true drops/breaks interim results on many mobile WebViews + Safari
    if (/Android|iPhone|iPad|iPod|Mobile|webOS|CriOS|FxiOS|EdgiOS/i.test(ua)) return true
    // iPadOS 13+ reports as Macintosh — detect touch
    if (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1) return true
    return false
  } catch {
    return true
  }
}

/** SpeechRecognition prefers a concrete BCP-47 tag; bare "en" often yields silence. */
function normalizeSpeechLang(lang) {
  const raw = String(lang || '').trim() || 'en-US'
  if (/^[a-z]{2}$/i.test(raw)) {
    const map = { en: 'en-US', gb: 'en-GB', uk: 'en-GB', es: 'es-ES', fr: 'fr-FR', de: 'de-DE' }
    return map[raw.toLowerCase()] || `${raw}-US`
  }
  return raw
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
 * @param {string} [props.lang] — BCP-47 language (default: device language)
 * @param {number} [props.maxListenMs=120000] — max continuous listen (default 2 min)
 * @param {number} [props.silenceMs=3500] — end turn after this much silence once speech heard
 */
export default function VoiceControls({
  onTranscript,
  disabled = false,
  autoSend = true,
  onPartial,
  speakReplies = false,
  onSpeakRepliesChange,
  lang,
  maxListenMs = 120000,
  silenceMs = 3500,
}) {
  const speechLang = normalizeSpeechLang(lang || defaultSpeechLang())
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
  const lateResultTimerRef = useRef(null)
  const mountedRef = useRef(true)
  /** false on mobile — continuous mode often never delivers usable text */
  const continuousRef = useRef(!prefersNonContinuousSpeech())
  /** Mobile: skip second getUserMedia for meters (steals mic from STT) */
  const mobileMicRef = useRef(prefersNonContinuousSpeech())
  /** Parent callbacks in refs so finishListening always uses latest send/busy handlers */
  const onTranscriptRef = useRef(onTranscript)
  const onPartialRef = useRef(onPartial)
  const finishRef = useRef(null)
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
    if (lateResultTimerRef.current) {
      clearTimeout(lateResultTimerRef.current)
      lateResultTimerRef.current = null
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

  const foldInterimIntoFinal = () => {
    const inter = String(interimRef.current || '').trim()
    if (!inter) return
    const fin = String(finalRef.current || '').trim()
    finalRef.current = `${fin}${fin ? ' ' : ''}${inter}`.replace(/\s+/g, ' ').trim()
    interimRef.current = ''
  }

  const finishListening = (sendText, { forceSend = false, quiet = false } = {}) => {
    // Snapshot FIRST — stop() races onend; never abort() here (abort drops finals)
    foldInterimIntoFinal()
    const snapped = String(
      sendText != null && String(sendText).trim() ? sendText : combinedTranscript(),
    ).trim()

    wantListenRef.current = false
    listeningRef.current = false
    if (mountedRef.current) setListening(false)
    clearTimers()
    if (lateResultTimerRef.current) {
      clearTimeout(lateResultTimerRef.current)
      lateResultTimerRef.current = null
    }
    const rec = recRef.current
    recRef.current = null
    // stop() only — abort() discards the last utterance on Chrome/Android
    try { rec?.stop?.() } catch { /* ignore */ }
    stopVolumeMeter()
    releaseKeepAwake().catch(() => {})

    // Late finals sometimes arrive after stop; wait briefly then merge
    const deliver = () => {
      foldInterimIntoFinal()
      const text = (snapped || combinedTranscript()).trim()

      if (mountedRef.current) setPartial(text || '')
      finalRef.current = ''
      interimRef.current = ''
      heardSpeechRef.current = false

      // Always put text in the composer so user can edit/send if auto-send fails
      if (text) {
        try { onPartialRef.current?.(text) } catch { /* ignore */ }
      }

      if (!text) {
        if (!quiet) {
          hapticSelect()
          message.info('No speech captured — speak, wait for words under the mic, then tap Send')
        }
        if (mountedRef.current) setPartial('')
        return
      }
      meterVoice('voice_stt', text).catch(() => {})
      if ((autoSend || forceSend) && onTranscriptRef.current) {
        try {
          hapticMedium()
          onTranscriptRef.current(text)
          hapticSuccess()
        } catch (e) {
          hapticError()
          message.warning(e?.message || 'Voice text is in the box — tap Send')
        }
      } else {
        hapticLight()
        message.success('Voice text ready in the box — tap Send')
      }
      if (mountedRef.current) setPartial('')
    }

    // Give the engine ~180ms to flush final results after stop()
    lateResultTimerRef.current = setTimeout(deliver, 180)
  }
  finishRef.current = finishListening

  const armSilenceTimer = () => {
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
    if (!heardSpeechRef.current) return
    // Mobile: longer pause so multi-word phrases aren't cut mid-sentence
    const base = continuousRef.current ? silenceMs : Math.max(silenceMs, 2800)
    silenceTimerRef.current = setTimeout(() => {
      if (wantListenRef.current) finishRef.current?.()
    }, clampNum(base, 1200, 30000, 3500))
  }

  const startRecognitionEngine = (langOverride) => {
    const SR = getSpeechRecognition()
    if (!SR || !wantListenRef.current) return false
    const langs = []
    const primary = normalizeSpeechLang(langOverride || speechLang)
    langs.push(primary)
    if (primary !== 'en-US') langs.push('en-US')
    if (primary !== 'en-GB') langs.push('en-GB')

    for (const useLang of langs) {
      for (const continuous of [!!continuousRef.current, false]) {
        try {
          // stop any prior instance
          try { recRef.current?.stop?.() } catch { /* ignore */ }
          recRef.current = null
          const rec = new SR()
          rec.lang = useLang
          rec.interimResults = true
          rec.continuous = continuous
          rec.maxAlternatives = 3
          attachRecHandlers(rec)
          recRef.current = rec
          rec.start()
          continuousRef.current = continuous
          listeningRef.current = true
          if (mountedRef.current) setListening(true)
          return true
        } catch {
          /* try next combo */
        }
      }
    }
    console.warn('[voice] start failed for all lang/continuous combos')
    return false
  }

  const attachRecHandlers = (rec) => {
    rec.onstart = () => {
      listeningRef.current = true
      if (mountedRef.current) setListening(true)
    }
    rec.onerror = (ev) => {
      const err = ev?.error || ''
      if (err === 'not-allowed' || err === 'service-not-allowed') {
        hapticError()
        message.error('Mic / speech blocked. Allow microphone for this site (Chrome works best).')
        wantListenRef.current = false
        finishRef.current?.('', { quiet: true })
        return
      }
      if (err === 'network') {
        // Google STT backend unreachable — keep trying non-continuous restarts
        continuousRef.current = false
        return
      }
      // aborted: ignore (we called stop)
      // no-speech: engine ends; onend will restart if still listening
      if (err === 'aborted' || err === 'no-speech') return
      if (err === 'audio-capture') {
        hapticError()
        message.error('No microphone found, or another app is using the mic.')
        wantListenRef.current = false
        finishRef.current?.('', { quiet: true })
      }
      if (err === 'language-not-supported') {
        continuousRef.current = false
        // Restart with en-US on next onend cycle
        try { rec.lang = 'en-US' } catch { /* ignore */ }
      }
    }
    rec.onend = () => {
      foldInterimIntoFinal()
      // Brief wait so a late onresult can land before restart
      if (wantListenRef.current) {
        restartTimerRef.current = setTimeout(() => {
          if (!wantListenRef.current) return
          // Prefer non-continuous after first cycle if we heard nothing
          if (!heardSpeechRef.current && continuousRef.current) {
            continuousRef.current = false
          }
          if (!startRecognitionEngine()) {
            // If we have text, finish with it; else keep trying once more en-US
            if (combinedTranscript()) {
              finishRef.current?.()
            } else if (!startRecognitionEngine('en-US')) {
              finishRef.current?.()
            }
          }
        }, continuousRef.current ? 200 : 120)
        return
      }
      listeningRef.current = false
      if (mountedRef.current) setListening(false)
    }
    rec.onresult = (event) => {
      try {
        let interim = ''
        // Scan full result list (not only resultIndex) — some mobile engines
        // re-emit earlier finals or only interim until stop
        const start = continuousRef.current ? event.resultIndex : 0
        if (!continuousRef.current) {
          // One-shot session: rebuild entire session transcript
          let sessionFinal = ''
          for (let i = 0; i < event.results.length; i++) {
            const r = event.results[i]
            if (!r) continue
            const t = String(r[0]?.transcript || r[1]?.transcript || '')
            if (!t.trim()) continue
            if (r.isFinal) sessionFinal += (sessionFinal ? ' ' : '') + t.trim()
            else interim += t
          }
          if (sessionFinal) {
            // One-shot: sessionFinal is the whole utterance so far
            const base = String(finalRef.current || '').trim()
            // Avoid duplicating if engine re-sends same final
            if (!base.endsWith(sessionFinal)) {
              finalRef.current = `${base}${base ? ' ' : ''}${sessionFinal}`.replace(/\s+/g, ' ').trim()
            }
            heardSpeechRef.current = true
          }
          if (interim.trim()) heardSpeechRef.current = true
          interimRef.current = interim
        } else {
          for (let i = start; i < event.results.length; i++) {
            const r = event.results[i]
            if (!r) continue
            const t = String(r[0]?.transcript || r[1]?.transcript || '')
            if (!t) continue
            if (r.isFinal) {
              const fin = String(finalRef.current || '').trim()
              const piece = t.trim()
              if (piece && !fin.endsWith(piece)) {
                finalRef.current = `${fin}${fin ? ' ' : ''}${piece}`.replace(/\s+/g, ' ')
              }
              heardSpeechRef.current = true
            } else {
              interim += t
              if (t.trim()) heardSpeechRef.current = true
            }
          }
          interimRef.current = interim
        }
      } catch { /* ignore malformed result */ }
      const display = combinedTranscript()
      if (mountedRef.current) setPartial(display)
      try { onPartialRef.current?.(display) } catch { /* ignore parent errors */ }
      // Fake meter pulse when speech heard (no second mic stream)
      if (heardSpeechRef.current && mobileMicRef.current && mountedRef.current) {
        const pulse = IDLE_LEVELS().map((_, i) => 0.25 + 0.55 * Math.abs(Math.sin(Date.now() / 120 + i)))
        setLevels(pulse)
      }
      armSilenceTimer()
    }
  }

  const hardStopMic = () => {
    wantListenRef.current = false
    listeningRef.current = false
    clearTimers()
    if (lateResultTimerRef.current) {
      clearTimeout(lateResultTimerRef.current)
      lateResultTimerRef.current = null
    }
    try { recRef.current?.stop?.() } catch { /* ignore */ }
    // abort only after stop when discarding session
    try { recRef.current?.abort?.() } catch { /* ignore */ }
    recRef.current = null
    stopVolumeMeter()
    releaseKeepAwake().catch(() => {})
    if (mountedRef.current) {
      setListening(false)
      setPartial('')
    }
    finalRef.current = ''
    interimRef.current = ''
  }

  const startListen = async () => {
    if (disabled) return
    const SR = getSpeechRecognition()
    if (!SR) {
      hapticError()
      message.warning('Voice needs Chrome or Edge on this device (speech recognition unavailable).')
      return
    }
    hapticLight()
    stopSpeaking()
    if (mountedRef.current) setSpeaking(false)
    finalRef.current = ''
    interimRef.current = ''
    if (mountedRef.current) setPartial('')
    heardSpeechRef.current = false
    wantListenRef.current = true
    mobileMicRef.current = prefersNonContinuousSpeech()
    continuousRef.current = !mobileMicRef.current
    clearTimers()
    acquireKeepAwake('mic').catch(() => {})

    // Request mic permission once. Do NOT open a second stream for meters on
    // mobile — that steals the mic from SpeechRecognition (empty transcripts).
    try {
      if (navigator.mediaDevices?.getUserMedia) {
        const probe = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
          video: false,
        })
        if (mobileMicRef.current) {
          // Release immediately so STT owns the mic exclusively
          try { probe.getTracks?.().forEach((t) => t.stop()) } catch { /* ignore */ }
        } else {
          // Desktop: stop probe, then volume meter can open its own stream
          try { probe.getTracks?.().forEach((t) => t.stop()) } catch { /* ignore */ }
          startVolumeMeter()
        }
      } else if (!mobileMicRef.current) {
        startVolumeMeter()
      }
    } catch {
      hapticError()
      message.error('Microphone permission denied. Allow the mic for this site, then try again.')
      hardStopMic()
      return
    }

    maxTimerRef.current = setTimeout(() => {
      if (wantListenRef.current) {
        message.info('Mic stopped after the time limit — tap again to continue')
        finishRef.current?.()
      }
    }, clampNum(maxListenMs, 5000, 600000, 120000))

    // Start STT after a tick so released probe tracks fully free the device
    const kick = () => {
      if (!wantListenRef.current) return
      if (!startRecognitionEngine()) {
        // Last try: en-US non-continuous
        continuousRef.current = false
        if (!startRecognitionEngine('en-US')) {
          message.error('Could not start speech recognition — use Chrome, check mic permission, reload')
          hardStopMic()
          return
        }
      }
      message.info('Listening — speak now. Tap Send when done.', 2)
    }
    setTimeout(kick, mobileMicRef.current ? 120 : 40)
  }

  const toggleMic = () => {
    if (listening || wantListenRef.current) {
      hapticSelect()
      finishRef.current?.()
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
                  hapticSelect()
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
          {partial
            ? `Hearing: “${partial.slice(0, 72)}${partial.length > 72 ? '…' : ''}”`
            : 'Listening — speak now…'}
        </Tag>
      )}

      {/* Explicit Send while talking — stops mic and sends to the agent */}
      {listening && (
        <Button
          type="primary"
          size="large"
          icon={<SendOutlined />}
          className="aba-voice-send-btn"
          onClick={() => {
            hapticMedium()
            finishListening(undefined, { forceSend: true })
          }}
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
