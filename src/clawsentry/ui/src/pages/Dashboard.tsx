import { useState, useEffect } from 'react'
import { api } from '../api/client'
import type { SummaryResponse } from '../api/types'
import MetricCard from '../components/MetricCard'
import DecisionFeed from '../components/DecisionFeed'
import {
  PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from 'recharts'

const RISK_COLORS: Record<string, string> = {
  low: '#3fb950', medium: '#d29922', high: '#db6d28', critical: '#f85149',
}
const DECISION_COLORS: Record<string, string> = {
  allow: '#3fb950', block: '#f85149', defer: '#d29922', modify: '#58a6ff',
}

export default function Dashboard() {
  const [summary, setSummary] = useState<SummaryResponse | null>(null)

  useEffect(() => {
    const load = () => api.summary().then(setSummary).catch(() => {})
    load()
    const timer = setInterval(load, 10_000)
    return () => clearInterval(timer)
  }, [])

  const blockRate = summary
    ? ((summary.by_decision['block'] || 0) / Math.max(summary.total_records, 1) * 100).toFixed(1)
    : '\u2014'

  const riskData = summary
    ? Object.entries(summary.by_risk_level).map(([name, value]) => ({ name, value }))
    : []

  const decisionData = summary
    ? Object.entries(summary.by_decision).map(([name, value]) => ({ name, value }))
    : []

  const sourceData = summary
    ? Object.entries(summary.by_source_framework).map(([name, value]) => ({ name, value }))
    : []

  return (
    <div>
      {/* Metric cards */}
      <div className="metric-grid" style={{ marginBottom: 20 }}>
        <MetricCard label="Total Decisions" value={summary?.total_records ?? '\u2014'} />
        <MetricCard label="Block Rate" value={`${blockRate}%`} color="var(--color-block)" />
        <MetricCard label="Risk Levels" value={Object.keys(summary?.by_risk_level ?? {}).length} />
        <MetricCard label="Sources" value={Object.keys(summary?.by_source_framework ?? {}).length} />
      </div>

      {/* Middle row: Feed + Pie */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 16, marginBottom: 20 }}>
        <DecisionFeed />
        <div className="card">
          <div className="card-header">Risk Distribution</div>
          <div style={{ height: 350 }}>
            {riskData.length > 0 ? (
              <ResponsiveContainer>
                <PieChart>
                  <Pie data={riskData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100} innerRadius={50} paddingAngle={2} label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`} labelLine={false} fontSize={11}>
                    {riskData.map(entry => (
                      <Cell key={entry.name} fill={RISK_COLORS[entry.name] || '#484f58'} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ background: '#161b22', border: '1px solid #21262d', borderRadius: 6, fontSize: 12 }} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-muted" style={{ padding: 16, fontSize: '0.8rem' }}>No data yet</p>
            )}
          </div>
        </div>
      </div>

      {/* Bottom row: Bar charts */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div className="card">
          <div className="card-header">Decisions by Verdict</div>
          <div style={{ height: 250 }}>
            {decisionData.length > 0 ? (
              <ResponsiveContainer>
                <BarChart data={decisionData} margin={{ top: 10, right: 10, bottom: 0, left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#21262d" />
                  <XAxis dataKey="name" tick={{ fill: '#7d8590', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#7d8590', fontSize: 11 }} />
                  <Tooltip contentStyle={{ background: '#161b22', border: '1px solid #21262d', borderRadius: 6, fontSize: 12 }} />
                  <Bar dataKey="value" radius={[3, 3, 0, 0]}>
                    {decisionData.map(entry => (
                      <Cell key={entry.name} fill={DECISION_COLORS[entry.name] || '#484f58'} />
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
          <div className="card-header">Decisions by Source</div>
          <div style={{ height: 250 }}>
            {sourceData.length > 0 ? (
              <ResponsiveContainer>
                <BarChart data={sourceData} margin={{ top: 10, right: 10, bottom: 0, left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#21262d" />
                  <XAxis dataKey="name" tick={{ fill: '#7d8590', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#7d8590', fontSize: 11 }} />
                  <Tooltip contentStyle={{ background: '#161b22', border: '1px solid #21262d', borderRadius: 6, fontSize: 12 }} />
                  <Bar dataKey="value" fill="var(--color-accent)" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-muted" style={{ padding: 16, fontSize: '0.8rem' }}>No data yet</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
