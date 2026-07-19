import React from 'react'
import {
  Card, Space, Typography, Tag, List, Switch, Button, Form, Input, Select, message,
} from 'antd'
import {
  ThunderboltOutlined, RobotOutlined, AppstoreOutlined, TeamOutlined,
} from '@ant-design/icons'
import { api } from '../api'

/** Agent manage page — Skills tab body. */
export default function AgentSkillsPanel({
  id, skills, setSkills, skillBusy, setSkillBusy,
  templates, spawnForm, load, setAllAgents, agentApps, humans, nav,
}) {
  return (
<Space direction="vertical" size={12} style={{ width: '100%' }}>
  <Card bordered size="small" className="aba-soft-card">
    <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
      Skills let this agent spawn teammates, message other agents, use connected apps, assign humans, and save data to training. Enable skills below; chat may emit <Typography.Text code>{'```skill'}</Typography.Text> blocks automatically.
    </Typography.Paragraph>
  </Card>

  <Card
    bordered
    size="small"
    className="aba-soft-card"
    title={(
      <Space wrap>
        <ThunderboltOutlined />
        <span>Enabled skills</span>
        {skills.length > 0 && (
          <Tag color="blue">
            {skills.filter((s) => s.enabled).length}/{skills.length}
          </Tag>
        )}
      </Space>
    )}
    extra={skills.length > 0 ? (
      <Space wrap size={[8, 4]}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {skills.filter((s) => s.enabled && !s.premium).length}/
          {skills.filter((s) => !s.premium && s.role_allowed).length} free on
        </Typography.Text>
        <Button
          size="small"
          type="primary"
          ghost
          loading={skillBusy}
          disabled={
            !skills.some((s) => !s.premium && s.role_allowed && !s.enabled)
          }
          onClick={async () => {
            // PUT /agents/:id/skills — enable every free role-allowed skill;
            // keep any already-enabled premium skills.
            const freeIds = skills
              .filter((s) => !s.premium && s.role_allowed)
              .map((s) => s.id)
            const premiumOn = skills
              .filter((s) => s.premium && s.enabled)
              .map((s) => s.id)
            const enabled = [...new Set([...freeIds, ...premiumOn])]
            setSkillBusy(true)
            try {
              const r = await api(`/agents/${id}/skills`, {
                method: 'PUT',
                body: { enabled },
              })
              setSkills(r.skills || [])
              message.success(`Enabled ${freeIds.length} free skills`)
            } catch (e) {
              message.error(e.message)
            } finally {
              setSkillBusy(false)
            }
          }}
        >
          Enable all free
        </Button>
      </Space>
    ) : null}
  >
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
            title={
              <Space wrap>
                <ThunderboltOutlined />
                <span>{s.name}</span>
                <Tag>{s.id}</Tag>
                {s.enabled && <Tag color="success">on</Tag>}
                {s.premium && <Tag color="gold">PREMIUM • {s.cost_credits || 0.02} credits</Tag>}
                {!s.role_allowed && <Tag color="orange">role blocked</Tag>}
              </Space>
            }
            description={
              <div>
                {s.description}
                {s.premium && (
                  <div style={{ fontSize: 11, color: '#d48806', marginTop: 2 }}>
                    Real delivery (Email/SMS/WhatsApp/Voice) — charged per use
                  </div>
                )}
              </div>
            }
          />
        </List.Item>
      )}
    />
  </Card>

  <Card bordered size="small" className="aba-soft-card" title={<Space><RobotOutlined /> Spawn agent</Space>}>
    <Form
      form={spawnForm}
      layout="vertical"
      style={{ maxWidth: 520 }}
      onFinish={async (v) => {
        setSkillBusy(true)
        try {
          const tid = v.template_id
          const tpl = tid === '__custom__' ? null : templates.find((t) => t.id === tid || String(t.id) === String(tid))
          const body = {
            name: (v.name || tpl?.name || 'New agent').trim(),
            template_type: tpl?.type || v.template_type || 'custom',
            hierarchy_role: v.hierarchy_role || 'member',
            personality: v.personality || 'Professional, helpful, concise.',
            parent_id: Number(id),
          }
          const r = await api(`/agents/${id}/spawn`, { method: 'POST', body })
          if (r?.ok === false || r?.error) {
            throw new Error(r.error || r.message || 'Spawn failed')
          }
          message.success(r.message || `Spawned ${body.name}`)
          spawnForm.resetFields()
          spawnForm.setFieldsValue({ hierarchy_role: 'member', template_type: 'custom', template_id: '__custom__' })
          load()
          api('/agents/').then(setAllAgents).catch(() => {})
          const childId = r?.agent?.id
          if (childId) {
            message.success(`${body.name} ready — open from Console or Hierarchy`)
          }
        } catch (e) {
          const msg = e?.message || 'Spawn failed'
          message.error(msg)
          if (e?.status === 402 || /subscription|plan|billing/i.test(msg)) {
            message.info('Open Billing to activate a plan, then try again')
          }
        } finally { setSkillBusy(false) }
      }}
      initialValues={{ hierarchy_role: 'member', template_type: 'custom', template_id: '__custom__' }}
    >
      <Form.Item name="name" label="Name" rules={[{ required: true, message: 'Name the new agent' }]}>
        <Input placeholder="e.g. Sales specialist" />
      </Form.Item>
      <Form.Item
        name="template_id"
        label="Template"
        rules={[{ required: true, message: 'Choose a template' }]}
        extra={templates.length ? `${templates.length} templates` : 'Using built-in roles'}
      >
        <Select
          showSearch
          optionFilterProp="label"
          placeholder="Pick a template"
          options={[
            { value: '__custom__', label: 'Custom (generic agent)' },
            ...templates.map((t) => ({
              value: t.id,
              label: `${t.type === 'orchestrator' ? '👑 ' : ''}${t.name || 'Unnamed'} (${t.type || 'custom'})`,
            })),
          ]}
          onChange={(tid) => {
            const t = templates.find((x) => x.id === tid || String(x.id) === String(tid))
            if (t) {
              spawnForm.setFieldsValue({
                template_type: t.type,
                name: spawnForm.getFieldValue('name') || t.name,
              })
            } else {
              spawnForm.setFieldsValue({ template_type: 'custom' })
            }
          }}
        />
      </Form.Item>
      <Form.Item name="template_type" hidden><Input /></Form.Item>
      <Form.Item name="hierarchy_role" label="Role">
        <Select options={[
          { value: 'member', label: 'Member' },
          { value: 'specialist', label: 'Specialist' },
          { value: 'lead', label: 'Lead' },
        ]} />
      </Form.Item>
      <Button type="primary" htmlType="submit" loading={skillBusy} block icon={<RobotOutlined />} className="aba-spawn-agent-btn">
        Spawn under this agent
      </Button>
    </Form>
  </Card>

  <Card bordered size="small" className="aba-soft-card" title={<Space><AppstoreOutlined /> Use connected app</Space>}>
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
      {!agentApps?.length && (
        <Typography.Text type="secondary">
          Link apps in Settings → Connected apps, then allocate to this agent.
        </Typography.Text>
      )}
    </Space>
  </Card>

  <Card bordered size="small" className="aba-soft-card" title={<Space><TeamOutlined /> Assign human</Space>}>
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
  </Card>
</Space>
  )
}
