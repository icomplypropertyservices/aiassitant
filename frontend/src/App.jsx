import React from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { getToken, getUser } from './api'
import { usePushRegistration } from './hooks/useNativeFeedback'
import AppLayout from './components/AppLayout'
import Login from './pages/Login'
import ResetPassword from './pages/ResetPassword'
import VerifyEmail from './pages/VerifyEmail'
import Subscribe from './pages/Subscribe'
import Dashboard from './pages/Dashboard'
import Workspace from './pages/Workspace'
import Chat from './pages/Chat'
import Agents from './pages/Agents'
import AgentDetail from './pages/AgentDetail'
import AgentChat from './pages/AgentChat'
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
import Profile from './pages/Profile'
import Permissions from './pages/Permissions'
import CompanyProfile from './pages/CompanyProfile'

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
  usePushRegistration()
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/verify-email" element={<VerifyEmail />} />
      <Route path="/subscribe" element={<SubscribeGate><Subscribe /></SubscribeGate>} />
      <Route path="/" element={<Protected><AppLayout /></Protected>}>
        <Route index element={<Dashboard />} />
        <Route path="workspace" element={<Workspace />} />
        <Route path="tasks" element={<TasksBoard />} />
        <Route path="chat" element={<Chat />} />
        {/* Agent Console — /agents/console (legacy /agents/agents and /agents/army still work) */}
        <Route path="console" element={<Agents />} />
        <Route path="console/:id" element={<AgentChat />} />
        <Route path="console/:id/chat" element={<AgentChat />} />
        <Route path="console/:id/manage" element={<AgentDetail />} />
        <Route path="army" element={<Agents />} />
        <Route path="army/:id" element={<AgentChat />} />
        <Route path="army/:id/chat" element={<AgentChat />} />
        <Route path="army/:id/manage" element={<AgentDetail />} />
        <Route path="agents" element={<Agents />} />
        <Route path="agents/:id" element={<AgentChat />} />
        <Route path="agents/:id/chat" element={<AgentChat />} />
        <Route path="agents/:id/manage" element={<AgentDetail />} />
        <Route path="hierarchy" element={<Hierarchy />} />
        <Route path="templates" element={<Templates />} />
        <Route path="training" element={<Training />} />
        <Route path="humans" element={<Humans />} />
        <Route path="users" element={<Humans />} />
        <Route path="profile" element={<Profile />} />
        <Route path="permissions" element={<Permissions />} />
        <Route path="companies/:id" element={<CompanyProfile />} />
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
