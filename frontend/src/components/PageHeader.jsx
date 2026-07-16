import React from 'react'
import { Space } from 'antd'

/** Consistent page title + optional actions */
export default function PageHeader({ title, subtitle, extra, style }) {
  return (
    <div className="aba-page-header" style={style}>
      <div>
        <h1>{title}</h1>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {extra ? <Space wrap>{extra}</Space> : null}
    </div>
  )
}
