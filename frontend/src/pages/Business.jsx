import React, { useEffect, useState } from 'react'
import {
  Card, Tabs, Button, Space, Typography, Form, message, Spin,
} from 'antd'
import {
  ShopOutlined, PlusOutlined, ReloadOutlined, CalendarOutlined,
  ShoppingOutlined, BankOutlined, CloudSyncOutlined,
} from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/PageHeader'
import PageShell from '../components/PageShell'
import BusinessProductsTab, { productsTabLabel } from './business/BusinessProductsTab'
import BusinessOverviewTab from './business/BusinessOverviewTab'
import BusinessCustomersTab, { customersTabLabel } from './business/BusinessCustomersTab'
import BusinessPipelineTab from './business/BusinessPipelineTab'
import BusinessDiaryModal from './business/BusinessDiaryModal'
import BusinessCustomerModal from './business/BusinessCustomerModal'
import BusinessProductModal from './business/BusinessProductModal'
import BusinessDealModal from './business/BusinessDealModal'
import BusinessPipelineModal from './business/BusinessPipelineModal'
import BusinessStatsRow from './business/BusinessStatsRow'

const { Text } = Typography

export default function Business() {
  const nav = useNavigate()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') || 'overview'
  const setTab = (k) => {
    const n = new URLSearchParams(params)
    n.set('tab', k)
    setParams(n)
  }

  const [loading, setLoading] = useState(true)
  const [overview, setOverview] = useState(null)
  const [customers, setCustomers] = useState([])
  const [total, setTotal] = useState(0)
  const [products, setProducts] = useState([])
  const [productTotal, setProductTotal] = useState(0)
  const [pipelines, setPipelines] = useState([])
  const [board, setBoard] = useState(null)
  const [pipelineId, setPipelineId] = useState(null)
  const [q, setQ] = useState('')
  const [statusFilter, setStatusFilter] = useState(undefined)
  const [productQ, setProductQ] = useState('')
  const [productStatus, setProductStatus] = useState(undefined)
  const [humans, setHumans] = useState([])
  const [agents, setAgents] = useState([])
  const [companies, setCompanies] = useState([])
  const [customerTagPresets, setCustomerTagPresets] = useState([
    'vip', 'enterprise', 'smb', 'startup', 'lead', 'partner', 'churn-risk', 'renewing', 'trial',
  ])
  const [productTagPresets, setProductTagPresets] = useState([
    'core', 'addon', 'featured', 'service', 'digital', 'physical', 'subscription', 'bundle', 'new', 'sale',
  ])

  const [custOpen, setCustOpen] = useState(false)
  const [productOpen, setProductOpen] = useState(false)
  const [dealOpen, setDealOpen] = useState(false)
  const [pipeOpen, setPipeOpen] = useState(false)
  const [diaryOpen, setDiaryOpen] = useState(false)
  const [selectedCustForDiary, setSelectedCustForDiary] = useState(null)
  const [custForm] = Form.useForm()
  const [productForm] = Form.useForm()
  const [dealForm] = Form.useForm()
  const [pipeForm] = Form.useForm()
  const [diaryForm] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [dragDeal, setDragDeal] = useState(null)
  const [upcomingDiary, setUpcomingDiary] = useState([])
  const [editingProduct, setEditingProduct] = useState(null)
  const [shopifySyncing, setShopifySyncing] = useState(false)
  const [hasShopify, setHasShopify] = useState(false)

  const defaultCompanyId = companies[0]?.id

  const syncShopify = async (what = 'all') => {
    if (!companies.length) {
      message.warning('Create a company in Workspace first — Shopify data must link to your company')
      nav('/workspace')
      return
    }
    setShopifySyncing(true)
    try {
      const r = await api('/business/shopify/sync', {
        method: 'POST',
        body: {
          what,
          company_id: defaultCompanyId,
          limit: 50,
        },
      })
      if (r.ok === false) {
        message.error(r.error || r.message || 'Shopify sync failed — connect Shopify under Settings → Connected apps')
        return
      }
      message.success(r.message || 'Shopify sync complete')
      await Promise.all([loadCustomers(), loadProducts(), loadOverview()])
    } catch (e) {
      message.error(e.message || 'Shopify sync failed')
    } finally {
      setShopifySyncing(false)
    }
  }

  const pushProductShopify = async (id) => {
    try {
      const r = await api(`/business/products/${id}/push-shopify`, { method: 'POST' })
      if (r.ok === false) {
        message.error(r.error || 'Push failed')
        return
      }
      message.success(r.message || 'Pushed tags to Shopify')
    } catch (e) {
      message.error(e.message)
    }
  }

  const loadOverview = async () => {
    const o = await api('/business/overview')
    setOverview(o)
    setPipelines(o.pipelines || [])
    if (o.companies?.length) setCompanies(o.companies)
    if (o.tag_presets?.customer) setCustomerTagPresets(o.tag_presets.customer)
    if (o.tag_presets?.product) setProductTagPresets(o.tag_presets.product)
    if (!pipelineId && o.pipelines?.length) {
      const def = o.pipelines.find((p) => p.is_default) || o.pipelines[0]
      setPipelineId(def.id)
    }
  }

  const loadCustomers = async () => {
    const qs = new URLSearchParams()
    if (q) qs.set('q', q)
    if (statusFilter) qs.set('status', statusFilter)
    const r = await api(`/business/customers?${qs.toString()}`)
    setCustomers(r.customers || [])
    setTotal(r.total || 0)
  }

  const loadProducts = async () => {
    const qs = new URLSearchParams()
    if (productQ) qs.set('q', productQ)
    if (productStatus) qs.set('status', productStatus)
    const r = await api(`/business/products?${qs.toString()}`)
    setProducts(r.products || [])
    setProductTotal(r.total || 0)
    if (r.tag_presets?.length) setProductTagPresets(r.tag_presets)
  }

  const loadBoard = async (pid) => {
    const id = pid || pipelineId
    if (!id) return
    const r = await api(`/business/pipelines/${id}`)
    setBoard(r)
  }

  const load = async () => {
    setLoading(true)
    try {
      const o = await api('/business/overview')
      setOverview(o)
      setPipelines(o.pipelines || [])
      if (!pipelineId && o.pipelines?.length) {
        const def = o.pipelines.find((p) => p.is_default) || o.pipelines[0]
        setPipelineId(def.id)
      }
      if (o.companies?.length) setCompanies(o.companies)
      if (o.tag_presets?.customer) setCustomerTagPresets(o.tag_presets.customer)
      if (o.tag_presets?.product) setProductTagPresets(o.tag_presets.product)
      await Promise.all([
        loadCustomers(),
        loadProducts(),
        api('/humans/').then((r) => setHumans(r.humans || [])).catch(() => {}),
        api('/agents/').then((a) => setAgents(Array.isArray(a) ? a : [])).catch(() => {}),
        api('/org/companies').then((c) => {
          const list = Array.isArray(c) ? c : c.companies || []
          if (list.length) setCompanies(list)
        }).catch(() => {}),
        api('/business/diary?upcoming=true').then((d) => setUpcomingDiary(d.diary || [])).catch(() => {}),
        api('/integrations/connections').then((r) => {
          const conns = r.connections || r || []
          setHasShopify(
            (Array.isArray(conns) ? conns : []).some(
              (c) => c.app_id === 'shopify' && (c.status === 'connected' || c.connected),
            ),
          )
        }).catch(() => setHasShopify(false)),
      ])
    } catch (e) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])
  useEffect(() => {
    if (pipelineId) loadBoard(pipelineId)
  }, [pipelineId])

  const createCustomer = async (values) => {
    setSaving(true)
    try {
      const body = {
        ...values,
        tags: Array.isArray(values.tags) ? values.tags : values.tags,
        company_id: values.company_id || defaultCompanyId || null,
      }
      const c = await api('/business/customers', { method: 'POST', body })
      message.success('Customer created')
      setCustOpen(false)
      custForm.resetFields()
      await loadCustomers()
      await loadOverview()
      nav(`/business/customers/${c.id}`)
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const saveProduct = async (values) => {
    setSaving(true)
    try {
      const body = {
        ...values,
        tags: Array.isArray(values.tags) ? values.tags : values.tags,
        company_id: values.company_id || defaultCompanyId,
      }
      if (!body.company_id) {
        message.warning('Create a company in Workspace first — products must link to your company')
        setSaving(false)
        return
      }
      if (editingProduct) {
        await api(`/business/products/${editingProduct.id}`, { method: 'PUT', body })
        message.success('Product updated')
      } else {
        await api('/business/products', { method: 'POST', body })
        message.success('Product created')
      }
      setProductOpen(false)
      setEditingProduct(null)
      productForm.resetFields()
      await loadProducts()
      await loadOverview()
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const removeProduct = async (id) => {
    try {
      await api(`/business/products/${id}`, { method: 'DELETE' })
      message.success('Product deleted')
      loadProducts()
      loadOverview()
    } catch (e) {
      message.error(e.message)
    }
  }

  const createDeal = async (values) => {
    setSaving(true)
    try {
      await api('/business/deals', {
        method: 'POST',
        body: { ...values, pipeline_id: pipelineId },
      })
      message.success('Deal created')
      setDealOpen(false)
      dealForm.resetFields()
      loadBoard()
      loadOverview()
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const createPipeline = async (values) => {
    setSaving(true)
    try {
      const p = await api('/business/pipelines', { method: 'POST', body: values })
      message.success('Pipeline created')
      setPipeOpen(false)
      pipeForm.resetFields()
      await loadOverview()
      setPipelineId(p.id)
      setTab('pipeline')
    } catch (e) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const onDropDeal = async (stageId) => {
    if (!dragDeal || dragDeal.stage_id === stageId) {
      setDragDeal(null)
      return
    }
    try {
      await api(`/business/deals/${dragDeal.id}/move`, {
        method: 'PUT',
        body: { stage_id: stageId },
      })
      message.success('Deal moved')
      loadBoard()
      loadOverview()
    } catch (e) {
      message.error(e.message)
    } finally {
      setDragDeal(null)
    }
  }

  if (loading && !overview) {
    return (
      <PageShell>
        <Card className="aba-soft-card">
          <div style={{ textAlign: 'center', padding: 64 }}>
            <Spin size="large" tip="Loading business…" />
          </div>
        </Card>
      </PageShell>
    )
  }

  const counts = overview?.counts || {}

  return (
    <PageShell>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Card className="aba-soft-card" styles={{ body: { paddingBlock: 16 } }}>
          <PageHeader
            title={<><ShopOutlined /> Business</>}
            subtitle="Customers, products, pipelines & diary — linked to your company"
            style={{ marginBottom: 0 }}
            extra={(
              <Space wrap>
                <Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button>
                <Button
                  icon={<CloudSyncOutlined />}
                  loading={shopifySyncing}
                  onClick={() => syncShopify('all')}
                  title="Import Shopify products & customers with tags into your company"
                >
                  Sync Shopify
                </Button>
                <Button icon={<PlusOutlined />} onClick={() => setPipeOpen(true)}>New pipeline</Button>
                <Button icon={<ShoppingOutlined />} onClick={() => { setEditingProduct(null); productForm.resetFields(); setProductOpen(true) }}>Add product</Button>
                <Button icon={<CalendarOutlined />} onClick={() => { setSelectedCustForDiary(null); setDiaryOpen(true) }}>Arrange diary</Button>
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setCustOpen(true)}>Add customer</Button>
              </Space>
            )}
          />
        </Card>

        {!companies.length && (
          <Card size="small" className="aba-soft-card">
            <Space wrap>
              <BankOutlined />
              <Text>No company on your account yet. Customers and products should link to a company.</Text>
              <Button type="primary" size="small" onClick={() => nav('/workspace')}>Create company</Button>
            </Space>
          </Card>
        )}

        {companies.length > 0 && !hasShopify && (
          <Card size="small" className="aba-soft-card">
            <Space wrap>
              <CloudSyncOutlined style={{ color: '#96bf48' }} />
              <Text>
                Connect Shopify to import products &amp; customers with <strong>tags</strong> into{' '}
                <strong>{companies[0]?.name || 'your company'}</strong>.
              </Text>
              <Button size="small" type="primary" onClick={() => nav('/settings?tab=apps')}>
                Connect Shopify
              </Button>
            </Space>
          </Card>
        )}

        <BusinessStatsRow counts={counts} companies={companies} />

        <Card className="aba-soft-card" styles={{ body: { paddingTop: 8 } }}>
          <Tabs
            activeKey={tab}
            onChange={setTab}
            centered
            items={[
              {
                key: 'overview',
                label: 'Overview',
                children: (
                  <BusinessOverviewTab
                    overview={overview}
                    upcomingDiary={upcomingDiary}
                    setTab={setTab}
                    setPipelineId={setPipelineId}
                    setSelectedCustForDiary={setSelectedCustForDiary}
                    setDiaryOpen={setDiaryOpen}
                  />
                ),
              },
              {
                key: 'customers',
                label: customersTabLabel(total),
                children: (
                  <BusinessCustomersTab
                    customers={customers}
                    total={total}
                    loading={loading}
                    q={q}
                    setQ={setQ}
                    statusFilter={statusFilter}
                    setStatusFilter={setStatusFilter}
                    loadCustomers={loadCustomers}
                    shopifySyncing={shopifySyncing}
                    syncShopify={syncShopify}
                    onAdd={() => setCustOpen(true)}
                  />
                ),
              },
              {
                key: 'products',
                label: productsTabLabel(productTotal),
                children: (
                  <BusinessProductsTab
                    products={products}
                    productTotal={productTotal}
                    loading={loading}
                    productQ={productQ}
                    setProductQ={setProductQ}
                    productStatus={productStatus}
                    setProductStatus={setProductStatus}
                    loadProducts={loadProducts}
                    shopifySyncing={shopifySyncing}
                    syncShopify={syncShopify}
                    onAdd={() => {
                      setEditingProduct(null)
                      productForm.resetFields()
                      setProductOpen(true)
                    }}
                    onEdit={(r) => {
                      setEditingProduct(r)
                      productForm.setFieldsValue({ ...r, tags: r.tags || [] })
                      setProductOpen(true)
                    }}
                    onRemove={removeProduct}
                    onPushShopify={pushProductShopify}
                  />
                ),
              },
              {
                key: 'pipeline',
                label: 'Pipeline',
                children: (
                  <BusinessPipelineTab
                    overview={overview}
                    pipelines={pipelines}
                    pipelineId={pipelineId}
                    setPipelineId={setPipelineId}
                    board={board}
                    setDragDeal={setDragDeal}
                    onDropDeal={onDropDeal}
                    dealForm={dealForm}
                    setDealOpen={setDealOpen}
                  />
                ),
              },
            ]}
          />
        </Card>
      </Space>

      <BusinessCustomerModal
        open={custOpen}
        onCancel={() => setCustOpen(false)}
        form={custForm}
        onFinish={createCustomer}
        saving={saving}
        companies={companies}
        humans={humans}
        agents={agents}
        customerTagPresets={customerTagPresets}
        defaultCompanyId={defaultCompanyId}
      />

      <BusinessProductModal
        open={productOpen}
        onCancel={() => { setProductOpen(false); setEditingProduct(null) }}
        form={productForm}
        onFinish={saveProduct}
        saving={saving}
        editingProduct={editingProduct}
        companies={companies}
        productTagPresets={productTagPresets}
        defaultCompanyId={defaultCompanyId}
      />

      <BusinessDealModal
        open={dealOpen}
        onCancel={() => setDealOpen(false)}
        form={dealForm}
        onFinish={createDeal}
        saving={saving}
        customers={customers}
      />

      <BusinessPipelineModal
        open={pipeOpen}
        onCancel={() => setPipeOpen(false)}
        form={pipeForm}
        onFinish={createPipeline}
        saving={saving}
      />

      <BusinessDiaryModal
        open={diaryOpen}
        onClose={() => setDiaryOpen(false)}
        form={diaryForm}
        saving={saving}
        setSaving={setSaving}
        selectedCustForDiary={selectedCustForDiary}
        setSelectedCustForDiary={setSelectedCustForDiary}
        customers={customers}
        humans={humans}
        agents={agents}
        onSaved={load}
      />
    </PageShell>
  )
}
