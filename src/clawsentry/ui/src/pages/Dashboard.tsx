import { useState, useEffect } from 'react'
import { api } from '../api/client'
import type { SummaryResponse, HealthResponse } from '../api/types'
import MetricCard from '../components/MetricCard'
import DecisionFeed from '../components/DecisionFeed'
import SkeletonCard from '../components/SkeletonCard'
import {
  PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { Activity, ShieldX, Cpu, Clock } from 'lucide-react'

const RISK_COLORS: Record<string, string> = {
  low: '#22c55e', medium: '#f59e0b', high: '#f97316', critical: '#ef4444',
}
const DECISION_COLORS: Record<string, string> = {
  allow: '#22c55e', block: '#ef4444', defer: '#f59e0b', modify: '#60a5fa',
}
const TIER_COLORS: Record<string, string> = {
  L1: '#a78bfa', L2: '#60a5fa', L3: '#f97316',
}

const TOOLTIP_STYLE = {
  background: '#1a1a24',
  border: '1px solid rgba(255,255,255,0.07)',
  borderRadius: 8,
  fontSize: 12,
  color: '#f1f0f5',
  boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
}

function formatUptime(s: number): string {
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 86400) return `${Math.floor(s / 3600)}h`
  return `${Math.floor(s / 86400)}d`
}

export default function Dashboard() {
  const [summary, setSummary] = useState<SummaryResponse | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = () => Promise.all([
      api.summary().then(setSummary),
      api.health().then(setHealth),
    ]).catch(() => {}).finally(() => setLoading(false))
    load()
    const timer = setInterval(load, 10_000)
    return () => clearInterval(timer)
  }, [])

  const blockRate = summary
    ? ((summary.by_decision['block'] || 0) / Math.max(summary.total_records, 1) * 100).toFixed(1)
    : '—'

  const l3Count = summary?.by_actual_tier?.['L3'] ?? summary?.by_actual_tier?.['l3'] ?? 0
  const l3Rate = summary
    ? ((l3Count / Math.max(summary.total_records, 1)) * 100).toFixed(1)
    : '—'

  const riskData = summary
    ? Object.entries(summary.by_risk_level).map(([name, value]) => ({ name, value }))
    : []

  const decisionData = summary
    ? Object.entries(summary.by_decision).map(([name, value]) => ({ name, value }))
    : []

  const tierData = summary?.by_actual_tier
    ? Object.entries(summary.by_actual_tier)
        .map(([name, value]) => ({ name: name.toUpperCase(), value }))
        .sort((a, b) => a.name.localeCompare(b.name))
    : []

  if (loading) {
    return (
      <div>
        <div className="metric-grid" style={{ marginBottom: 20 }}>
          {[0,1,2,3].map(i => <SkeletonCard key={i} rows={2} height={90} />)}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 16 }}>
          <SkeletonCard rows={6} height={460} />
          <SkeletonCard rows={4} height={460} />
        </div>
      </div>
    )
  }

  return (
    <div>
      {/* Metric cards */}
      <div className="metric-grid" style={{ marginBottom: 20 }}>
        <MetricCard
          label="Total Decisions"
          value={summary?.total_records.toLocaleString() ?? '—'}
          accent="purple"
          icon={<Activity size={20} />}
          subtext={`${summary?.by_event_type?.['pre_action'] ?? 0} pre-action`}
        />
        <MetricCard
          label="Block Rate"
          value={`${blockRate}%`}
          accent="red"
          icon={<ShieldX size={20} />}
          subtext={`${summary?.by_decision?.['block'] ?? 0} blocked`}
        />
        <MetricCard
          label="L3 Escalation Rate"
          value={`${l3Rate}%`}
          accent="amber"
          icon={<Cpu size={20} />}
          subtext={`${l3Count} agent reviews`}
        />
        <MetricCard
          label="Uptime"
          value={health ? formatUptime(health.uptime_seconds) : '—'}
          accent="blue"
          icon={<Clock size={20} />}
          subtext={health ? `${health.trajectory_count.toLocaleString()} total events` : undefined}
        />
      </div>

      {/* Middle row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 16, marginBottom: 16 }}>
        <DecisionFeed />
        <div className="card">
          <div className="card-header">Risk Distribution</div>
          <div style={{ height: 360 }}>
            {riskData.length > 0 ? (
              <ResponsiveContainer>
                <PieChart>
                  <Pie
                    data={riskData}
                    dataKey="value"
                    nameKey="name"
                    cx="50%" cy="50%"
                    outerRadius={110}
                    innerRadius={55}
                    paddingAngle={3}
                    label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                    labelLine={false}
                    fontSize={11}
                  >
                    {riskData.map(entry => (
                      <Cell key={entry.name} fill={RISK_COLORS[entry.name] || '#52515e'} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-muted" style={{ padding: 16, fontSize: '0.8rem' }}>No data yet</p>
            )}
          </div>
        </div>
      </div>

      {/* Bottom row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div className="card">
          <div className="card-header">Decision Verdicts</div>
          <div style={{ height: 220 }}>
            {decisionData.length > 0 ? (
              <ResponsiveContainer>
                <BarChart data={decisionData} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                  <XAxis dataKey="name" tick={{ fill: '#8b8a9b', fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: '#8b8a9b', fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
                  <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                    {decisionData.map(entry => (
                      <Cell key={entry.name} fill={DECISION_COLORS[entry.name] || '#52515e'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-muted" style={{ padding: 16, fontSize: '0.8rem' }}>No data yet</p>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-header">Policy Tier Distribution</div>
          <div style={{ height: 220 }}>
            {tierData.length > 0 ? (
              <ResponsiveContainer>
                <BarChart data={tierData} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                  <XAxis dataKey="name" tick={{ fill: '#8b8a9b', fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: '#8b8a9b', fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
                  <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                    {tierData.map(entry => (
                      <Cell key={entry.name} fill={TIER_COLORS[entry.name] || '#a78bfa'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-muted" style={{ padding: 16, fontSize: '0.8rem' }}>No tier data yet</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
