import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { api } from '../api/client'
import { RiskBadge, DecisionBadge } from '../components/badges'
import SkeletonCard from '../components/SkeletonCard'
import type { SessionRisk, TrajectoryRecord } from '../api/types'
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'

const DIMENSION_LABELS: Record<string, string> = {
  d1: 'Tool Risk',
  d2: 'Target Sensitivity',
  d3: 'Data Flow',
  d4: 'Frequency',
  d5: 'Context',
}

const TOOLTIP_STYLE = {
  background: '#1a1a24',
  border: '1px solid rgba(255,255,255,0.07)',
  borderRadius: 8,
  fontSize: 12,
  color: '#f1f0f5',
  boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
}

function classifyHint(hint: string): string {
  const h = hint.toLowerCase()
  if (h.includes('shell') || h.includes('exec') || h.includes('command')) return 'shell'
  if (h.includes('file') || h.includes('write') || h.includes('delete') || h.includes('path')) return 'file'
  if (h.includes('network') || h.includes('http') || h.includes('request') || h.includes('url')) return 'network'
  if (h.includes('data') || h.includes('read') || h.includes('secret') || h.includes('credential')) return 'data'
  return 'default'
}

function HintTag({ hint }: { hint: string }) {
  const cls = `hint-tag hint-tag-${classifyHint(hint)}`
  return <span className={cls}>{hint}</span>
}

function LatencyBadge({ ms }: { ms: number }) {
  const cls = ms < 100 ? 'latency-fast' : ms < 3000 ? 'latency-medium' : 'latency-slow'
  return <span className={`latency-badge ${cls}`}>{ms}ms</span>
}

function TierBadge({ tier }: { tier: string }) {
  const t = tier.toUpperCase()
  const cls = t === 'L3' ? 'badge-tier-l3' : t === 'L2' ? 'badge-tier-l2' : 'badge-tier-l1'
  return <span className={`badge ${cls}`}>{t}</span>
}

