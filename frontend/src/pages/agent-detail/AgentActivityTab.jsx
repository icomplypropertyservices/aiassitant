import React from 'react'
import { Card, Timeline, Typography } from 'antd'
import { ICONS } from './constants'

/** Agent manage page — Live activity tab body. */
export default function AgentActivityTab({ agent }) {
  return (
    <Card
      bordered
      size="small"
      className="aba-soft-card"
      title="Activity feed"
      styles={{ body: { padding: 0 } }}
    >
      <div style={{ maxHeight: 480, overflowY: 'auto', background: '#0f172a', borderRadius: '0 0 12px 12px', padding: 16 }}>
        <Timeline
          items={(agent.activity || []).map((entry) => ({
            dot: ICONS[entry.type] || ICONS.info,
            children: (
              <span style={{ color: '#e2e8f0', fontSize: 13, fontFamily: 'ui-monospace, monospace' }}>
                {entry.message}
                <Typography.Text style={{ color: '#64748b', marginLeft: 8, fontSize: 11 }}>
                  {entry.created_at ? new Date(entry.created_at).toLocaleTimeString() : ''}
                </Typography.Text>
              </span>
            ),
          }))}
        />
        {(!agent.activity || !agent.activity.length) && (
          <Typography.Text style={{ color: '#94a3b8' }}>Waiting for activity…</Typography.Text>
        )}
      </div>
    </Card>
  )
}
