import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import { RiskBadge } from '../components/badges'
import type { SessionSummary } from '../api/types'

export default function Sessions() {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [minRisk, setMinRisk] = useState<string>('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.sessions({
        sort: 'risk_desc',
        limit: 50,
        min_risk: minRisk || undefined,
      })
      setSessions(data)
    } catch { /* ignore */ }
    setLoading(false)
  }, [minRisk])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    const timer = setInterval(load, 15_000)
    return () => clearInterval(timer)
  }, [load])

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 className="section-header" style={{ marginBottom: 0, borderBottom: 'none', paddingBottom: 0 }}>
          Active Sessions
        </h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <select
            value={minRisk}
            onChange={e => setMinRisk(e.target.value)}
            style={{
              background: 'var(--color-surface-raised)',
              color: 'var(--color-text)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius)',
              padding: '6px 10px',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.75rem',
            }}
          >
            <option value="">All Risk Levels</option>
            <option value="low">Low+</option>
            <option value="medium">Medium+</option>
            <option value="high">High+</option>
            <option value="critical">Critical</option>
          </select>
          <button className="btn" onClick={load} disabled={loading}>
            <RefreshCw size={14} style={loading ? { animation: 'spin 1s linear infinite' } : undefined} />
          </button>
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <table>
          <thead>
            <tr>
              <th>Session ID</th>
              <th>Agent</th>
              <th>Risk</th>
              <th>Events</th>
              <th>Source</th>
              <th>Last Activity</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map(s => (
              <tr key={s.session_id}>
                <td>
                  <Link to={`/sessions/${s.session_id}`} style={{ color: 'var(--color-accent)', textDecoration: 'none', fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>
                    {s.session_id.length > 16 ? s.session_id.slice(0, 16) + '...' : s.session_id}
                  </Link>
                </td>
                <td className="mono" style={{ fontSize: '0.8rem' }}>{s.agent_id}</td>
                <td><RiskBadge level={s.current_risk_level} /></td>
                <td className="mono">{s.event_count}</td>
                <td className="text-secondary" style={{ fontSize: '0.8rem' }}>{s.source_framework}</td>
                <td className="text-muted mono" style={{ fontSize: '0.75rem' }}>
                  {new Date(s.last_event_at).toLocaleString()}
                </td>
              </tr>
            ))}
            {sessions.length === 0 && !loading && (
              <tr><td colSpan={6} className="text-muted" style={{ textAlign: 'center', padding: 24 }}>No sessions found</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
