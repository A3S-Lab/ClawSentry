import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { api } from '../api/client'
import { RiskBadge, DecisionBadge } from '../components/badges'
import type { SessionRisk, TrajectoryRecord } from '../api/types'
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'

const DIMENSION_LABELS: Record<string, string> = {
  d1: 'D1: Tool Risk',
  d2: 'D2: Target Sensitivity',
  d3: 'D3: Data Flow',
  d4: 'D4: Frequency',
  d5: 'D5: Context',
}

export default function SessionDetail() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const [risk, setRisk] = useState<SessionRisk | null>(null)
  const [trajectory, setTrajectory] = useState<TrajectoryRecord[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!sessionId) return
    setLoading(true)
    Promise.all([
      api.sessionRisk(sessionId),
      api.sessionReplay(sessionId),
    ]).then(([r, t]) => {
      setRisk(r)
      setTrajectory(t)
    }).catch(() => {}).finally(() => setLoading(false))
  }, [sessionId])

  if (loading) {
    return <p className="text-muted">Loading session data...</p>
  }

  const radarData = risk ? Object.entries(risk.dimensions_latest).map(([key, value]) => ({
    dimension: DIMENSION_LABELS[key] || key,
    value: value,
    fullMark: 1,
  })) : []

  const riskCurveData = risk?.risk_timeline.map(item => ({
    time: new Date(item.occurred_at).toLocaleTimeString(),
    score: item.composite_score,
    risk_level: item.risk_level,
  })) || []

  return (
    <div>
      <Link to="/sessions" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--color-text-secondary)', textDecoration: 'none', fontSize: '0.8rem', marginBottom: 16 }}>
        <ArrowLeft size={14} /> Back to Sessions
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <h2 className="mono" style={{ fontSize: '1rem' }}>{sessionId}</h2>
        {risk && <RiskBadge level={risk.current_risk_level} />}
      </div>

      {/* Top row: Radar + Metadata */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
        <div className="card">
          <div className="card-header">D1-D5 Dimension Scores</div>
          <div style={{ height: 300 }}>
            {radarData.length > 0 ? (
              <ResponsiveContainer>
                <RadarChart data={radarData}>
                  <PolarGrid stroke="#21262d" />
                  <PolarAngleAxis dataKey="dimension" tick={{ fill: '#7d8590', fontSize: 10 }} />
                  <PolarRadiusAxis tick={{ fill: '#484f58', fontSize: 9 }} domain={[0, 1]} />
                  <Radar dataKey="value" stroke="#58a6ff" fill="#58a6ff" fillOpacity={0.2} />
                </RadarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-muted" style={{ padding: 16 }}>No data</p>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-header">Session Metadata</div>
          <div style={{ display: 'grid', gap: 12, padding: '8px 0' }}>
            {risk && (
              <>
                <div>
                  <div className="text-muted" style={{ fontSize: '0.7rem', marginBottom: 2 }}>Cumulative Score</div>
                  <div className="mono" style={{ fontSize: '1.2rem' }}>{risk.cumulative_score.toFixed(2)}</div>
                </div>
                <div>
                  <div className="text-muted" style={{ fontSize: '0.7rem', marginBottom: 2 }}>Tools Used</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {risk.tools_used.map(t => (
                      <span key={t} className="mono" style={{ fontSize: '0.75rem', background: 'var(--color-surface-raised)', padding: '2px 6px', borderRadius: 4, border: '1px solid var(--color-border)' }}>
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="text-muted" style={{ fontSize: '0.7rem', marginBottom: 2 }}>Risk Hints</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {risk.risk_hints_seen.length > 0
                      ? risk.risk_hints_seen.map(h => (
                          <span key={h} className="mono" style={{ fontSize: '0.75rem', color: 'var(--color-risk-high)' }}>{h}</span>
                        ))
                      : <span className="text-muted" style={{ fontSize: '0.75rem' }}>None</span>
                    }
                  </div>
                </div>
                <div>
                  <div className="text-muted" style={{ fontSize: '0.7rem', marginBottom: 2 }}>Tier Distribution</div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    {Object.entries(risk.actual_tier_distribution).map(([tier, count]) => (
                      <span key={tier} className="mono" style={{ fontSize: '0.75rem' }}>{tier}: {count}</span>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Risk curve */}
      <div className="card" style={{ marginBottom: 20 }}>
        <div className="card-header">Risk Score Over Time</div>
        <div style={{ height: 250 }}>
          {riskCurveData.length > 0 ? (
            <ResponsiveContainer>
              <LineChart data={riskCurveData} margin={{ top: 10, right: 10, bottom: 0, left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#21262d" />
                <XAxis dataKey="time" tick={{ fill: '#7d8590', fontSize: 10 }} />
                <YAxis tick={{ fill: '#7d8590', fontSize: 10 }} domain={[0, 1]} />
                <Tooltip contentStyle={{ background: '#161b22', border: '1px solid #21262d', borderRadius: 6, fontSize: 12 }} />
                <Line type="monotone" dataKey="score" stroke="#58a6ff" strokeWidth={2} dot={{ fill: '#58a6ff', r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-muted" style={{ padding: 16 }}>No timeline data</p>
          )}
        </div>
      </div>

      {/* Decision timeline */}
      <div className="card">
        <div className="card-header">Decision Timeline</div>
        <div style={{ maxHeight: 400, overflowY: 'auto' }}>
          {trajectory.map((rec, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '8px 12px',
              borderBottom: '1px solid rgba(33,38,45,0.5)',
              fontSize: '0.8rem',
            }}>
              <span className="mono text-muted" style={{ fontSize: '0.7rem', minWidth: 65 }}>
                {new Date(rec.recorded_at).toLocaleTimeString()}
              </span>
              <DecisionBadge decision={rec.decision.decision} />
              <RiskBadge level={rec.risk_snapshot.risk_level} />
              <span className="mono" style={{ minWidth: 100 }}>
                {rec.event?.tool_name as string || '\u2014'}
              </span>
              <span className="text-secondary" style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.75rem' }}>
                {rec.decision.reason}
              </span>
              <span className="text-muted mono" style={{ fontSize: '0.7rem' }}>
                {rec.decision.decision_latency_ms}ms
              </span>
            </div>
          ))}
          {trajectory.length === 0 && (
            <p className="text-muted" style={{ padding: 16, textAlign: 'center' }}>No trajectory records</p>
          )}
        </div>
      </div>
    </div>
  )
}
