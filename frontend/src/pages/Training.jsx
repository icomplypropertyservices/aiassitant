import React, { useEffect, useMemo, useState } from 'react'
import {
  Card, Typography, Tabs, Button, Space, Tag, List, Empty, Spin, Modal, Form, Input,
  Select, Upload, message, Popconfirm, Alert, Row, Col, Switch, Divider, Badge, Progress,
} from 'antd'
import {
  BookOutlined, FolderOutlined, FileTextOutlined, CloudUploadOutlined,
  RobotOutlined, DeleteOutlined, ReloadOutlined, CloudOutlined, LinkOutlined,
  ExperimentOutlined, PlusOutlined, InboxOutlined, CloudServerOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, API, getToken } from '../api'
import PageHeader from '../components/PageHeader'
import PageShell from '../components/PageShell'

const { Text, Paragraph } = Typography
const { TextArea } = Input
const { Dragger } = Upload


export default function Training() {
  const nav = useNavigate()
  const [tab, setTab] = useState('library')
  const [loading, setLoading] = useState(true)
  const [overview, setOverview] = useState(null)
  const [folders, setFolders] = useState([])
  const [files, setFiles] = useState([])
  const [agents, setAgents] = useState([])
  const [connections, setConnections] = useState([])
  const [folderFilter, setFolderFilter] = useState(undefined)
  const [search, setSearch] = useState('')

  // notes / upload
  const [noteForm] = Form.useForm()
  const [uploadStorage, setUploadStorage] = useState('local')
  const [uploadFolder, setUploadFolder] = useState(undefined)
  const [uploading, setUploading] = useState(false)

  // folder modal
  const [folderOpen, setFolderOpen] = useState(false)
  const [folderForm] = Form.useForm()

  // preview / assign
  const [preview, setPreview] = useState(null)
  const [assignOpen, setAssignOpen] = useState(null)
  const [assignIds, setAssignIds] = useState([])

  // cloud browser
  const [cloudStorage, setCloudStorage] = useState('dropbox')
  const [cloudPath, setCloudPath] = useState('')
  const [cloudItems, setCloudItems] = useState([])
  const [cloudLoading, setCloudLoading] = useState(false)

  // agent program
  const [progAgent, setProgAgent] = useState(null)
  const [prog, setProg] = useState(null)
  const [progLoading, setProgLoading] = useState(false)
  const [progForm] = Form.useForm()
  const [progSaving, setProgSaving] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [ov, fol, fl, ag, con] = await Promise.all([
        api('/training/overview'),
        api('/training/folders'),
        api('/training/files'),
        api('/agents/').catch(() => []),
        api('/integrations/connections').catch(() => ({ connections: [] })),
      ])
      setOverview(ov)
      setFolders(Array.isArray(fol) ? fol : [])
      setFiles(fl.files || [])
      setAgents(Array.isArray(ag) ? ag : [])
      setConnections(con.connections || [])
    } catch (e) {
      message.error(e.message || 'Failed to load training')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const refreshFiles = async (opts = {}) => {
    const params = new URLSearchParams()
    if (opts.folder_id !== undefined) params.set('folder_id', opts.folder_id)
    else if (folderFilter !== undefined && folderFilter !== null) params.set('folder_id', folderFilter)
    if (opts.q || search) params.set('q', opts.q ?? search)
    const fl = await api(`/training/files?${params.toString()}`)
    setFiles(fl.files || [])
  }

  const filteredFiles = useMemo(() => files, [files])

  const createFolder = async (values) => {
    try {
      await api('/training/folders', { method: 'POST', body: values })
      message.success('Folder created')
      setFolderOpen(false)
      folderForm.resetFields()
      load()
    } catch (e) {
      message.error(e.message)
    }
  }

  const createNote = async (values) => {
    try {
      await api('/training/notes', { method: 'POST', body: values })
      message.success('Training note saved')
      noteForm.resetFields()
      load()
      setTab('library')
    } catch (e) {
      message.error(e.message)
    }
  }

  const customUpload = async ({ file, onSuccess, onError }) => {
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('storage', uploadStorage)
      if (uploadFolder) fd.append('folder_id', String(uploadFolder))
      const res = await fetch(`${API}/training/upload`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}` },
        body: fd,
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Upload failed')
      message.success(`Uploaded ${data.name}`)
      onSuccess?.(data)
      load()
      setTab('library')
    } catch (e) {
      message.error(e.message)
      onError?.(e)
    } finally {
      setUploading(false)
    }
  }

  const openPreview = async (id) => {
    try {
      const f = await api(`/training/files/${id}`)
      setPreview(f)
    } catch (e) {
      message.error(e.message)
    }
  }

  const openAssign = (file) => {
    setAssignOpen(file)
    setAssignIds((file.agents || []).map((a) => a.id))
  }

  const saveAssign = async () => {
    try {
      await api(`/training/files/${assignOpen.id}/agents`, {
        method: 'PUT',
        body: { agent_ids: assignIds },
      })
      message.success('Agents updated')
      setAssignOpen(null)
      load()
    } catch (e) {
      message.error(e.message)
    }
  }

  const deleteFile = async (id) => {
    try {
      await api(`/training/files/${id}`, { method: 'DELETE' })
      message.success('Deleted')
      load()
    } catch (e) {
      message.error(e.message)
    }
  }

  const browseCloud = async () => {
    setCloudLoading(true)
    try {
      const params = new URLSearchParams({ storage: cloudStorage, path: cloudPath || '' })
      const r = await api(`/training/cloud/list?${params}`)
      setCloudItems(r.items || [])
    } catch (e) {
      message.error(e.message)
      setCloudItems([])
    } finally {
      setCloudLoading(false)
    }
  }

  const importCloud = async (item) => {
    try {
      await api('/training/import-cloud', {
        method: 'POST',
        body: {
          storage: cloudStorage,
          path: item.path,
          name: item.name,
          folder_id: uploadFolder || null,
        },
      })
      message.success(`Imported ${item.name}`)
      load()
      setTab('library')
    } catch (e) {
      message.error(e.message)
    }
  }

  const loadProgram = async (agentId) => {
    if (!agentId) {
      setProgAgent(null)
      setProg(null)
      return
    }
    setProgAgent(agentId)
    setProgLoading(true)
    try {
      const r = await api(`/training/agents/${agentId}/access`)
      setProg(r)
      const fileIds = (r.access || [])
        .filter((a) => a.resource_type === 'file')
        .map((a) => a.resource_id)
      const folderIds = (r.access || [])
        .filter((a) => a.resource_type === 'folder')
        .map((a) => a.resource_id)
      const allowAll = (r.access || []).some((a) => a.resource_type === 'all')
        || r.program?.policy?.allow_all_files
      progForm.setFieldsValue({
        instructions: r.program?.instructions || '',
        allow_all_files: !!allowAll,
        allow_all_apps: !!r.program?.policy?.allow_all_apps,
        max_file_chars: r.program?.policy?.max_file_chars || 14000,
        file_ids: fileIds,
        folder_ids: folderIds,
        connection_ids: (r.apps || []).map((a) => a.connection_id),
      })
    } catch (e) {
      message.error(e.message)
    } finally {
      setProgLoading(false)
    }
  }

  const saveProgram = async (values) => {
    if (!progAgent) return
    setProgSaving(true)
    try {
      const r = await api(`/training/agents/${progAgent}/program`, {
        method: 'PUT',
        body: {
          instructions: values.instructions || '',
          allow_all_files: !!values.allow_all_files,
          allow_all_apps: !!values.allow_all_apps,
          max_file_chars: values.max_file_chars || 14000,
          file_ids: values.allow_all_files ? [] : (values.file_ids || []),
          folder_ids: values.allow_all_files ? [] : (values.folder_ids || []),
          connection_ids: values.allow_all_apps ? [] : (values.connection_ids || []),
        },
      })
      setProg(r)
      message.success('Agent program saved')
    } catch (e) {
      message.error(e.message)
    } finally {
      setProgSaving(false)
    }
  }

  const storageTag = (s) => {
    const color = s === 'gcs' ? 'blue' : s === 'dropbox' ? 'geekblue' : 'default'
    return <Tag color={color}>{s}</Tag>
  }

  const libraryTab = (
    <div>
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} md={8}>
          <Card
            className="aba-soft-card"
            size="small"
            title={<Space><FolderOutlined /> Folders</Space>}
            extra={<Button size="small" icon={<PlusOutlined />} onClick={() => setFolderOpen(true)}>New</Button>}
          >
            <List
              size="small"
              dataSource={[{ id: null, name: 'All files', file_count: overview?.files }, { id: 0, name: 'Unfiled', file_count: null }, ...folders]}
              renderItem={(f) => (
                <List.Item
                  style={{
                    cursor: 'pointer',
                    background: folderFilter === f.id ? '#e6f4ff' : undefined,
                    padding: '8px 12px',
                    borderRadius: 6,
                  }}
                  onClick={() => {
                    setFolderFilter(f.id)
                    const params = {}
                    if (f.id !== null && f.id !== undefined) params.folder_id = f.id
                    refreshFiles(params)
                  }}
                >
                  <Space>
                    <FolderOutlined />
                    <span>{f.name}</span>
                    {f.file_count != null && <Badge count={f.file_count} style={{ backgroundColor: '#1677ff' }} />}
                  </Space>
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} md={16}>
          <Card
            className="aba-soft-card"
            size="small"
            title="Training files"
            extra={
              <Space>
                <Input.Search
                  placeholder="Search"
                  allowClear
                  onSearch={(q) => { setSearch(q); refreshFiles({ q }) }}
                  style={{ width: 180 }}
                />
                <Button icon={<ReloadOutlined />} onClick={load} />
              </Space>
            }
          >
            {loading ? <Spin /> : filteredFiles.length === 0 ? (
              <Empty description="No training files yet — upload or create a note" />
            ) : (
              <List
                dataSource={filteredFiles}
                renderItem={(f) => (
                  <List.Item
                    actions={[
                      <Button key="v" type="link" onClick={() => openPreview(f.id)}>View</Button>,
                      <Button key="a" type="link" icon={<RobotOutlined />} onClick={() => openAssign(f)}>
                        Agents ({(f.agents || []).length})
                      </Button>,
                      <Popconfirm key="d" title="Delete this file?" onConfirm={() => deleteFile(f.id)}>
                        <Button type="link" danger icon={<DeleteOutlined />} />
                      </Popconfirm>,
                    ]}
                  >
                    <List.Item.Meta
                      avatar={<FileTextOutlined style={{ fontSize: 22 }} />}
                      title={
                        <Space wrap>
                          <Text strong>{f.name}</Text>
                          {storageTag(f.storage)}
                          <Tag>{f.kind}</Tag>
                          <Tag color={f.status === 'ready' ? 'success' : 'default'}>{f.status}</Tag>
                        </Space>
                      }
                      description={
                        <div>
                          <Text type="secondary">
                            {(f.content_chars || 0).toLocaleString()} chars
                            {f.tags ? ` · ${f.tags}` : ''}
                          </Text>
                          {f.content_preview && (
                            <Paragraph type="secondary" ellipsis={{ rows: 1 }} style={{ marginBottom: 0 }}>
                              {f.content_preview}
                            </Paragraph>
                          )}
                        </div>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )

  const uploadTab = (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={12}>
        <Card className="aba-soft-card" title={<Space><FileTextOutlined /> Training note</Space>}>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message="Paste SOPs, product info, scripts — agents only see notes you allocate to them."
          />
          <Form form={noteForm} layout="vertical" onFinish={createNote}>
            <Form.Item name="name" label="Title" rules={[{ required: true }]}>
              <Input placeholder="e.g. Refund policy" />
            </Form.Item>
            <Form.Item name="folder_id" label="Folder">
              <Select
                allowClear
                placeholder="Optional folder"
                options={folders.map((f) => ({ value: f.id, label: f.name }))}
              />
            </Form.Item>
            <Form.Item name="tags" label="Tags">
              <Input placeholder="policy, sales, support" />
            </Form.Item>
            <Form.Item name="content" label="Content" rules={[{ required: true }]}>
              <TextArea rows={10} placeholder="Markdown or plain text…" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block>Save to library</Button>
          </Form>
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card className="aba-soft-card" title={<Space><CloudUploadOutlined /> Upload file</Space>}>
          <Space direction="vertical" style={{ width: '100%', marginBottom: 12 }} size="middle">
            <div>
              <Text type="secondary">Storage backend</Text>
              <Select
                style={{ width: '100%', marginTop: 4 }}
                value={uploadStorage}
                onChange={setUploadStorage}
                options={[
                  { value: 'local', label: 'Local (server disk)' },
                  { value: 'gcs', label: 'Google Cloud Storage' },
                  { value: 'dropbox', label: 'Dropbox' },
                ]}
              />
              {uploadStorage !== 'local' && (
                <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}>
                  Connect {uploadStorage === 'gcs' ? 'Google Cloud Storage' : 'Dropbox'} under{' '}
                  <a onClick={() => nav('/settings?tab=apps')}>Settings → Connected apps</a> first.
                </Paragraph>
              )}
            </div>
            <div>
              <Text type="secondary">Folder</Text>
              <Select
                style={{ width: '100%', marginTop: 4 }}
                allowClear
                placeholder="Optional"
                value={uploadFolder}
                onChange={setUploadFolder}
                options={folders.map((f) => ({ value: f.id, label: f.name }))}
              />
            </div>
          </Space>
          <Dragger customRequest={customUpload} multiple={false} showUploadList={false} disabled={uploading}>
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">{uploading ? 'Uploading…' : 'Click or drag file'}</p>
            <p className="ant-upload-hint">Text, Markdown, CSV, JSON, code — max 15 MB. Text is extracted for training.</p>
          </Dragger>
        </Card>
      </Col>
    </Row>
  )

  const cloudTab = (
    <Card
      className="aba-soft-card"
      title={<Space><CloudOutlined /> Cloud browser</Space>}
      extra={
        <Space wrap>
          <Select
            value={cloudStorage}
            onChange={setCloudStorage}
            style={{ width: 160 }}
            options={[
              { value: 'dropbox', label: 'Dropbox' },
              { value: 'gcs', label: 'Google Cloud Storage' },
            ]}
          />
          <Input
            style={{ width: 220 }}
            placeholder={cloudStorage === 'gcs' ? 'prefix (optional)' : 'path e.g. /AI-Training'}
            value={cloudPath}
            onChange={(e) => setCloudPath(e.target.value)}
          />
          <Button type="primary" loading={cloudLoading} onClick={browseCloud} icon={<ReloadOutlined />}>
            List
          </Button>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="Browse connected storage and import files into the training library (content is indexed for agents)."
      />
      {cloudLoading ? <Spin /> : cloudItems.length === 0 ? (
        <Empty description="List a path, or connect Dropbox / GCS in Settings" />
      ) : (
        <List
          dataSource={cloudItems}
          renderItem={(item) => (
            <List.Item
              actions={
                item.tag === 'folder' || item.tag === 'folder'
                  ? [
                    <Button key="open" type="link" onClick={() => { setCloudPath(item.path); setTimeout(browseCloud, 0) }}>
                      Open
                    </Button>,
                  ]
                  : [
                    <Button key="imp" type="link" icon={<LinkOutlined />} onClick={() => importCloud(item)}>
                      Import to library
                    </Button>,
                  ]
              }
            >
              <List.Item.Meta
                title={item.name}
                description={`${item.path || ''} ${item.size != null ? `· ${item.size} bytes` : ''} · ${item.tag || 'file'}`}
              />
            </List.Item>
          )}
        />
      )}
    </Card>
  )

  const programTab = (
    <div>
      <Card className="aba-soft-card" size="small" style={{ marginBottom: 16 }}>
        <Space wrap style={{ width: '100%' }}>
          <Text strong>Program agent:</Text>
          <Select
            style={{ minWidth: 260 }}
            placeholder="Select an agent"
            value={progAgent}
            onChange={loadProgram}
            options={agents.map((a) => ({
              value: a.id,
              label: `${a.name} (${a.template_type})`,
            }))}
          />
          <Button onClick={() => nav('/settings?tab=apps')}>Manage app connections</Button>
        </Space>
      </Card>

      {!progAgent ? (
        <Card className="aba-soft-card">
          <Empty description="Pick an agent to set instructions, files, and app access" />
        </Card>
      ) : progLoading ? (
        <Card className="aba-soft-card">
          <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={14}>
            <Card className="aba-soft-card" title={<Space><RobotOutlined /> {prog?.agent_name || 'Agent'} program</Space>}>
              <Form form={progForm} layout="vertical" onFinish={saveProgram}>
                <Form.Item
                  name="instructions"
                  label="Standing instructions"
                  extra="Always injected into this agent's chat and tasks"
                >
                  <TextArea rows={6} placeholder="You always follow the refund SOP. Never invent prices…" />
                </Form.Item>
                <Form.Item name="allow_all_files" label="Allow all training files" valuePropName="checked">
                  <Switch />
                </Form.Item>
                <Form.Item noStyle shouldUpdate={(p, c) => p.allow_all_files !== c.allow_all_files}>
                  {({ getFieldValue }) => !getFieldValue('allow_all_files') && (
                    <>
                      <Form.Item name="file_ids" label="Allowed files">
                        <Select
                          mode="multiple"
                          allowClear
                          placeholder="Select files"
                          options={files.map((f) => ({ value: f.id, label: f.name }))}
                        />
                      </Form.Item>
                      <Form.Item name="folder_ids" label="Allowed folders">
                        <Select
                          mode="multiple"
                          allowClear
                          placeholder="Select folders"
                          options={folders.map((f) => ({ value: f.id, label: f.name }))}
                        />
                      </Form.Item>
                    </>
                  )}
                </Form.Item>
                <Form.Item name="allow_all_apps" label="Allow all connected apps" valuePropName="checked">
                  <Switch />
                </Form.Item>
                <Form.Item noStyle shouldUpdate={(p, c) => p.allow_all_apps !== c.allow_all_apps}>
                  {({ getFieldValue }) => !getFieldValue('allow_all_apps') && (
                    <Form.Item name="connection_ids" label="Allowed apps">
                      <Select
                        mode="multiple"
                        allowClear
                        placeholder="Select connected apps"
                        options={connections.map((c) => ({
                          value: c.id,
                          label: `${c.display_name || c.app_name} (${c.status})`,
                        }))}
                      />
                    </Form.Item>
                  )}
                </Form.Item>
                <Form.Item name="max_file_chars" label="Max training chars in prompt">
                  <Select
                    options={[
                      { value: 6000, label: '6,000' },
                      { value: 14000, label: '14,000 (default)' },
                      { value: 24000, label: '24,000' },
                    ]}
                  />
                </Form.Item>
                <Button type="primary" htmlType="submit" loading={progSaving} block icon={<ExperimentOutlined />}>
                  Save program
                </Button>
              </Form>
            </Card>
          </Col>
          <Col xs={24} lg={10}>
            <Card className="aba-soft-card" title="Context preview" size="small">
              <Paragraph type="secondary" style={{ fontSize: 12 }}>
                What this agent will receive (truncated).
              </Paragraph>
              <pre style={{
                whiteSpace: 'pre-wrap',
                background: '#fafafa',
                padding: 12,
                borderRadius: 8,
                maxHeight: 480,
                overflow: 'auto',
                fontSize: 12,
              }}>
                {prog?.context_preview || 'Save or reload to preview.'}
              </pre>
              <Divider />
              <Text strong>Resolved files: </Text>
              <Space wrap>
                {!Array.isArray(prog?.resolved_files) || prog.resolved_files.length === 0
                  ? <Text type="secondary">none</Text>
                  : prog.resolved_files.map((f) => <Tag key={f.id}>{f.name}</Tag>)}
              </Space>
              <div style={{ marginTop: 8 }}>
                <Text strong>Apps: </Text>
                <Space wrap>
                  {!Array.isArray(prog?.apps) || prog.apps.length === 0
                    ? <Text type="secondary">none</Text>
                    : prog.apps.map((a) => <Tag key={a.connection_id} color="blue">{a.display_name}</Tag>)}
                </Space>
              </div>
            </Card>
          </Col>
        </Row>
      )}
    </div>
  )

  return (
    <PageShell>
      <PageHeader
        title={(
          <span>
            <BookOutlined style={{ marginRight: 8 }} />
            Training
          </span>
        )}
        subtitle="Upload knowledge, store on local / GCS / Dropbox, and program which agents may use which files and apps."
      />

      {overview && (
        <Card className="aba-soft-card" size="small" style={{ marginBottom: 16 }}>
          <Space wrap>
            <Tag color="blue">{overview.files} files</Tag>
            <Tag color="blue">{overview.folders} folders</Tag>
            <Tag color="green">{overview.ready} ready</Tag>
            {Object.entries(overview.by_storage || {}).map(([k, v]) => (
              <Tag key={k}>{k}: {v}</Tag>
            ))}
          </Space>
          {overview.quota && (
            <div style={{ marginTop: 12 }}>
              {(overview.quota.hard_block || overview.quota.warn) && (
                <Alert
                  type={overview.quota.hard_block ? 'error' : 'warning'}
                  showIcon
                  style={{ marginBottom: 10 }}
                  message={
                    overview.quota.hard_block
                      ? 'Training storage is full'
                      : 'Training storage running low'
                  }
                  description={
                    <span>
                      {overview.quota.used_human} of {overview.quota.limit_human} used.
                      {' '}
                      <a onClick={() => nav('/billing')}>Upgrade storage or plan →</a>
                    </span>
                  }
                />
              )}
              <Space wrap align="center">
                <CloudServerOutlined />
                <Text type="secondary">
                  Storage: <strong>{overview.quota.used_human}</strong>
                  {' / '}
                  <strong>{overview.quota.limit_human}</strong>
                  {overview.quota.bonus_bytes > 0 ? ` (+${overview.quota.bonus_human} packs)` : ''}
                </Text>
                {!overview.quota.unlimited && (
                  <Progress
                    percent={Math.min(100, overview.quota.usage_percent || 0)}
                    size="small"
                    style={{ width: 160, margin: 0 }}
                    status={overview.quota.hard_block ? 'exception' : overview.quota.warn ? 'active' : 'normal'}
                    format={(p) => `${p}%`}
                  />
                )}
                <Button size="small" type="link" onClick={() => nav('/billing')}>
                  Get more storage
                </Button>
              </Space>
            </div>
          )}
        </Card>
      )}

      <Card className="aba-soft-card" styles={{ body: { paddingTop: 8 } }}>
        <Tabs
          activeKey={tab}
          onChange={setTab}
          items={[
            { key: 'library', label: <span><FolderOutlined /> Library</span>, children: libraryTab },
            { key: 'upload', label: <span><CloudUploadOutlined /> Upload & notes</span>, children: uploadTab },
            { key: 'cloud', label: <span><CloudOutlined /> Cloud</span>, children: cloudTab },
            { key: 'program', label: <span><RobotOutlined /> Agent access</span>, children: programTab },
          ]}
        />
      </Card>

      <Modal
        title="New folder"
        open={folderOpen}
        onCancel={() => setFolderOpen(false)}
        footer={null}
        destroyOnClose
      >
        <Form form={folderForm} layout="vertical" onFinish={createFolder}>
          <Form.Item name="name" label="Name" rules={[{ required: true }]}>
            <Input placeholder="e.g. Policies" />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <Input />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>Create</Button>
        </Form>
      </Modal>

      <Modal
        title={preview?.name || 'File'}
        open={!!preview}
        onCancel={() => setPreview(null)}
        footer={null}
        width={720}
      >
        {preview && (
          <>
            <Space wrap style={{ marginBottom: 12 }}>
              {storageTag(preview.storage)}
              <Tag>{preview.kind}</Tag>
              <Tag>{preview.mime_type}</Tag>
              <Text type="secondary">{preview.content_chars} chars</Text>
            </Space>
            <pre style={{
              whiteSpace: 'pre-wrap',
              background: '#fafafa',
              padding: 12,
              borderRadius: 8,
              maxHeight: 480,
              overflow: 'auto',
            }}>
              {preview.content || preview.content_preview || '(empty)'}
            </pre>
          </>
        )}
      </Modal>

      <Modal
        title={assignOpen ? `Agents · ${assignOpen.name}` : 'Agents'}
        open={!!assignOpen}
        onCancel={() => setAssignOpen(null)}
        onOk={saveAssign}
        okText="Save"
      >
        <Select
          mode="multiple"
          style={{ width: '100%' }}
          placeholder="Select agents that may read this file"
          value={assignIds}
          onChange={setAssignIds}
          options={agents.map((a) => ({ value: a.id, label: `${a.name} (${a.template_type})` }))}
        />
      </Modal>
    </PageShell>
  )
}
