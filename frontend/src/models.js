/** Shared model catalog for every picker in the app.
 *  Clients only see neutral names. All routing and provider details are hidden.
 */

export const FALLBACK_MODELS = [
  // Clean, neutral names shown to clients.
  { value: 'fast', label: 'Fast', group: 'managed', group_label: 'Managed', provider: 'managed' },
  { value: 'quality', label: 'Quality', group: 'managed', group_label: 'Managed', provider: 'managed' },
  { value: 'reasoning', label: 'Reasoning', group: 'managed', group_label: 'Managed', provider: 'managed' },
  { value: 'large', label: 'Large Context', group: 'managed', group_label: 'Managed', provider: 'managed' },
  { value: 'small', label: 'Small', group: 'managed', group_label: 'Managed', provider: 'managed' },
  { value: 'medium', label: 'Medium', group: 'managed', group_label: 'Managed', provider: 'managed' },
  // Media (also billed every use)
  { value: 'image', label: 'Image', group: 'media', group_label: 'Media', provider: 'managed' },
  { value: 'video', label: 'Video', group: 'media', group_label: 'Media', provider: 'managed' },
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
