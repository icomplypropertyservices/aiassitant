import React from 'react'
import {
  Card, Button, Space, Tag, List, Form, Select, Switch, Typography,
} from 'antd'
import { TeamOutlined, RobotOutlined } from '@ant-design/icons'
import { modelLabel } from '../../models'
import { STATUS_COLOR } from './constants'

/** Agent manage page — Team tab body. */
export default function AgentTeamTab({
  agent, setDelegateOpen, delegateForm, nav, hierForm, saveHierarchy, allAgents, id,
}) {
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card
        bordered
        size="small"
        className="aba-soft-card"
        title="Direct reports"
        extra={(
          <Space wrap>
            <Button
              type="primary"
              size="small"
              icon={<TeamOutlined />}
              onClick={() => setDelegateOpen(true)}
              disabled={!(agent.reports?.length || agent.is_lead)}
            >
              Delegate task
            </Button>
            <Button size="small" onClick={() => nav('/hierarchy')}>Open hierarchy map</Button>
          </Space>
        )}
      >
        {agent.team_context && (
          <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
            {agent.team_context}
          </Typography.Paragraph>
        )}
        <List
          dataSource={agent.reports || []}
          locale={{ emptyText: 'No reports yet — set hierarchy below or on Hierarchy page' }}
          renderItem={(r) => (
            <List.Item
              style={{ cursor: 'pointer' }}
              onClick={() => nav(`/agents/${r.id}`)}
              actions={[
                <Button
                  key="d"
                  type="link"
                  onClick={(e) => {
                    e.stopPropagation()
                    setDelegateOpen(true)
                    delegateForm.setFieldsValue({ to_agent_id: r.id })
                  }}
                >
                  Delegate
                </Button>,
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
      </Card>
      {(agent.team_tasks || []).length > 0 && (
        <Card bordered size="small" className="aba-soft-card" title="Team tasks">
          <List
            size="small"
            dataSource={agent.team_tasks}
            renderItem={(t) => (
              <List.Item>
                <Space wrap>
                  <Tag color={STATUS_COLOR[t.status]}>{t.status}</Tag>
                  <span>{t.title}</span>
                  {t.agent_name && <Tag color="geekblue">{t.agent_name}</Tag>}
                </Space>
              </List.Item>
            )}
          />
        </Card>
      )}
      <Card bordered size="small" className="aba-soft-card" title="Set hierarchy">
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
              options={allAgents.filter((a) => a.id !== Number(id)).map((a) => ({
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
              options={allAgents.filter((a) => a.id !== Number(id)).map((a) => ({
                value: a.id,
                label: a.name,
              }))}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit">Save hierarchy</Button>
        </Form>
      </Card>
    </Space>
  )
}
