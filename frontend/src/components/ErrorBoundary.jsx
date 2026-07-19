import React from 'react'
import { Button, Result, Space, Typography } from 'antd'
import { ReloadOutlined, HomeOutlined } from '@ant-design/icons'

/**
 * Catch React render crashes so the whole app does not white-screen.
 * Use around the shell and around heavy lazy pages.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null, info: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    this.setState({ info })
    try {
      console.error('[ErrorBoundary]', error, info?.componentStack)
    } catch { /* ignore */ }
    try {
      this.props.onError?.(error, info)
    } catch { /* ignore */ }
    // Stale JS chunks after deploy: one automatic reload (session-scoped)
    try {
      const msg = String(error?.message || error || '')
      if (
        /Loading chunk|Failed to fetch dynamically imported module|Importing a module script failed|ChunkLoadError/i.test(
          msg,
        )
      ) {
        const key = 'aba_chunk_reload_v1'
        if (typeof sessionStorage !== 'undefined' && !sessionStorage.getItem(key)) {
          sessionStorage.setItem(key, '1')
          window.location.reload()
        }
      }
    } catch { /* ignore */ }
  }

  componentDidUpdate(prevProps) {
    // Allow parent to reset via key=pathname; also support resetKey prop
    if (
      this.state.error
      && this.props.resetKey != null
      && prevProps.resetKey !== this.props.resetKey
    ) {
      this.setState({ error: null, info: null })
    }
  }

  reset = () => {
    this.setState({ error: null, info: null })
    try {
      this.props.onReset?.()
    } catch { /* ignore */ }
  }

  hardReload = () => {
    try {
      window.location.reload()
    } catch {
      this.reset()
    }
  }

  goHome = () => {
    try {
      const base = (import.meta.env.BASE_URL || '/').replace(/\/+$/, '') || ''
      window.location.href = `${base}/` || '/'
    } catch {
      window.location.href = '/'
    }
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    const title = this.props.title || 'Something went wrong'
    const msg = String(error?.message || error || 'Unexpected error')
    const compact = !!this.props.compact

    if (compact) {
      return (
        <div
          role="alert"
          style={{
            padding: 16,
            textAlign: 'center',
            border: '1px solid #fecaca',
            background: '#fef2f2',
            borderRadius: 12,
            margin: 8,
          }}
        >
          <Typography.Text type="danger" strong style={{ display: 'block', marginBottom: 8 }}>
            {title}
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
            {msg.slice(0, 180)}
          </Typography.Text>
          <Space wrap>
            <Button size="small" type="primary" icon={<ReloadOutlined />} onClick={this.reset}>
              Try again
            </Button>
            <Button size="small" icon={<ReloadOutlined />} onClick={this.hardReload}>
              Reload
            </Button>
          </Space>
        </div>
      )
    }

    return (
      <div
        style={{
          minHeight: this.props.fullPage ? '100dvh' : 320,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 24,
          background: this.props.fullPage ? '#f1f5f9' : 'transparent',
        }}
      >
        <Result
          status="error"
          title={title}
          subTitle={msg.slice(0, 240)}
          extra={
            <Space wrap>
              <Button type="primary" icon={<ReloadOutlined />} onClick={this.reset}>
                Try again
              </Button>
              <Button icon={<ReloadOutlined />} onClick={this.hardReload}>
                Reload page
              </Button>
              <Button icon={<HomeOutlined />} onClick={this.goHome}>
                Home
              </Button>
            </Space>
          }
        />
      </div>
    )
  }
}
