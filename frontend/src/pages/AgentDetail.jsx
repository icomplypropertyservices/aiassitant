import React, { useEffect, useRef, useState } from 'react'
import {
  Card, Tabs, Button, Space, Tag, Typography, Input, List, Timeline, Form, Select,
  message, Spin, Empty, Modal, Descriptions, Switch, Popconfirm, Badge, Divider,
} from 'antd'
// Switch + Divider used by Skills / Data tabs
import {
  ArrowLeftOutlined, SendOutlined, PauseCircleOutlined, PlayCircleOutlined,
  ThunderboltOutlined, CopyOutlined, DeleteOutlined, BulbOutlined, MailOutlined,
  MessageOutlined, PhoneOutlined, CheckCircleOutlined, InfoCircleOutlined,
  ReloadOutlined, CrownOutlined, TeamOutlined, RobotOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { api, getToken, getWsBase } from '../api'
import ModelSelect from '../components/ModelSelect'
import VoiceControls, { speakText, stopSpeaking } from '../components/VoiceControls'
import { modelLabel } from '../models'

const ICONS = {
  thinking: <BulbOutlined style={{ color: '#faad14' }} />,
  action: <ThunderboltOutlined style={{ color: '#1668dc' }} />,
  email: <MailOutlined style={{ color: '#52c41a' }} />,
  sms: <MessageOutlined style={{ color: '#52c41a' }} />,
  call: <PhoneOutlined style={{ color: '#52c41a' }} />,
  done: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  info: <InfoCircleOutlined style={{ color: '#8c8c8c' }} />,
}

const PROMPTS = [
  'Summarise what you can do for me',
  'Draft a professional follow-up email',
  'What tasks are you working on?',
  'Give me 3 next actions for this week',
]

const STATUS_COLOR = {
  todo: 'default', queued: 'processing', in_progress: 'gold',
  review: 'purple', completed: 'success', failed: 'error',
}

export default function AgentDetail() {
  const { id } = useParams()
  const nav = useNavigate()
  const [agent, setAgent] = useState(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState('chat')
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [live, setLive] = useState(false)
  const [sessionTokens, setSessionTokens] = useState(0)
  const [taskOpen, setTaskOpen] = useState(false)
  const [taskForm] = Form.useForm()
  const [editForm] = Form.useForm()
  const [projects, setProjects] = useState([])
  const [selectedTask, setSelectedTask] = useState(null)
  const [allAgents, setAllAgents] = useState([])
  const [delegateOpen, setDelegateOpen] = useState(false)
  const [speakReplies, setSpeakReplies] = useState(
    () => localStorage.getItem('voice_speak_replies') === '1',
  )
  const [agentApps, setAgentApps] = useState([])
  const [agentTraining, setAgentTraining] = useState([])
  const [skills, setSkills] = useState([])
  const [memories, setMemories] = useState([])
  const [agentMsgs, setAgentMsgs] = useState([])
  const [humans, setHumans] = useState([])
  const [skillBusy, setSkillBusy] = useState(false)
  const [memForm] = Form.useForm()
  const [a2aForm] = Form.useForm()
  const [spawnForm] = Form.useForm()
  const [hierForm] = Form.useForm()
  const [delegateForm] = Form.useForm()
  const wsRef = useRef(null)
  const bottomRef = useRef(null)
  const activityWs = useRef(null)
  const speakRepliesRef = useRef(speakReplies)
  speakRepliesRef.current = speakReplies

  const loadSkillsExtra = () => {
    api(`/agents/${id}/skills`).then((r) => setSkills(r.skills || [])).catch(() => setSkills([]))
    api(`/agents/${id}/memory`).then((r) => setMemories(r.memories || [])).catch(() => setMemories([]))
    api(`/agents/${id}/messages`).then((r) => setAgentMsgs(r.messages || [])).catch(() => setAgentMsgs([]))
    api('/humans/').then((r) => setHumans(r.humans || [])).catch(() => setHumans([]))
  }

  const load = () => {
    setLoading(true)
    api(`/agents/${id}`)
      .then(a => {
        setAgent(a)
        if (a.chat?.messages?.length) {
          setMessages(a.chat.messages.map(m => ({ role: m.role, content: m.content })))
        }
        editForm.setFieldsValue({
          name: a.name,
          personality: a.personality,
          model: a.model,
          never_idle: a.idle_mode === 'never_idle',
          permission_level: a.permission_level || 'operator',
          escalate_when: a.escalate_when || 'on_failure',
          escalate_reason: a.escalate_reason || '',
          escalate_to: a.escalate_to || 'parent',
          escalate_human_id: a.escalate_human_id || undefined,
        })
        hierForm.setFieldsValue({
          is_lead: a.is_lead || a.hierarchy_role === 'lead',
          hierarchy_role: a.hierarchy_role || (a.is_lead ? 'lead' : 'member'),
          parent_id: a.parent_id || undefined,
          report_ids: (a.reports || []).map(r => r.id),
        })
        // Load live app + training allocations
        api(`/integrations/agents/${id}`)
          .then((r) => setAgentApps(r.connections || []))
          .catch(() => setAgentApps(a.integrations || []))
        api(`/training/agents/${id}/access`)
          .then((r) => {
            setAgentTraining(r.resolved_files || [])
            if (r.apps?.length) setAgentApps(r.apps)
          })
          .catch(() => setAgentTraining([]))
        loadSkillsExtra()
      })
      .catch(e => { message.error(e.message); nav('/agents') })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    api('/org/projects').then(setProjects).catch(() => setProjects([]))
    api('/agents/').then(setAllAgents).catch(() => setAllAgents([]))

    // Live activity feed
    const aws = new WebSocket(`${getWsBase()}/agents/ws?token=${getToken()}`)
    aws.onmessage = (e) => {
      const m = JSON.parse(e.data)
      if (m.event === 'activity' && String(m.agent_id) === String(id)) {
        setAgent(prev => prev ? {
          ...prev,
          activity: [...(prev.activity || []).slice(-39), m.entry],
        } : prev)
      }
      if (m.event === 'task_done' && String(m.agent_id) === String(id)) load()
      if (m.event === 'task_updated') load()
    }
    activityWs.current = aws

    // Streaming chat socket
    const cws = new WebSocket(`${getWsBase()}/agents/${id}/ws/chat?token=${getToken()}`)
    cws.onopen = () => setLive(true)
    cws.onclose = () => setLive(false)
    cws.onerror = () => setLive(false)
    cws.onmessage = (e) => {
      const m = JSON.parse(e.data)
      if (m.type === 'error') {
        message.error(m.content)
        setBusy(false)
      }
      if (m.type === 'start') {
        setMessages(prev => [...prev, { role: 'assistant', content: '', streaming: true }])
      }
      if (m.type === 'chunk') {
        setMessages(prev => {
          const next = [...prev]
          const last = next[next.length - 1]
          if (last?.streaming) last.content += m.content
          else next.push({ role: 'assistant', content: m.content, streaming: true })
          return next
        })
      }
      if (m.type === 'done') {
        setBusy(false)
        setSessionTokens(t => t + (m.tokens || 0))
        setMessages(prev => {
          const next = prev.map(x => ({ ...x, streaming: false }))
          if (speakRepliesRef.current) {
            const last = [...next].reverse().find(x => x.role === 'assistant' && x.content)
            if (last?.content) speakText(last.content)
          }
          return next
        })
      }
    }
    wsRef.current = cws

    return () => {
      aws.close()
      cws.close()
      stopSpeaking()
    }
  }, [id])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, tab])

  const send = async (text) => {
    const msg = (text ?? input).trim()
    if (!msg || busy) return
    setMessages(prev => [...prev, { role: 'user', content: msg }])
    setInput('')
    setBusy(true)
    if (wsRef.current?.readyState === 1) {
      wsRef.current.send(JSON.stringify({ message: msg }))
      return
    }
    // REST fallback
    try {
      const r = await api(`/agents/${id}/chat`, { method: 'POST', body: { message: msg } })
      setMessages(prev => [...prev, { role: 'assistant', content: r.reply }])
      setSessionTokens(t => t + (r.tokens || 0))
      if (speakRepliesRef.current && r.reply) speakText(r.reply)
    } catch (e) {
      message.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  const assignTask = async (v) => {
    try {
      await api(`/agents/${id}/tasks`, {
        method: 'POST',
        body: {
          title: v.title,
          description: v.description,
          project_id: v.project_id || null,
          priority: v.priority || 'medium',
          run_now: v.run_now !== false,
        },
      })
      message.success(v.run_now !== false ? 'Task queued — agent is working' : 'Task saved as todo')
      setTaskOpen(false)
      taskForm.resetFields()
      load()
      if (v.run_now !== false) setTab('tasks')
    } catch (e) {
      message.error(e.message)
    }
  }

  const saveSettings = async (v) => {
    try {
      await api(`/agents/${id}`, {
        method: 'PATCH',
        body: {
          name: v.name,
          personality: v.personality,
          model: v.model,
          idle_mode: v.never_idle ? 'never_idle' : 'allow_idle',
          permission_level: v.permission_level,
          escalate_when: v.escalate_when,
          escalate_reason: v.escalate_reason || '',
          escalate_to: v.escalate_to,
          escalate_human_id: v.escalate_human_id || null,
        },
      })
      message.success('Agent updated')
      load()
    } catch (e) {
      message.error(e.message)
    }
  }

  const saveHierarchy = async (v) => {
    try {
      await api(`/agents/${id}/hierarchy`, {
        method: 'PUT',
        body: {
          is_lead: v.is_lead,
          hierarchy_role: v.hierarchy_role,
          parent_id: v.parent_id || null,
          clear_parent: !v.parent_id,
          report_ids: v.report_ids || [],
        },
      })
      message.success('Hierarchy saved')
      load()
      api('/agents/').then(setAllAgents).catch(() => {})
    } catch (e) {
      message.error(e.message)
    }
  }

  const delegate = async (v) => {
    try {
      await api(`/agents/${id}/delegate`, {
        method: 'POST',
        body: {
          to_agent_id: v.to_agent_id,
          title: v.title,
          description: v.description,
          priority: v.priority || 'medium',
          run_now: v.run_now !== false,
        },
      })
      message.success('Task delegated')
      setDelegateOpen(false)
      delegateForm.resetFields()
      load()
    } catch (e) {
      message.error(e.message)
    }
  }

  const toggle = async () => {
    try {
      await api(`/agents/${id}/${agent.status === 'active' ? 'pause' : 'resume'}`, { method: 'POST' })
      load()
    } catch (e) {
      message.error(e.message)
    }
  }

  if (loading || !agent) {
    return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>
  }

  return (
    <div>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }} wrap>
        <Space wrap>
          <Button icon={<ArrowLeftOutlined />} onClick={() => nav('/agents')}>Agents</Button>
          <Typography.Title level={4} style={{ margin: 0 }}>{agent.name}</Typography.Title>
          <Tag color={agent.status === 'active' ? 'green' : 'orange'}>{agent.status}</Tag>
          <Tag>{agent.template_type}</Tag>
          {(agent.is_lead || agent.hierarchy_role === 'lead') && (
            <Tag icon={<CrownOutlined />} color="gold">Lead</Tag>
          )}
          {agent.parent_name && <Tag color="default">Reports to {agent.parent_name}</Tag>}
          <Tag color="blue">{modelLabel(agent.model)}</Tag>
          <Badge status={live ? 'processing' : 'default'} text={live ? 'Live chat connected' : 'Chat reconnecting…'} />
        </Space>
        <Space wrap>
          <Tag icon={<ThunderboltOutlined />} color="purple">{sessionTokens} tok this session</Tag>
          {(agent.is_lead || agent.reports?.length > 0) && (
            <Button icon={<TeamOutlined />} onClick={() => setDelegateOpen(true)}>Delegate</Button>
          )}
          <Button onClick={() => setTaskOpen(true)} type="primary">Assign task</Button>
          <Button
            icon={agent.status === 'active' ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
            onClick={toggle}
          >
            {agent.status === 'active' ? 'Pause' : 'Resume'}
          </Button>
          <Button icon={<CopyOutlined />} onClick={async () => {
            try {
              const c = await api(`/agents/${id}/duplicate`, { method: 'POST' })
              message.success('Agent duplicated')
              nav(`/agents/${c.id}`)
            } catch (e) { message.error(e.message) }
          }}>Duplicate</Button>
          <Popconfirm title="Delete agent?" onConfirm={async () => {
            await api(`/agents/${id}`, { method: 'DELETE' })
            nav('/agents')
          }}>
            <Button danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      </Space>

      <RowStats agent={agent} />

      <Card size="small" style={{ marginBottom: 12 }} title="Apps & training">
        <Space direction="vertical" style={{ width: '100%' }} size={4}>
          <Space wrap>
            <Typography.Text type="secondary">Apps:</Typography.Text>
            {(agentApps || []).length === 0 ? (
              <Typography.Text type="secondary">none</Typography.Text>
            ) : (
              agentApps.map((c) => (
                <Tag
                  key={c.id || c.connection_id}
                  color={c.status === 'connected' ? 'success' : c.status === 'error' ? 'error' : 'default'}
                >
                  {c.display_name || c.app_name || c.app_id}
                </Tag>
              ))
            )}
          </Space>
          <Space wrap>
            <Typography.Text type="secondary">Training files:</Typography.Text>
            {(agentTraining || []).length === 0 ? (
              <Typography.Text type="secondary">none allocated</Typography.Text>
            ) : (
              agentTraining.map((f) => (
                <Tag key={f.id}>{f.name}</Tag>
              ))
            )}
          </Space>
          <Space wrap>
            <Button type="link" size="small" onClick={() => nav('/settings?tab=apps')}>
              Connected apps
            </Button>
            <Button type="link" size="small" onClick={() => nav('/training')}>
              Training library
            </Button>
            <Button type="link" size="small" onClick={() => nav(`/training`)}>
              Program this agent
            </Button>
          </Space>
        </Space>
      </Card>

      <Card styles={{ body: { paddingTop: 8 } }}>
        <Tabs
          activeKey={tab}
          onChange={setTab}
          items={[
            {
              key: 'chat',
              label: 'Live chat',
              children: (
                <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 340px)', minHeight: 360 }}>
                  <div style={{ marginBottom: 8 }}>
                    <Space wrap size={[6, 6]} style={{ width: '100%', justifyContent: 'space-between' }}>
                      <Space wrap size={[6, 6]}>
                        {PROMPTS.map(p => (
                          <Button key={p} size="small" onClick={() => send(p)} disabled={busy}>{p}</Button>
                        ))}
                      </Space>
                      <VoiceControls
                        disabled={busy}
                        onTranscript={(text) => send(text)}
                        onPartial={(t) => setInput(t)}
                        speakReplies={speakReplies}
                        onSpeakRepliesChange={(v) => {
                          setSpeakReplies(v)
                          localStorage.setItem('voice_speak_replies', v ? '1' : '0')
                        }}
                      />
                    </Space>
                  </div>
                  <div style={{ flex: 1, overflowY: 'auto', background: '#fafafa', borderRadius: 8, padding: 12 }}>
                    {messages.length === 0 && (
                      <Empty description={`Start a live conversation with ${agent.name}`} />
                    )}
                    {messages.map((m, i) => (
                      <div key={i} style={{
                        display: 'flex',
                        justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start',
                        marginBottom: 8,
                      }}>
                        <div style={{
                          maxWidth: '75%', padding: '8px 14px', borderRadius: 12, whiteSpace: 'pre-wrap',
                          background: m.role === 'user' ? '#1668dc' : '#fff',
                          color: m.role === 'user' ? '#fff' : '#000',
                          border: m.role === 'user' ? 'none' : '1px solid #e8e8e8',
                          opacity: m.streaming ? 0.95 : 1,
                        }}>
                          {m.content || (m.streaming ? '…' : '')}
                        </div>
                      </div>
                    ))}
                    <div ref={bottomRef} />
                  </div>
                  <Space.Compact style={{ width: '100%', marginTop: 12 }}>
                    <Input
                      size="large"
                      value={input}
                      onChange={e => setInput(e.target.value)}
                      onPressEnter={() => send()}
                      placeholder={`Message ${agent.name}… or use the mic to talk`}
                      disabled={busy}
                    />
                    <Button size="large" type="primary" icon={<SendOutlined />} loading={busy} onClick={() => send()}>
                      Send
                    </Button>
                  </Space.Compact>
                  <Typography.Text type="secondary" style={{ fontSize: 11, marginTop: 6, display: 'block' }}>
                    Voice: click the mic and speak — your words become a message. Turn on “Speak” to hear replies aloud (Chrome/Edge recommended).
                  </Typography.Text>
                </div>
              ),
            },
            {
              key: 'skills',
              label: 'Skills',
              children: (
                <div>
                  <Typography.Paragraph type="secondary">
                    Skills let this agent spawn teammates, message other agents, use connected apps, assign humans, and save data to training. Enable skills below; chat may emit <Typography.Text code>```skill</Typography.Text> blocks automatically.
                  </Typography.Paragraph>
                  <List
                    dataSource={skills}
                    locale={{ emptyText: 'Loading skills…' }}
                    renderItem={(s) => (
                      <List.Item
                        actions={[
                          <Switch
                            key="en"
                            checked={!!s.enabled}
                            disabled={!s.role_allowed}
                            onChange={async (checked) => {
                              const enabled = skills
                                .filter((x) => (x.id === s.id ? checked : x.enabled))
                                .map((x) => x.id)
                              try {
                                const r = await api(`/agents/${id}/skills`, { method: 'PUT', body: { enabled } })
                                setSkills(r.skills || [])
                                message.success('Skills updated')
                              } catch (e) { message.error(e.message) }
                            }}
                          />,
                        ]}
                      >
                        <List.Item.Meta
                          title={<Space><ThunderboltOutlined /><span>{s.name}</span><Tag>{s.id}</Tag>{!s.role_allowed && <Tag color="orange">role blocked</Tag>}</Space>}
                          description={s.description}
                        />
                      </List.Item>
                    )}
                  />
                  <Divider />
                  <Typography.Title level={5}>Spawn agent</Typography.Title>
                  <Form form={spawnForm} layout="inline" onFinish={async (v) => {
                    setSkillBusy(true)
                    try {
                      const r = await api(`/agents/${id}/spawn`, { method: 'POST', body: v })
                      message.success(r.message || 'Spawned')
                      spawnForm.resetFields()
                      load()
                    } catch (e) { message.error(e.message) }
                    finally { setSkillBusy(false) }
                  }}>
                    <Form.Item name="name" rules={[{ required: true }]}><Input placeholder="Name" /></Form.Item>
                    <Form.Item name="template_type" initialValue="custom"><Input placeholder="template type" /></Form.Item>
                    <Form.Item name="hierarchy_role" initialValue="member">
                      <Select style={{ width: 120 }} options={[
                        { value: 'member', label: 'Member' },
                        { value: 'specialist', label: 'Specialist' },
                        { value: 'lead', label: 'Lead' },
                      ]} />
                    </Form.Item>
                    <Button type="primary" htmlType="submit" loading={skillBusy} icon={<RobotOutlined />}>Spawn</Button>
                  </Form>
                  <Divider />
                  <Typography.Title level={5}>Use connected app</Typography.Title>
                  <Space wrap>
                    {(agentApps || []).map((c) => (
                      <Button
                        key={c.id}
                        loading={skillBusy}
                        onClick={async () => {
                          setSkillBusy(true)
                          try {
                            const r = await api(`/agents/${id}/skills/run`, {
                              method: 'POST',
                              body: { skill: 'use_app', args: { app_id: c.app_id, action: 'status' } },
                            })
                            if (r.ok) message.success(r.message || `${c.app_name} OK`)
                            else message.error(r.error || 'App action failed')
                          } catch (e) { message.error(e.message) }
                          finally { setSkillBusy(false) }
                        }}
                      >
                        Test {c.app_name || c.app_id}
                      </Button>
                    ))}
                    {!agentApps?.length && <Typography.Text type="secondary">Link apps in Settings → Connected apps, then allocate to this agent.</Typography.Text>}
                  </Space>
                  <Divider />
                  <Typography.Title level={5}>Assign human</Typography.Title>
                  <Space wrap>
                    {humans.filter((h) => h.status === 'active').map((h) => (
                      <Button
                        key={h.id}
                        onClick={async () => {
                          const title = window.prompt(`Task title for ${h.name}`, 'Please handle this work item')
                          if (!title) return
                          setSkillBusy(true)
                          try {
                            const r = await api(`/agents/${id}/skills/run`, {
                              method: 'POST',
                              body: { skill: 'assign_human', args: { human_id: h.id, title, description: title } },
                            })
                            if (r.ok) message.success(r.message)
                            else message.error(r.error)
                          } catch (e) { message.error(e.message) }
                          finally { setSkillBusy(false) }
                        }}
                      >
                        <TeamOutlined /> {h.name}
                      </Button>
                    ))}
                    {!humans.length && <Button type="link" onClick={() => nav('/humans')}>Add humans</Button>}
                  </Space>
                </div>
              ),
            },
            {
              key: 'memory',
              label: `Data (${memories.length})`,
              children: (
                <div>
                  <Typography.Paragraph type="secondary">
                    Agent data vault — notes, facts, deliverables. Optionally promote into the Training library.
                  </Typography.Paragraph>
                  <Form
                    form={memForm}
                    layout="vertical"
                    onFinish={async (v) => {
                      try {
                        const r = await api(`/agents/${id}/memory`, { method: 'POST', body: v })
                        message.success(r.message || 'Saved')
                        memForm.resetFields()
                        loadSkillsExtra()
                      } catch (e) { message.error(e.message) }
                    }}
                  >
                    <Form.Item name="title" label="Title"><Input placeholder="Optional title" /></Form.Item>
                    <Form.Item name="content" label="Content" rules={[{ required: true }]}>
                      <Input.TextArea rows={4} placeholder="Data this agent should remember…" />
                    </Form.Item>
                    <Form.Item name="kind" label="Kind" initialValue="note">
                      <Select options={[
                        { value: 'note', label: 'Note' },
                        { value: 'fact', label: 'Fact' },
                        { value: 'deliverable', label: 'Deliverable' },
                        { value: 'crm', label: 'CRM' },
                      ]} />
                    </Form.Item>
                    <Form.Item name="tags" label="Tags"><Input placeholder="comma,separated" /></Form.Item>
                    <Form.Item name="save_to_training" valuePropName="checked" initialValue={false}>
                      <Switch checkedChildren="Also save to Training" unCheckedChildren="Vault only" />
                    </Form.Item>
                    <Button type="primary" htmlType="submit">Save data</Button>
                  </Form>
                  <Divider />
                  <List
                    dataSource={memories}
                    locale={{ emptyText: 'No saved data yet' }}
                    renderItem={(m) => (
                      <List.Item
                        actions={[
                          <Popconfirm key="d" title="Delete?" onConfirm={async () => {
                            await api(`/agents/${id}/memory/${m.id}`, { method: 'DELETE' })
                            loadSkillsExtra()
                          }}><Button size="small" danger>Delete</Button></Popconfirm>,
                        ]}
                      >
                        <List.Item.Meta
                          title={<Space><Tag>{m.kind}</Tag>{m.title || 'Untitled'}{m.knowledge_file_id && <Tag color="blue">in training</Tag>}</Space>}
                          description={<div style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>}
                        />
                      </List.Item>
                    )}
                  />
                </div>
              ),
            },
            {
              key: 'a2a',
              label: 'Agent chat',
              children: (
                <div>
                  <Typography.Paragraph type="secondary">
                    Converse with other agents. Messages are stored and can trigger an auto-reply from the target agent.
                  </Typography.Paragraph>
                  <Form
                    form={a2aForm}
                    layout="vertical"
                    onFinish={async (v) => {
                      setSkillBusy(true)
                      try {
                        const r = await api(`/agents/${id}/message-agent`, { method: 'POST', body: { ...v, expect_reply: true } })
                        if (r.ok) {
                          message.success(r.message)
                          if (r.reply) message.info(`Reply: ${String(r.reply).slice(0, 120)}…`)
                        } else message.error(r.error)
                        a2aForm.resetFields(['message'])
                        loadSkillsExtra()
                      } catch (e) { message.error(e.message) }
                      finally { setSkillBusy(false) }
                    }}
                  >
                    <Form.Item name="to_agent_id" label="To agent" rules={[{ required: true }]}>
                      <Select
                        showSearch
                        optionFilterProp="label"
                        options={allAgents.filter((a) => String(a.id) !== String(id)).map((a) => ({
                          value: a.id,
                          label: `${a.name} (${a.hierarchy_role || 'member'})`,
                        }))}
                      />
                    </Form.Item>
                    <Form.Item name="message" label="Message" rules={[{ required: true }]}>
                      <Input.TextArea rows={3} placeholder="Internal instruction or question…" />
                    </Form.Item>
                    <Button type="primary" htmlType="submit" loading={skillBusy} icon={<MessageOutlined />}>Send to agent</Button>
                  </Form>
                  <Divider />
                  <List
                    dataSource={agentMsgs}
                    locale={{ emptyText: 'No agent-to-agent messages yet' }}
                    renderItem={(m) => (
                      <List.Item>
                        <List.Item.Meta
                          title={<Space><Tag color="blue">{m.from_name}</Tag>→<Tag color="purple">{m.to_name}</Tag></Space>}
                          description={<div style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>}
                        />
                      </List.Item>
                    )}
                  />
                </div>
              ),
            },
            {
              key: 'tasks',
              label: `Tasks (${agent.stats?.tasks || 0})`,
              children: (
                <div>
                  <Space style={{ marginBottom: 12 }}>
                    <Button type="primary" onClick={() => setTaskOpen(true)}>New task</Button>
                    <Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button>
                    <Button type="link" onClick={() => nav('/tasks')}>Open tasks board →</Button>
                  </Space>
                  <List
                    dataSource={agent.recent_tasks || []}
                    locale={{ emptyText: 'No tasks yet — assign one from live chat or the board' }}
                    renderItem={t => (
                      <List.Item
                        style={{ cursor: 'pointer' }}
                        onClick={() => setSelectedTask(t)}
                        actions={[
                          t.status !== 'completed' && t.status !== 'in_progress' && (
                            <Button key="run" type="link" onClick={async (e) => {
                              e.stopPropagation()
                              try {
                                await api(`/agents/tasks/${t.id}/run`, { method: 'POST' })
                                message.success('Running…')
                                load()
                              } catch (err) { message.error(err.message) }
                            }}>Run</Button>
                          ),
                        ].filter(Boolean)}
                      >
                        <List.Item.Meta
                          title={
                            <Space wrap>
                              {t.title}
                              <Tag color={STATUS_COLOR[t.status]}>{t.status}</Tag>
                              <Tag>{t.priority}</Tag>
                              {t.tokens_used > 0 && (
                                <Tag color="purple">{t.tokens_used} tok · ${Number(t.cost).toFixed(4)}</Tag>
                              )}
                            </Space>
                          }
                          description={t.description}
                        />
                      </List.Item>
                    )}
                  />
                </div>
              ),
            },
            {
              key: 'team',
              label: `Team (${agent.reports_count || agent.reports?.length || 0})`,
              children: (
                <div>
                  <Space style={{ marginBottom: 12 }} wrap>
                    <Button type="primary" icon={<TeamOutlined />} onClick={() => setDelegateOpen(true)}
                      disabled={!(agent.reports?.length || agent.is_lead)}>
                      Delegate task
                    </Button>
                    <Button onClick={() => nav('/hierarchy')}>Open hierarchy map</Button>
                  </Space>
                  {agent.team_context && (
                    <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                      {agent.team_context}
                    </Typography.Paragraph>
                  )}
                  <Typography.Title level={5}>Direct reports</Typography.Title>
                  <List
                    dataSource={agent.reports || []}
                    locale={{ emptyText: 'No reports yet — set hierarchy below or on Hierarchy page' }}
                    renderItem={r => (
                      <List.Item
                        style={{ cursor: 'pointer' }}
                        onClick={() => nav(`/agents/${r.id}`)}
                        actions={[
                          <Button key="d" type="link" onClick={(e) => {
                            e.stopPropagation()
                            setDelegateOpen(true)
                            delegateForm.setFieldsValue({ to_agent_id: r.id })
                          }}>Delegate</Button>,
                        ]}
                      >
                        <List.Item.Meta
                          avatar={<RobotOutlined />}
                          title={<Space>{r.name}<Tag>{r.status}</Tag><Tag>{r.hierarchy_role}</Tag></Space>}
                          description={`${r.template_type} · ${r.open_tasks || 0} open tasks · ${modelLabel(r.model)}`}
                        />
                      </List.Item>
                    )}
                  />
                  {(agent.team_tasks || []).length > 0 && (
                    <>
                      <Typography.Title level={5} style={{ marginTop: 16 }}>Team tasks</Typography.Title>
                      <List
                        size="small"
                        dataSource={agent.team_tasks}
                        renderItem={t => (
                          <List.Item>
                            <Space wrap>
                              <Tag color={STATUS_COLOR[t.status]}>{t.status}</Tag>
                              <span>{t.title}</span>
                              {t.agent_name && <Tag color="geekblue">{t.agent_name}</Tag>}
                            </Space>
                          </List.Item>
                        )}
                      />
                    </>
                  )}
                  <Divider />
                  <Typography.Title level={5}>Set hierarchy</Typography.Title>
                  <Form form={hierForm} layout="vertical" onFinish={saveHierarchy} style={{ maxWidth: 480 }}>
                    <Form.Item name="is_lead" label="This is a lead agent" valuePropName="checked">
                      <Switch checkedChildren="Lead" unCheckedChildren="Member" />
                    </Form.Item>
                    <Form.Item name="hierarchy_role" label="Role">
                      <Select options={[
                        { value: 'lead', label: 'Lead' },
                        { value: 'member', label: 'Member' },
                        { value: 'specialist', label: 'Specialist' },
                      ]} />
                    </Form.Item>
                    <Form.Item name="parent_id" label="Reports to">
                      <Select
                        allowClear
                        placeholder="No parent"
                        options={allAgents.filter(a => a.id !== Number(id)).map(a => ({
                          value: a.id,
                          label: `${a.name}${a.is_lead ? ' (lead)' : ''}`,
                        }))}
                      />
                    </Form.Item>
                    <Form.Item name="report_ids" label="Direct reports">
                      <Select
                        mode="multiple"
                        allowClear
                        placeholder="Team members"
                        options={allAgents.filter(a => a.id !== Number(id)).map(a => ({
                          value: a.id,
                          label: a.name,
                        }))}
                      />
                    </Form.Item>
                    <Button type="primary" htmlType="submit">Save hierarchy</Button>
                  </Form>
                </div>
              ),
            },
            {
              key: 'activity',
              label: 'Live activity',
              children: (
                <div style={{ maxHeight: 480, overflowY: 'auto', background: '#0f172a', borderRadius: 8, padding: 16 }}>
                  <Timeline
                    items={(agent.activity || []).map(entry => ({
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
              ),
            },
            {
              key: 'settings',
              label: 'Settings',
              children: (
                <Form form={editForm} layout="vertical" onFinish={saveSettings} style={{ maxWidth: 560 }}>
                  <Form.Item name="name" label="Name" rules={[{ required: true }]}><Input /></Form.Item>
                  <Form.Item name="personality" label="Personality"><Input.TextArea rows={4} /></Form.Item>
                  <Form.Item name="model" label="Model"><ModelSelect style={{ width: '100%' }} /></Form.Item>
                  <Form.Item name="never_idle" label="Never be idle (self-running work when free)" valuePropName="checked"><Switch /></Form.Item>
                  <Divider>Permissions & escalation</Divider>
                  <Form.Item name="permission_level" label="Permission level" rules={[{ required: true }]}>
                    <Select options={[
                      { value: 'viewer', label: 'Viewer — read only' },
                      { value: 'operator', label: 'Operator — execute own work' },
                      { value: 'lead', label: 'Lead — delegate, spawn, assign humans' },
                      { value: 'admin', label: 'Admin — full control' },
                    ]} />
                  </Form.Item>
                  <Form.Item name="escalate_when" label="When to escalate" rules={[{ required: true }]}>
                    <Select options={[
                      { value: 'never', label: 'Never auto-escalate' },
                      { value: 'on_failure', label: 'On failure' },
                      { value: 'on_blocked', label: 'When blocked' },
                      { value: 'high_priority', label: 'High / urgent priority' },
                      { value: 'sla_breach', label: 'SLA / stuck too long' },
                      { value: 'customer_vip', label: 'VIP / tagged customers' },
                      { value: 'value_threshold', label: 'High deal value' },
                      { value: 'always_review', label: 'Always review' },
                      { value: 'custom', label: 'Custom rule (use reason below)' },
                    ]} />
                  </Form.Item>
                  <Form.Item name="escalate_reason" label="Escalation reason / custom rule">
                    <Input.TextArea rows={2} placeholder="e.g. Escalate refunds over £500 or legal risk" />
                  </Form.Item>
                  <Form.Item name="escalate_to" label="Escalate to">
                    <Select options={[
                      { value: 'parent', label: 'Reporting lead / parent agent' },
                      { value: 'orchestrator', label: 'Main orchestrator' },
                      { value: 'human', label: 'Human (pick below)' },
                      { value: 'owner', label: 'Workspace owner' },
                    ]} />
                  </Form.Item>
                  <Form.Item name="escalate_human_id" label="Escalate human (optional)">
                    <Select allowClear options={humans.map((h) => ({ value: h.id, label: h.name }))} placeholder="Human teammate" />
                  </Form.Item>
                  <Divider />
                  <Descriptions size="small" column={1}>
                    <Descriptions.Item label="Type">{agent.template_type}</Descriptions.Item>
                    <Descriptions.Item label="Permission"><Tag>{agent.permission_level || 'operator'}</Tag></Descriptions.Item>
                    <Descriptions.Item label="Escalate when"><Tag color="orange">{agent.escalate_when || 'on_failure'}</Tag></Descriptions.Item>
                    <Descriptions.Item label="Created">{agent.created_at && new Date(agent.created_at).toLocaleString()}</Descriptions.Item>
                    <Descriptions.Item label="Config">
                      <Typography.Paragraph code copyable style={{ margin: 0, fontSize: 12 }}>
                        {JSON.stringify(agent.config || {}, null, 0)}
                      </Typography.Paragraph>
                    </Descriptions.Item>
                  </Descriptions>
                  <Button type="primary" htmlType="submit" style={{ marginTop: 12 }}>Save</Button>
                </Form>
              ),
            },
          ]}
        />
      </Card>

      <Modal title="Delegate to team member" open={delegateOpen} onCancel={() => setDelegateOpen(false)} footer={null} destroyOnClose>
        <Form form={delegateForm} layout="vertical" onFinish={delegate} initialValues={{ priority: 'medium', run_now: true }}>
          <Form.Item name="to_agent_id" label="Delegate to" rules={[{ required: true }]}>
            <Select
              options={(agent.reports?.length
                ? agent.reports
                : allAgents.filter(a => a.id !== Number(id))
              ).map(a => ({ value: a.id, label: a.name }))}
              placeholder="Select agent"
            />
          </Form.Item>
          <Form.Item name="title" label="Title"><Input /></Form.Item>
          <Form.Item name="description" label="Task" rules={[{ required: true }]}>
            <Input.TextArea rows={3} placeholder="What should they do?" />
          </Form.Item>
          <Form.Item name="priority" label="Priority">
            <Select options={[
              { value: 'low', label: 'Low' },
              { value: 'medium', label: 'Medium' },
              { value: 'high', label: 'High' },
              { value: 'urgent', label: 'Urgent' },
            ]} />
          </Form.Item>
          <Form.Item name="run_now" label="Run immediately" valuePropName="checked"><Switch /></Form.Item>
          <Button type="primary" htmlType="submit" block>Delegate</Button>
        </Form>
      </Modal>

      <Modal title="Assign task" open={taskOpen} onCancel={() => setTaskOpen(false)} footer={null} destroyOnClose>
        <Form form={taskForm} layout="vertical" onFinish={assignTask} initialValues={{ priority: 'medium', run_now: true }}>
          <Form.Item name="title" label="Title"><Input placeholder="Optional short title" /></Form.Item>
          <Form.Item name="description" label="What should the agent do?" rules={[{ required: true }]}>
            <Input.TextArea rows={4} placeholder="e.g. Draft outreach for 5 landlord leads this week" />
          </Form.Item>
          <Form.Item name="project_id" label="Link to project (optional)">
            <Select allowClear placeholder="None" options={projects.map(p => ({ value: p.id, label: p.name }))} />
          </Form.Item>
          <Form.Item name="priority" label="Priority">
            <Select options={[
              { value: 'low', label: 'Low' },
              { value: 'medium', label: 'Medium' },
              { value: 'high', label: 'High' },
              { value: 'urgent', label: 'Urgent' },
            ]} />
          </Form.Item>
          <Form.Item name="run_now" label="Run immediately with agent" valuePropName="checked"><Switch /></Form.Item>
          <Button type="primary" htmlType="submit" block>Assign</Button>
        </Form>
      </Modal>

      <Modal
        title={selectedTask?.title || 'Task'}
        open={!!selectedTask}
        onCancel={() => setSelectedTask(null)}
        width={720}
        footer={[
          <Button key="close" onClick={() => setSelectedTask(null)}>Close</Button>,
          selectedTask && selectedTask.status !== 'completed' && (
            <Button key="run" type="primary" onClick={async () => {
              try {
                await api(`/agents/tasks/${selectedTask.id}/run`, { method: 'POST' })
                message.success('Agent running task')
                setSelectedTask(null)
                load()
              } catch (e) { message.error(e.message) }
            }}>Run with agent</Button>
          ),
        ]}
      >
        {selectedTask && (
          <>
            <Space wrap style={{ marginBottom: 12 }}>
              <Tag color={STATUS_COLOR[selectedTask.status]}>{selectedTask.status}</Tag>
              <Tag>{selectedTask.priority}</Tag>
              {selectedTask.project_name && <Tag color="cyan">{selectedTask.project_name}</Tag>}
            </Space>
            <Typography.Paragraph>{selectedTask.description}</Typography.Paragraph>
            {selectedTask.result && (
              <>
                <Typography.Title level={5}>Deliverable</Typography.Title>
                <div style={{
                  background: '#f6f8fa', borderRadius: 8, padding: 12,
                  whiteSpace: 'pre-wrap', maxHeight: 320, overflowY: 'auto',
                }}>
                  {selectedTask.result}
                </div>
              </>
            )}
          </>
        )}
      </Modal>
    </div>
  )
}

function RowStats({ agent }) {
  const s = agent.stats || {}
  return (
    <Space wrap style={{ marginBottom: 16 }}>
      <Card size="small"><Typography.Text type="secondary">Open tasks </Typography.Text><strong>{s.open ?? 0}</strong></Card>
      <Card size="small"><Typography.Text type="secondary">Completed </Typography.Text><strong>{s.completed ?? 0}</strong></Card>
      <Card size="small"><Typography.Text type="secondary">Team reports </Typography.Text><strong>{s.reports ?? agent.reports_count ?? 0}</strong></Card>
      <Card size="small"><Typography.Text type="secondary">Chats </Typography.Text><strong>{s.conversations ?? 0}</strong></Card>
      <Card size="small">
        <Typography.Text type="secondary">Role </Typography.Text>
        <strong>{agent.hierarchy_role || (agent.is_lead ? 'lead' : 'member')}</strong>
      </Card>
    </Space>
  )
}