export default function SessionDetail() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const [risk, setRisk] = useState<SessionRisk | null>(null)
  const [trajectory, setTrajectory] = useState<TrajectoryRecord[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!sessionId) return
    setLoading(true)
    Promise.all([api.sessionRisk(sessionId), api.sessionReplay(sessionId)])
      .then(([r, t]) => { setRisk(r); setTrajectory(t) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [sessionId])

  if (loading) {
    return (
      <div>
        <div style={{ height: 24, marginBottom: 20 }} />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
          <SkeletonCard rows={4} height={320} />
          <SkeletonCard rows={5} height={320} />
        </div>
        <SkeletonCard rows={3} height={270} />
      </div>
    )
  }

  const radarData = risk
    ? Object.entries(risk.dimensions_latest).map(([key, value]) => ({
        dimension: DIMENSION_LABELS[key] || key,
        value,
        fullMark: 1,
      }))
    : []

  const riskCurveData = risk?.risk_timeline.map(item => ({
    time: new Date(item.occurred_at).toLocaleTimeString(),
    score: parseFloat(item.composite_score.toFixed(3)),
    risk_level: item.risk_level,
  })) ?? []

  return (
    <div>
      <Link
        to="/sessions"
        style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--color-text-muted)', textDecoration: 'none', fontSize: '0.78rem', marginBottom: 16 }}
      >
        <ArrowLeft size={13} /> Back to Sessions
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
        <h2 className="mono" style={{ fontSize: '0.95rem', fontWeight: 600 }}>{sessionId}</h2>
        {risk && <RiskBadge level={risk.current_risk_level} />}
      </div>

      {/* Top row: Radar + Metadata */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        <div className="card">
          <div className="card-header">D1–D5 Dimension Scores</div>
          <div style={{ height: 280 }}>
            {radarData.length > 0 ? (
              <ResponsiveContainer>
                <RadarChart data={radarData}>
                  <PolarGrid stroke="rgba(255,255,255,0.06)" />
                  <PolarAngleAxis dataKey="dimension" tick={{ fill: '#8b8a9b', fontSize: 10 }} />
                  <PolarRadiusAxis tick={{ fill: '#52515e', fontSize: 9 }} domain={[0, 1]} />
                  <Radar dataKey="value" stroke="#a78bfa" fill="#a78bfa" fillOpacity={0.18} strokeWidth={2} />
                </RadarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-muted" style={{ padding: 16 }}>No dimension data</p>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-header">Session Metadata</div>
          {risk && (
            <div style={{ display: 'grid', gap: 14, padding: '6px 0' }}>
              <div>
                <div className="text-muted" style={{ fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>Cumulative Score</div>
                <div className="mono" style={{ fontSize: '1.4rem', fontWeight: 700 }}>{risk.cumulative_score.toFixed(3)}</div>
              </div>
              <div>
                <div className="text-muted" style={{ fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>Tools Used</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                  {risk.tools_used.map(t => (
                    <span key={t} className="mono cmd-snippet">{t}</span>
                  ))}
                  {risk.tools_used.length === 0 && <span className="text-muted" style={{ fontSize: '0.75rem' }}>None</span>}
                </div>
              </div>
              <div>
                <div className="text-muted" style={{ fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>Risk Hints</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                  {risk.risk_hints_seen.length > 0
                    ? risk.risk_hints_seen.map(h => <HintTag key={h} hint={h} />)
                    : <span className="text-muted" style={{ fontSize: '0.75rem' }}>No risk hints</span>}
                </div>
              </div>
              <div>
                <div className="text-muted" style={{ fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>Tier Distribution</div>
                <div style={{ display: 'flex', gap: 8 }}>
                  {Object.entries(risk.actual_tier_distribution).map(([tier, count]) => (
                    <span key={tier}>
                      <TierBadge tier={tier} /> <span className="mono" style={{ fontSize: '0.72rem' }}>{count}</span>
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Risk curve - AreaChart with gradient */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-header">Risk Score Over Time</div>
        <div style={{ height: 230 }}>
          {riskCurveData.length > 0 ? (
            <ResponsiveContainer>
              <AreaChart data={riskCurveData} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
                <defs>
                  <linearGradient id="riskGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#a78bfa" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#a78bfa" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="time" tick={{ fill: '#8b8a9b', fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#8b8a9b', fontSize: 10 }} axisLine={false} tickLine={false} domain={[0, 1]} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Area
                  type="monotone"
                  dataKey="score"
                  stroke="#a78bfa"
                  strokeWidth={2}
                  fill="url(#riskGradient)"
                  dot={{ fill: '#a78bfa', r: 3, strokeWidth: 0 }}
                  activeDot={{ r: 5, fill: '#a78bfa' }}
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-muted" style={{ padding: 16 }}>No timeline data</p>
          )}
        </div>
      </div>

      {/* Decision timeline */}
      <div className="card">
        <div className="card-header">Decision Timeline ({trajectory.length} events)</div>
        <div style={{ maxHeight: 420, overflowY: 'auto' }}>
          {trajectory.map((rec, i) => (
            <div key={i} style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 10,
              padding: '10px 14px',
              borderBottom: '1px solid var(--color-border)',
              fontSize: '0.8rem',
            }}>
              <span className="mono text-muted" style={{ fontSize: '0.68rem', minWidth: 62, paddingTop: 2 }}>
                {new Date(rec.recorded_at).toLocaleTimeString()}
              </span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 5, flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <DecisionBadge decision={rec.decision.decision} />
                  <RiskBadge level={rec.risk_snapshot.risk_level} />
                  <TierBadge tier={rec.meta.actual_tier} />
                  <span className="mono" style={{ fontSize: '0.78rem', fontWeight: 500 }}>
                    {rec.event?.tool_name as string || '—'}
                  </span>
                  <LatencyBadge ms={rec.decision.decision_latency_ms} />
                </div>
                {(rec.event?.input as string) && (
                  <span className="cmd-snippet" style={{ maxWidth: '100%' }}>
                    {(rec.event.input as string).slice(0, 120)}
                  </span>
                )}
                {rec.decision.reason && (
                  <span className="text-secondary" style={{ fontSize: '0.73rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {rec.decision.reason}
                  </span>
                )}
              </div>
            </div>
          ))}
          {trajectory.length === 0 && (
            <p className="text-muted" style={{ padding: 20, textAlign: 'center', fontSize: '0.82rem' }}>No trajectory records</p>
          )}
        </div>
      </div>
    </div>
  )
}
