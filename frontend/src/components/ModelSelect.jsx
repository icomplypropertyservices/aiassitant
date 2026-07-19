import React, { useEffect, useState } from 'react'
import { Select } from 'antd'
import { api } from '../api'
import { FALLBACK_MODELS, loadModels, modelSelectOptions } from '../models'

/**
 * Full model picker used everywhere (chat, agents, settings).
 * Loads all models from GET /system/models; falls back to local catalog.
 */
export default function ModelSelect({
  value,
  onChange,
  style,
  size,
  placeholder = 'Select model',
  allowClear = false,
  disabled = false,
  showRates = true,
}) {
  const [models, setModels] = useState(FALLBACK_MODELS)

  useEffect(() => {
    loadModels(api).then(({ models: m }) => setModels(Array.isArray(m) && m.length ? m : FALLBACK_MODELS))
  }, [])

  const safeModels = Array.isArray(models) ? models : FALLBACK_MODELS
  const options = showRates
    ? modelSelectOptions(safeModels)
    : modelSelectOptions(safeModels.map(m => ({ ...m, rate_per_1m: undefined })))

  return (
    <Select
      value={value}
      onChange={onChange}
      options={options}
      style={{ minWidth: 280, ...style }}
      size={size}
      placeholder={placeholder}
      allowClear={allowClear}
      disabled={disabled}
      showSearch
      optionFilterProp="label"
      popupMatchSelectWidth={false}
      listHeight={360}
    />
  )
}

export function useModelOptions() {
  const [models, setModels] = useState(FALLBACK_MODELS)
  useEffect(() => {
    loadModels(api).then(({ models: m }) => setModels(m))
  }, [])
  return models
}
