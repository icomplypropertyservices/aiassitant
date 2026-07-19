import React, { Suspense, lazy } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { getToken, getUser } from './api'
import { usePushRegistration } from './hooks/useNativeFeedback'
import AppLayout from './components/AppLayout'
import { LogoLoading } from './components/BrandLogo'

// Eager: first paint auth shell (small)
import Login from './pages/Login'

// Lazy: heavy pages — split antd-heavy routes so initial JS is smaller/faster
const ResetPassword = lazy(() => import('./pages/ResetPassword'))
const VerifyEmail = lazy(() => import('./pages/VerifyEmail'))
const Subscribe = lazy(() => import('./pages/Subscribe'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Workspace = lazy(() => import('./pages/Workspace'))
const Chat = lazy(() => import('./pages/Chat'))
const Agents = lazy(() => import('./pages/Agents'))
const AgentDetail = lazy(() => import('./pages/AgentDetail'))
const AgentChat = lazy(() => import('./pages/AgentChat'))
const TasksBoard = lazy(() => import('./pages/TasksBoard'))
const Meetings = lazy(() => import('./pages/Meetings'))
const MeetingRoom = lazy(() => import('./pages/MeetingRoom'))
const Hierarchy = lazy(() => import('./pages/Hierarchy'))
const Templates = lazy(() => import('./pages/Templates'))
const Analytics = lazy(() => import('./pages/Analytics'))
const Billing = lazy(() => import('./pages/Billing'))
const Settings = lazy(() => import('./pages/Settings'))
const Training = lazy(() => import('./pages/Training'))
const CommsPractice = lazy(() => import('./pages/CommsPractice'))
const Humans = lazy(() => import('./pages/Humans'))
const Ops = lazy(() => import('./pages/Ops'))
const Business = lazy(() => import('./pages/Business'))
const CustomerDetail = lazy(() => import('./pages/CustomerDetail'))
const Admin = lazy(() => import('./pages/Admin'))
const Profile = lazy(() => import('./pages/Profile'))
const Permissions = lazy(() => import('./pages/Permissions'))
const CompanyProfile = lazy(() => import('./pages/CompanyProfile'))

function PageFallback() {
  return <LogoLoading tip="Loading…" minHeight={280} />
}

function Lazy({ children }) {
  return <Suspense fallback={<PageFallback />}>{children}</Suspense>
}

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
      <Route path="/reset-password" element={<Lazy><ResetPassword /></Lazy>} />
      <Route path="/verify-email" element={<Lazy><VerifyEmail /></Lazy>} />
      <Route path="/subscribe" element={<Lazy><SubscribeGate><Subscribe /></SubscribeGate></Lazy>} />
      <Route path="/" element={<Protected><AppLayout /></Protected>}>
        <Route index element={<Lazy><Dashboard /></Lazy>} />
        <Route path="workspace" element={<Lazy><Workspace /></Lazy>} />
        <Route path="tasks" element={<Lazy><TasksBoard /></Lazy>} />
        <Route path="meetings" element={<Lazy><Meetings /></Lazy>} />
        <Route path="meetings/:id" element={<Lazy><MeetingRoom /></Lazy>} />
        <Route path="chat" element={<Lazy><Chat /></Lazy>} />
        {/* Agent Console — /agents/console (legacy /agents/agents and /agents/army still work) */}
        <Route path="console" element={<Lazy><Agents /></Lazy>} />
        <Route path="console/:id" element={<Lazy><AgentChat /></Lazy>} />
        <Route path="console/:id/chat" element={<Lazy><AgentChat /></Lazy>} />
        <Route path="console/:id/manage" element={<Lazy><AgentDetail /></Lazy>} />
        <Route path="army" element={<Lazy><Agents /></Lazy>} />
        <Route path="army/:id" element={<Lazy><AgentChat /></Lazy>} />
        <Route path="army/:id/chat" element={<Lazy><AgentChat /></Lazy>} />
        <Route path="army/:id/manage" element={<Lazy><AgentDetail /></Lazy>} />
        <Route path="agents" element={<Lazy><Agents /></Lazy>} />
        <Route path="agents/:id" element={<Lazy><AgentChat /></Lazy>} />
        <Route path="agents/:id/chat" element={<Lazy><AgentChat /></Lazy>} />
        <Route path="agents/:id/manage" element={<Lazy><AgentDetail /></Lazy>} />
        <Route path="hierarchy" element={<Lazy><Hierarchy /></Lazy>} />
        <Route path="templates" element={<Lazy><Templates /></Lazy>} />
        <Route path="training" element={<Lazy><Training /></Lazy>} />
        <Route path="comms" element={<Lazy><CommsPractice /></Lazy>} />
        <Route path="calls" element={<Lazy><CommsPractice /></Lazy>} />
        <Route path="humans" element={<Lazy><Humans /></Lazy>} />
        <Route path="users" element={<Lazy><Humans /></Lazy>} />
        <Route path="profile" element={<Lazy><Profile /></Lazy>} />
        <Route path="permissions" element={<Lazy><Permissions /></Lazy>} />
        <Route path="companies/:id" element={<Lazy><CompanyProfile /></Lazy>} />
        <Route path="ops" element={<Lazy><Ops /></Lazy>} />
        <Route path="business" element={<Lazy><Business /></Lazy>} />
        <Route path="business/customers/:id" element={<Lazy><CustomerDetail /></Lazy>} />
        <Route path="analytics" element={<Lazy><Analytics /></Lazy>} />
        <Route path="billing" element={<Lazy><Billing /></Lazy>} />
        <Route path="settings" element={<Lazy><Settings /></Lazy>} />
        <Route path="admin" element={<Lazy><AdminOnly><Admin /></AdminOnly></Lazy>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
