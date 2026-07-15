/** Shared model catalog for every picker in the app. */

export const FALLBACK_MODELS = [
  // VPS
  { value: 'vps-fast', label: 'Our VPS – Fast', group: 'vps', group_label: 'Our VPS', provider: 'ollama' },
  { value: 'vps-quality', label: 'Our VPS – Quality', group: 'vps', group_label: 'Our VPS', provider: 'ollama' },
  // Qwen
  { value: 'vps-qwen-fast', label: 'Our VPS – Qwen Fast', group: 'qwen', group_label: 'Our VPS – Qwen', provider: 'ollama' },
  { value: 'vps-qwen-7b', label: 'Our VPS – Qwen 7B', group: 'qwen', group_label: 'Our VPS – Qwen', provider: 'ollama' },
  { value: 'vps-qwen-14b', label: 'Our VPS – Qwen 14B', group: 'qwen', group_label: 'Our VPS – Qwen', provider: 'ollama' },
  { value: 'vps-qwen-32b', label: 'Our VPS – Qwen 32B', group: 'qwen', group_label: 'Our VPS – Qwen', provider: 'ollama' },
  { value: 'vps-qwen-coder', label: 'Our VPS – Qwen Coder', group: 'qwen', group_label: 'Our VPS – Qwen', provider: 'ollama' },
  { value: 'vps-qwen-coder-7b', label: 'Our VPS – Qwen Coder 7B', group: 'qwen', group_label: 'Our VPS – Qwen', provider: 'ollama' },
  { value: 'vps-qwen-coder-14b', label: 'Our VPS – Qwen Coder 14B', group: 'qwen', group_label: 'Our VPS – Qwen', provider: 'ollama' },
  { value: 'vps-qwen-coder-32b', label: 'Our VPS – Qwen Coder 32B', group: 'qwen', group_label: 'Our VPS – Qwen', provider: 'ollama' },
  { value: 'vps-qwen-large', label: 'Our VPS – Qwen Large', group: 'qwen', group_label: 'Our VPS – Qwen', provider: 'ollama' },
  { value: 'vps-qwen-72b', label: 'Our VPS – Qwen 72B', group: 'qwen', group_label: 'Our VPS – Qwen', provider: 'ollama' },
  // Claude
  { value: 'claude-haiku', label: 'Premium Claude Haiku', group: 'anthropic', group_label: 'Premium Claude', provider: 'anthropic' },
  { value: 'claude-sonnet', label: 'Premium Claude Sonnet', group: 'anthropic', group_label: 'Premium Claude', provider: 'anthropic' },
  { value: 'claude-opus', label: 'Premium Claude Opus', group: 'anthropic', group_label: 'Premium Claude', provider: 'anthropic' },
  // Grok
  { value: 'grok-fast', label: 'Premium xAI Grok Fast', group: 'xai', group_label: 'Premium xAI Grok', provider: 'xai' },
  { value: 'grok-mini', label: 'Premium xAI Grok Mini', group: 'xai', group_label: 'Premium xAI Grok', provider: 'xai' },
  { value: 'grok', label: 'Premium xAI Grok', group: 'xai', group_label: 'Premium xAI Grok', provider: 'xai' },
  { value: 'grok-2', label: 'Premium xAI Grok 2', group: 'xai', group_label: 'Premium xAI Grok', provider: 'xai' },
  { value: 'grok-3', label: 'Premium xAI Grok 3', group: 'xai', group_label: 'Premium xAI Grok', provider: 'xai' },
  { value: 'grok-4', label: 'Premium xAI Grok 4', group: 'xai', group_label: 'Premium xAI Grok', provider: 'xai' },
]

let _cache = null
let _loading = null

export function modelLabel(id) {
  const m = (_cache || FALLBACK_MODELS).find(x => x.value === id || x.id === id)
  return m?.label || id
}

/** Ant Design Select options with optgroups */
export function modelSelectOptions(models = FALLBACK_MODELS) {
  const list = models.map(m => ({
    value: m.value || m.id,
    label: m.rate_per_1m != null
      ? `${m.label}  ·  $${Number(m.rate_per_1m).toFixed(2)}/1M`
      : m.label,
    group: m.group || m.group_label || 'Other',
    group_label: m.group_label || m.group || 'Other',
    configured: m.configured !== false,
  }))
  const groups = []
  const seen = new Map()
  for (const opt of list) {
    const g = opt.group_label
    if (!seen.has(g)) {
      seen.set(g, { label: g, options: [] })
      groups.push(seen.get(g))
    }
    seen.get(g).options.push({
      value: opt.value,
      label: opt.label,
      disabled: opt.configured === false && (opt.value.startsWith('claude') || opt.value.startsWith('grok'))
        ? false // still selectable — falls back
        : false,
    })
  }
  return groups
}

/** Flat {value,label}[] for simple Selects */
export function modelFlatOptions(models = FALLBACK_MODELS) {
  return models.map(m => ({
    value: m.value || m.id,
    label: m.label,
  }))
}

/**
 * Load full catalog from API once. Safe to call from many components.
 * @returns {Promise<{models: array, groups: array}>}
 */
export async function loadModels(apiFn) {
  if (_cache) return { models: _cache, groups: [] }
  if (_loading) return _loading
  _loading = (async () => {
    try {
      const data = await apiFn('/system/models')
      const models = (data.models || data || []).map(m => ({
        value: m.id || m.value,
        id: m.id || m.value,
        label: m.label,
        group: m.group,
        group_label: m.group_label,
        provider: m.provider,
        rate_per_1m: m.rate_per_1m,
        configured: m.configured,
      }))
      _cache = models.length ? models : FALLBACK_MODELS
      return { models: _cache, groups: data.groups || [] }
    } catch {
      _cache = FALLBACK_MODELS
      return { models: _cache, groups: [] }
    } finally {
      _loading = null
    }
  })()
  return _loading
}

export function clearModelCache() {
  _cache = null
}
