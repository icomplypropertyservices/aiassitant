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
    loadModels(api).then(({ models: m }) => setModels(m))
  }, [])

  const options = showRates
    ? modelSelectOptions(models)
    : modelSelectOptions(models.map(m => ({ ...m, rate_per_1m: undefined })))

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
