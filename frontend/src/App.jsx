import React from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { getToken, getUser } from './api'
import AppLayout from './components/AppLayout'
import Login from './pages/Login'
import Subscribe from './pages/Subscribe'
import Dashboard from './pages/Dashboard'
import Workspace from './pages/Workspace'
import Chat from './pages/Chat'
import Agents from './pages/Agents'
import AgentDetail from './pages/AgentDetail'
import TasksBoard from './pages/TasksBoard'
import Hierarchy from './pages/Hierarchy'
import Templates from './pages/Templates'
import Analytics from './pages/Analytics'
import Billing from './pages/Billing'
import Settings from './pages/Settings'
import Training from './pages/Training'
import Humans from './pages/Humans'
import Ops from './pages/Ops'
import Business from './pages/Business'
import CustomerDetail from './pages/CustomerDetail'
import Admin from './pages/Admin'

function Protected({ children }) {
  return getToken() ? children : <Navigate to="/login" replace />
}

function AdminOnly({ children }) {
  if (!getToken()) return <Navigate to="/login" replace />
  if (getUser()?.role !== 'admin') return <Navigate to="/" replace />
  return children
}

function SubscribeGate({ children }) {
  const user = getUser()
  if (!getToken()) return <Navigate to="/login" replace />
  if (user && !user.needs_subscription && user.subscription_active) {
    return <Navigate to="/" replace />
  }
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/subscribe" element={<SubscribeGate><Subscribe /></SubscribeGate>} />
      <Route path="/" element={<Protected><AppLayout /></Protected>}>
        <Route index element={<Dashboard />} />
        <Route path="workspace" element={<Workspace />} />
        <Route path="tasks" element={<TasksBoard />} />
        <Route path="chat" element={<Chat />} />
        <Route path="agents" element={<Agents />} />
        <Route path="agents/:id" element={<AgentDetail />} />
        <Route path="hierarchy" element={<Hierarchy />} />
        <Route path="templates" element={<Templates />} />
        <Route path="training" element={<Training />} />
        <Route path="humans" element={<Humans />} />
        <Route path="ops" element={<Ops />} />
        <Route path="business" element={<Business />} />
        <Route path="business/customers/:id" element={<CustomerDetail />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="billing" element={<Billing />} />
        <Route path="settings" element={<Settings />} />
        <Route path="admin" element={<AdminOnly><Admin /></AdminOnly>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
