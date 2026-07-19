import React, { useEffect, useRef, useState } from 'react'
import {
  Card, Tabs, Button, Space, Tag, Typography, Input, Form, Select,
  message, Spin, Modal, Switch, Badge,
} from 'antd'
import {
  ArrowLeftOutlined, ThunderboltOutlined, MessageOutlined,
  CrownOutlined, TeamOutlined, SettingOutlined, CheckSquareOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { api, connectAuthedWs } from '../api'
import PageHeader from '../components/PageHeader'
import PageShell from '../components/PageShell'
import AgentSkillsPanel from '../components/AgentSkillsPanel'
import { speakText, stopSpeaking } from '../components/VoiceControls'
import { hapticMedium, hapticSuccess, hapticError } from '../native'
import { modelLabel } from '../models'
import { STATUS_COLOR } from './agent-detail/constants'
import AgentConfigTab from './agent-detail/AgentConfigTab'
import AgentTasksTab from './agent-detail/AgentTasksTab'
import AgentTeamTab from './agent-detail/AgentTeamTab'
import AgentMemoryTab from './agent-detail/AgentMemoryTab'
import AgentA2ATab from './agent-detail/AgentA2ATab'
import AgentActivityTab from './agent-detail/AgentActivityTab'
import AgentChatTab from './agent-detail/AgentChatTab'
import AgentActionsCard from './agent-detail/AgentActionsCard'
import AgentIntegrationsCard from './agent-detail/AgentIntegrationsCard'
import AgentStatsRow from './agent-detail/AgentStatsRow'

/**
 * Manage agent page (`/agents/:id/manage`).
 * Shell: load agent, tabs, modals — tab bodies live under agent-detail/.
 */
export default function AgentDetail() {
  const { id } = useParams()
  const nav = useNavigate()
  const [agent, setAgent] = useState(null)
  const [loading, setLoading] = useState(true)
  // Manage page defaults to Skills (full chat is at /agents/:id)
  const [tab, setTab] = useState('skills')
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
  const [templates, setTemplates] = useState([])
  const [meetingBusy, setMeetingBusy] = useState(false)
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
      .then((a) => {
        setAgent(a)
        if (Array.isArray(a.chat?.messages) && a.chat.messages.length) {
          setMessages(a.chat.messages.map((m) => ({ role: m.role, content: m.content })))
        } else {
          setMessages([])
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
          report_ids: (a.reports || []).map((r) => r.id),
        })
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
      .catch((e) => { message.error(e.message); nav('/agents') })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    api('/org/projects').then(setProjects).catch(() => setProjects([]))
    api('/agents/').then(setAllAgents).catch(() => setAllAgents([]))
    api('/templates/')
      .then(async (t) => {
        const normalize = (p) => (
          Array.isArray(p) ? p
            : Array.isArray(p?.templates) ? p.templates
              : Array.isArray(p?.items) ? p.items
                : []
        )
        let list = normalize(t)
        if (!list.length) {
          try { await api('/templates/ensure', { method: 'POST' }) } catch { /* ignore */ }
          try { list = normalize(await api('/templates/')) } catch { list = [] }
        }
        // Offline fallback so Spawn card never has an empty Select
        if (!list.length) {
          list = [
            { id: 'fb-sales', name: 'Sales Agent', type: 'sales' },
            { id: 'fb-support', name: 'Support Agent', type: 'support' },
            { id: 'fb-ops', name: 'Ops Agent', type: 'ops' },
            { id: 'fb-custom', name: 'Custom agent', type: 'custom' },
          ]
        }
        setTemplates(list)
      })
      .catch(() => setTemplates([
        { id: 'fb-custom', name: 'Custom agent', type: 'custom' },
        { id: 'fb-sales', name: 'Sales Agent', type: 'sales' },
        { id: 'fb-support', name: 'Support Agent', type: 'support' },
      ]))

    const aws = connectAuthedWs('/agents/ws')
    aws.onmessage = (e) => {
      const m = JSON.parse(e.data)
      if (m.type === 'auth_ok') return
      if (m.event === 'activity' && String(m.agent_id) === String(id)) {
        setAgent((prev) => (prev ? {
          ...prev,
          activity: [...(prev.activity || []).slice(-39), m.entry],
        } : prev))
      }
      if (m.event === 'task_done' && String(m.agent_id) === String(id)) load()
      if (m.event === 'task_updated') load()
    }
    activityWs.current = aws

    const cws = connectAuthedWs(`/agents/${id}/ws/chat`)
    cws.onopen = () => setLive(true)
    cws.onclose = () => setLive(false)
    cws.onerror = () => setLive(false)
    cws.onmessage = (e) => {
      const m = JSON.parse(e.data)
      if (m.type === 'auth_ok') return
      if (m.type === 'error') {
        message.error(m.content)
        setBusy(false)
      }
      if (m.type === 'start') {
        setMessages((prev) => [...prev, { role: 'assistant', content: '', streaming: true }])
      }
      if (m.type === 'chunk') {
        setMessages((prev) => {
          const next = [...prev]
          const last = next[next.length - 1]
          if (last?.streaming) last.content += m.content
          else next.push({ role: 'assistant', content: m.content, streaming: true })
          return next
        })
      }
      if (m.type === 'done') {
        setBusy(false)
        setSessionTokens((t) => t + (m.tokens || 0))
        setMessages((prev) => {
          const next = prev.map((x) => ({ ...x, streaming: false }))
          if (speakRepliesRef.current) {
            const last = [...next].reverse().find((x) => x.role === 'assistant' && x.content)
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
    if (!msg) return
    if (busy) {
      setInput(msg)
      message.info('Agent is still replying — speech is in the box. Tap Send when ready.')
      return
    }
    hapticMedium()
    setMessages((prev) => [...prev, { role: 'user', content: msg }])
    setInput('')
    setBusy(true)
    if (wsRef.current?.readyState === 1) {
      wsRef.current.send(JSON.stringify({ message: msg }))
      return
    }
    try {
      const r = await api(`/agents/${id}/chat`, { method: 'POST', body: { message: msg } })
      setMessages((prev) => [...prev, { role: 'assistant', content: r.reply }])
      setSessionTokens((t) => t + (r.tokens || 0))
      hapticSuccess()
      if (speakRepliesRef.current && r.reply) speakText(r.reply)
    } catch (e) {
      hapticError()
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

  const openMeetingRoom = async () => {
    if (!agent || meetingBusy) return
    setMeetingBusy(true)
    try {
      const r = await api('/meetings', {
        method: 'POST',
        body: {
          name: `Meeting with ${agent.name}`,
          agent_id: agent.id,
        },
      })
      const roomId = r?.id ?? r?.meeting_id
      if (!roomId) throw new Error('Meeting room created but no id returned')
      nav(`/meetings/${roomId}`)
    } catch (e) {
      message.error(e.message || 'Could not open meeting room')
    } finally {
      setMeetingBusy(false)
    }
  }

  if (loading || !agent) {
    return (
      <PageShell>
        <Card bordered className="aba-soft-card">
          <div style={{ textAlign: 'center', padding: '64px 24px' }}>
            <Spin size="large" tip="Loading agent…" />
          </div>
        </Card>
      </PageShell>
    )
  }

  const tabItems = [
    {
      key: 'skills',
      label: (
        <span><ThunderboltOutlined /> Skills</span>
      ),
      children: (
        <AgentSkillsPanel
          id={id}
          skills={skills}
          setSkills={setSkills}
          skillBusy={skillBusy}
          setSkillBusy={setSkillBusy}
          templates={templates}
          spawnForm={spawnForm}
          load={load}
          setAllAgents={setAllAgents}
          agentApps={agentApps}
          humans={humans}
          nav={nav}
        />
      ),
    },
    {
      key: 'settings',
      label: (
        <span><SettingOutlined /> Config</span>
      ),
      children: (
        <AgentConfigTab
          editForm={editForm}
          saveSettings={saveSettings}
          agent={agent}
          humans={humans}
        />
      ),
    },
    {
      key: 'tasks',
      label: (
        <span><CheckSquareOutlined /> Tasks ({agent.stats?.tasks || 0})</span>
      ),
      children: (
        <AgentTasksTab
          agent={agent}
          setTaskOpen={setTaskOpen}
          load={load}
          setSelectedTask={setSelectedTask}
          nav={nav}
        />
      ),
    },
    {
      key: 'team',
      label: (
        <span><TeamOutlined /> Team ({agent.reports_count || agent.reports?.length || 0})</span>
      ),
      children: (
        <AgentTeamTab
          agent={agent}
          setDelegateOpen={setDelegateOpen}
          delegateForm={delegateForm}
          nav={nav}
          hierForm={hierForm}
          saveHierarchy={saveHierarchy}
          allAgents={allAgents}
          id={id}
        />
      ),
    },
    {
      key: 'memory',
      label: `Data (${memories.length})`,
      children: (
        <AgentMemoryTab
          id={id}
          memForm={memForm}
          loadSkillsExtra={loadSkillsExtra}
          memories={memories}
        />
      ),
    },
    {
      key: 'a2a',
      label: 'Agent chat',
      children: (
        <AgentA2ATab
          id={id}
          a2aForm={a2aForm}
          skillBusy={skillBusy}
          setSkillBusy={setSkillBusy}
          allAgents={allAgents}
          loadSkillsExtra={loadSkillsExtra}
          agentMsgs={agentMsgs}
        />
      ),
    },
    {
      key: 'activity',
      label: 'Live activity',
      children: <AgentActivityTab agent={agent} />,
    },
    {
      key: 'chat',
      label: (
        <span><MessageOutlined /> Live chat</span>
      ),
      children: (
        <AgentChatTab
          agent={agent}
          messages={messages}
          input={input}
          setInput={setInput}
          send={send}
          busy={busy}
          speakReplies={speakReplies}
          setSpeakReplies={setSpeakReplies}
          bottomRef={bottomRef}
        />
      ),
    },
  ]

  return (
    <PageShell>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Card bordered className="aba-soft-card" styles={{ body: { paddingBlock: 16 } }}>
          <PageHeader
            title={(
              <Space wrap size={[8, 4]}>
                <span>{agent.name}</span>
                <Tag color={agent.status === 'active' ? 'green' : 'orange'}>{agent.status}</Tag>
                <Tag>{agent.template_type}</Tag>
                {(agent.is_lead || agent.hierarchy_role === 'lead') && (
                  <Tag icon={<CrownOutlined />} color="gold">Lead</Tag>
                )}
                {agent.parent_name && <Tag color="default">Reports to {agent.parent_name}</Tag>}
                <Tag color="blue">{modelLabel(agent.model)}</Tag>
              </Space>
            )}
            subtitle={(
              <Space wrap size={[8, 4]}>
                <span>Manage skills, config, and actions for this agent.</span>
                <Badge status={live ? 'processing' : 'default'} text={live ? 'Live chat connected' : 'Chat reconnecting…'} />
                <Tag icon={<ThunderboltOutlined />} color="purple">{sessionTokens} tok this session</Tag>
              </Space>
            )}
            style={{ marginBottom: 0 }}
            extra={(
              <Space wrap>
                <Button icon={<ArrowLeftOutlined />} onClick={() => nav(`/agents/${id}`)}>Back to chat</Button>
                <Button type="primary" icon={<MessageOutlined />} onClick={() => nav(`/agents/${id}`)}>Talk</Button>
              </Space>
            )}
          />
        </Card>

        <AgentActionsCard
          agent={agent}
          id={id}
          nav={nav}
          setTaskOpen={setTaskOpen}
          setDelegateOpen={setDelegateOpen}
          meetingBusy={meetingBusy}
          openMeetingRoom={openMeetingRoom}
          toggle={toggle}
        />

        <AgentStatsRow agent={agent} />

        <AgentIntegrationsCard
          agentApps={agentApps}
          agentTraining={agentTraining}
          nav={nav}
        />

        <Card bordered className="aba-soft-card" styles={{ body: { paddingTop: 8 } }}>
          <Tabs activeKey={tab} onChange={setTab} items={tabItems} />
        </Card>
      </Space>

      <Modal title="Delegate to team member" open={delegateOpen} onCancel={() => setDelegateOpen(false)} footer={null} destroyOnClose>
        <Form form={delegateForm} layout="vertical" onFinish={delegate} initialValues={{ priority: 'medium', run_now: true }}>
          <Form.Item name="to_agent_id" label="Delegate to" rules={[{ required: true }]}>
            <Select
              options={(agent.reports?.length
                ? agent.reports
                : allAgents.filter((a) => a.id !== Number(id))
              ).map((a) => ({ value: a.id, label: a.name }))}
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
            <Select allowClear placeholder="None" options={projects.map((p) => ({ value: p.id, label: p.name }))} />
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
            <Button
              key="run"
              type="primary"
              onClick={async () => {
                try {
                  await api(`/agents/tasks/${selectedTask.id}/run`, { method: 'POST' })
                  message.success('Agent running task')
                  setSelectedTask(null)
                  load()
                } catch (e) { message.error(e.message) }
              }}
            >
              Run with agent
            </Button>
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
                }}
                >
                  {selectedTask.result}
                </div>
              </>
            )}
          </>
        )}
      </Modal>
    </PageShell>
  )
}
