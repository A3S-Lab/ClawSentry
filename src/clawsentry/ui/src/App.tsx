import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './hooks/useAuth'
import Layout from './components/Layout'
import LoginForm from './components/LoginForm'
import Dashboard from './pages/Dashboard'
import Sessions from './pages/Sessions'
import SessionDetail from './pages/SessionDetail'
import Alerts from './pages/Alerts'
import DeferPanel from './pages/DeferPanel'

export default function App() {
  const { authenticated, checking, check, login } = useAuth()

  useEffect(() => { check() }, [check])

  if (checking && authenticated === null) {
    return (
      <div className="login-container">
        <div style={{ textAlign: 'center' }}>
          <span className="status-dot checking" style={{ width: 12, height: 12 }} />
          <p className="text-muted mono" style={{ marginTop: 12, fontSize: '0.8rem' }}>Connecting...</p>
        </div>
      </div>
    )
  }

  if (authenticated === false) {
    return <LoginForm onLogin={login} />
  }

  return (
    <BrowserRouter basename="/ui">
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="sessions" element={<Sessions />} />
          <Route path="sessions/:sessionId" element={<SessionDetail />} />
          <Route path="alerts" element={<Alerts />} />
          <Route path="defer" element={<DeferPanel />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
