/** Shared helpers for Settings tabs */

export function StatusTagProps(ok) {
  return {
    color: ok ? 'success' : 'default',
    text: ok ? 'live' : 'not configured',
  }
}

export function connStatusColor(s) {
  if (s === 'connected') return 'success'
  if (s === 'pending') return 'processing'
  if (s === 'error') return 'error'
  return 'default'
}

export function partitionKeys(keys, providers) {
  const byId = Object.fromEntries((providers || []).map((p) => [p.id, p]))
  const llm = []
  const channels = []
  const other = []
  for (const k of keys || []) {
    const cat = byId[k.provider]?.category
    if (!cat || cat === 'llm') llm.push(k)
    else if (cat === 'channels') channels.push(k)
    else other.push(k)
  }
  // Fallback when providers empty
  if (!providers?.length) {
    return {
      llm: (keys || []).filter((k) => ['anthropic', 'xai', 'openai', 'google'].includes(k.provider)),
      channels: (keys || []).filter((k) => String(k.provider).startsWith('twilio') || k.provider === 'resend'),
      other: [],
    }
  }
  return { llm, channels, other }
}
