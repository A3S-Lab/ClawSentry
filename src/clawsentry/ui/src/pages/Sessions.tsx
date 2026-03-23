import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { RefreshCw, Users } from 'lucide-react'
import { api } from '../api/client'
import { RiskBadge } from '../components/badges'
import EmptyState from '../components/EmptyState'
import type { SessionSummary } from '../api/types'

const RISK_SCORE_COLORS = ['#22c55e', '#f59e0b', '#f97316', '#ef4444']

function getRiskColor(score: number): string {
  if (score < 0.25) return RISK_SCORE_COLORS[0]
  if (score < 0.5) return RISK_SCORE_COLORS[1]
  if (score < 0.75) return RISK_SCORE_COLORS[2]
  return RISK_SCORE_COLORS[3]
}

function VerdictBar({ dist }: { dist: Record<string, number> }) {
  const total = Object.values(dist).reduce((a, b) => a + b, 0)
  if (total === 0) return <span className="text-muted" style={{ fontSize: '0.7rem' }}>—</span>
  const colors: Record<string, string> = {
    allow: '#22c55e', block: '#ef4444', defer: '#f59e0b', modify: '#60a5fa',
  }
  return (
    <div className="verdict-bar">
      {Object.entries(dist).map(([key, count]) => (
        count > 0 ? (
          <div
            key={key}
            className="verdict-bar-segment"
            style={{ width: `${(count / total) * 100}%`, background: colors[key] || '#52515e' }}
            title={`${key}: ${count}`}
          />
        ) : null
      ))}
    </div>
  )
}

function ScoreBar({ score }: { score: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div className="score-bar">
        <div
          className="score-bar-fill"
          style={{ width: `${score * 100}%`, background: getRiskColor(score) }}
        />
      </div>
      <span className="mono" style={{ fontSize: '0.7rem', color: getRiskColor(score) }}>
        {score.toFixed(2)}
      </span>
    </div>
  )
}

export default function Sessions() {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [minRisk, setMinRisk] = useState<string>('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.sessions({ sort: 'risk_desc', limit: 50, min_risk: minRisk || undefined })
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
        <h2 className="section-header" style={{ marginBottom: 0 }}>
          <Users size={18} style={{ color: 'var(--color-accent)' }} />
          Active Sessions
          <span className="mono" style={{ fontSize: '0.72rem', color: 'var(--color-text-muted)', fontWeight: 400 }}>
            {sessions.length} sessions
          </span>
        </h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <select value={minRisk} onChange={e => setMinRisk(e.target.value)}>
            <option value="">All Risk Levels</option>
            <option value="low">Low+</option>
            <option value="medium">Medium+</option>
            <option value="high">High+</option>
            <option value="critical">Critical Only</option>
          </select>
          <button className="btn" onClick={load} disabled={loading}>
            <RefreshCw size={13} style={loading ? { animation: 'spin 1s linear infinite' } : undefined} />
          </button>
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <table>
          <thead>
            <tr>
              <th>Session ID</th>
              <th>Agent</th>
              <th>Risk Level</th>
              <th>Score</th>
              <th>Events</th>
              <th>High Risk</th>
              <th>Verdicts</th>
              <th>Last Active</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map(s => (
              <tr key={s.session_id}>
                <td>
                  <Link
                    to={`/sessions/${s.session_id}`}
                    style={{ color: 'var(--color-accent)', textDecoration: 'none', fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}
                  >
                    {s.session_id.length > 14 ? s.session_id.slice(0, 14) + '…' : s.session_id}
                  </Link>
                </td>
                <td className="mono" style={{ fontSize: '0.78rem' }}>{s.agent_id || '—'}</td>
                <td><RiskBadge level={s.current_risk_level} /></td>
                <td><ScoreBar score={s.cumulative_score} /></td>
                <td className="mono" style={{ fontSize: '0.78rem' }}>{s.event_count}</td>
                <td>
                  <span className="mono" style={{
                    fontSize: '0.78rem',
                    color: s.high_risk_event_count > 0 ? 'var(--color-risk-high)' : 'var(--color-text-muted)',
                    fontWeight: s.high_risk_event_count > 0 ? 600 : 400,
                  }}>
                    {s.high_risk_event_count}
                  </span>
                </td>
                <td><VerdictBar dist={s.decision_distribution} /></td>
                <td className="text-muted mono" style={{ fontSize: '0.7rem' }}>
                  {new Date(s.last_event_at).toLocaleTimeString()}
                </td>
              </tr>
            ))}
            {sessions.length === 0 && !loading && (
              <tr>
                <td colSpan={8} style={{ padding: 0, border: 'none' }}>
                  <EmptyState
                    icon={<Users size={20} />}
                    title="No sessions found"
                    subtitle="Sessions will appear here when agents start sending events"
                  />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
