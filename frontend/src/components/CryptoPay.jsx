import React, { useEffect, useState } from 'react'
import {
  Modal, Select, Button, Space, Typography, Alert, Input, message, Spin, Tag, Divider, Descriptions,
} from 'antd'
import { CopyOutlined, CheckCircleOutlined } from '@ant-design/icons'
import { api } from '../api'

const CHAIN_LABELS = {
  eth: 'Ethereum (ETH)',
  sol: 'Solana (SOL)',
  xrp: 'XRP Ledger (XRP)',
}

/**
 * Crypto payment modal for plan or top-up (ETH / SOL / XRP).
 *
 * props:
 *  open, onClose
 *  kind: 'plan' | 'topup'
 *  plan?: string
 *  companyName?: string
 *  amount?: number  (topup USD)
 *  onPaid: (result) => void
 */
export default function CryptoPay({
  open, onClose, kind = 'plan', plan, companyName, amount, onPaid,
}) {
  const [options, setOptions] = useState(null)
  const [chain, setChain] = useState(null)
  const [invoice, setInvoice] = useState(null)
  const [txHash, setTxHash] = useState('')
  const [busy, setBusy] = useState(false)
  const [verifying, setVerifying] = useState(false)

  useEffect(() => {
    if (!open) return
    setInvoice(null)
    setTxHash('')
    api('/billing/crypto/options')
      .then((o) => {
        setOptions(o)
        const first = (o.chains || [])[0]?.id
        setChain(first || null)
      })
      .catch((e) => message.error(e.message || 'Could not load crypto options'))
  }, [open])

  const createInvoice = async () => {
    if (!chain) {
      message.warning('Select a chain')
      return
    }
    setBusy(true)
    try {
      const body = { chain, kind }
      if (kind === 'plan') {
        body.plan = plan
        if (companyName) body.company_name = companyName
      } else {
        body.amount = amount
      }
      const inv = await api('/billing/crypto/invoice', { method: 'POST', body })
      if (inv.activated) {
        message.success('Plan activated')
        onPaid?.(inv)
        onClose?.()
        return
      }
      setInvoice(inv)
    } catch (e) {
      message.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  const verify = async () => {
    if (!invoice?.public_id) return
    setVerifying(true)
    try {
      const r = await api(`/billing/crypto/invoice/${invoice.public_id}/verify`, {
        method: 'POST',
        body: { tx_hash: txHash || undefined },
      })
      message.success('Payment confirmed on-chain')
      setInvoice(r.invoice)
      onPaid?.(r)
      onClose?.()
    } catch (e) {
      message.error(e.message)
    } finally {
      setVerifying(false)
    }
  }

  const copy = async (text, label) => {
    try {
      await navigator.clipboard.writeText(String(text))
      message.success(`${label} copied`)
    } catch {
      message.info(String(text))
    }
  }

  const chains = options?.chains || []
  const priceHint = options?.prices_usd?.[chain]

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={kind === 'topup' ? 'Pay with crypto (top-up)' : 'Pay with crypto'}
      footer={null}
      destroyOnClose
      width={560}
    >
      {!options ? (
        <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div>
      ) : !options.enabled || !chains.length ? (
        <Alert
          type="warning"
          showIcon
          message="Crypto payments not configured"
          description="Set CRYPTO_ETH_ADDRESS, CRYPTO_SOL_ADDRESS, and/or CRYPTO_XRP_ADDRESS in the server environment."
        />
      ) : !invoice ? (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            Pay with native <strong>ETH</strong>, <strong>SOL</strong>, or <strong>XRP</strong>.
            Send from your wallet to our address, then paste the transaction hash to unlock instantly.
          </Typography.Paragraph>
          {kind === 'plan' && (
            <Alert type="info" showIcon message={`Plan: ${plan} · charged as one-time monthly equivalent in crypto`} />
          )}
          {kind === 'topup' && (
            <Alert type="info" showIcon message={`Top-up amount: $${Number(amount || 0).toFixed(2)} USD`} />
          )}
          <div>
            <Typography.Text strong>Network</Typography.Text>
            <Select
              style={{ width: '100%', marginTop: 6 }}
              value={chain}
              onChange={setChain}
              options={chains.map((c) => ({
                value: c.id,
                label: `${CHAIN_LABELS[c.id] || c.name}${c.usd_price ? ` · $${Number(c.usd_price).toLocaleString()}` : ''}`,
              }))}
            />
            {priceHint ? (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Live price ≈ ${Number(priceHint).toLocaleString()} USD per coin (CoinGecko)
              </Typography.Text>
            ) : null}
          </div>
          <Button type="primary" block size="large" loading={busy} onClick={createInvoice}>
            Create crypto invoice
          </Button>
        </Space>
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Tag color={invoice.status === 'paid' ? 'success' : 'processing'}>
            {invoice.status?.toUpperCase()} · {invoice.public_id}
          </Tag>
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="Network">{invoice.network}</Descriptions.Item>
            <Descriptions.Item label="Amount">
              <Typography.Text copyable={{ text: String(invoice.amount_crypto) }} strong>
                {invoice.amount_crypto} {invoice.asset_symbol}
              </Typography.Text>
              <Typography.Text type="secondary"> (${invoice.amount_usd} USD)</Typography.Text>
            </Descriptions.Item>
            <Descriptions.Item label="Address">
              <Space wrap>
                <Typography.Text code style={{ wordBreak: 'break-all' }}>
                  {invoice.receive_address}
                </Typography.Text>
                <Button
                  size="small"
                  icon={<CopyOutlined />}
                  onClick={() => copy(invoice.receive_address, 'Address')}
                />
              </Space>
            </Descriptions.Item>
            {invoice.dest_tag != null && (
              <Descriptions.Item label="Destination tag">
                <Typography.Text type="danger" strong>
                  {invoice.dest_tag}
                </Typography.Text>
                <Button
                  size="small"
                  style={{ marginLeft: 8 }}
                  icon={<CopyOutlined />}
                  onClick={() => copy(invoice.dest_tag, 'Tag')}
                />
                <div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    Required for XRP — omit the tag and payment cannot be matched.
                  </Typography.Text>
                </div>
              </Descriptions.Item>
            )}
            {invoice.expires_at && (
              <Descriptions.Item label="Expires">{invoice.expires_at}</Descriptions.Item>
            )}
          </Descriptions>

          <Alert
            type="warning"
            showIcon
            message="Send the exact amount"
            description={
              <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
                {(invoice.instructions || []).map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            }
          />

          <Divider style={{ margin: '8px 0' }} />

          <div>
            <Typography.Text strong>Transaction hash / signature</Typography.Text>
            <Input
              style={{ marginTop: 6 }}
              placeholder={
                invoice.chain === 'sol'
                  ? 'Solana transaction signature'
                  : invoice.chain === 'xrp'
                    ? 'XRP transaction hash'
                    : '0x… Ethereum tx hash'
              }
              value={txHash}
              onChange={(e) => setTxHash(e.target.value)}
            />
            {invoice.chain === 'xrp' && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                For XRP you can leave this blank and we will try to match by destination tag.
              </Typography.Text>
            )}
          </div>

          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Button
              onClick={async () => {
                try {
                  await api(`/billing/crypto/invoice/${invoice.public_id}/cancel`, { method: 'POST' })
                } catch { /* ignore */ }
                setInvoice(null)
              }}
            >
              Cancel / new invoice
            </Button>
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              loading={verifying}
              onClick={verify}
            >
              I paid — verify on-chain
            </Button>
          </Space>
        </Space>
      )}
    </Modal>
  )
}
