import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle, XCircle, RefreshCw, AlertTriangle } from 'lucide-react'
import { api } from '../api/client'
import { connectSSE } from '../api/sse'
import EmptyState from '../components/EmptyState'
import type { Alert, AlertSeverity, SSEAlertEvent } from '../api/types'

const SEVERITY_COLORS: Record<AlertSeverity, string> = {
  low: 'var(--color-allow)',
  medium: 'var(--color-defer)',
  high: 'var(--color-block)',
  critical: 'var(--color-block)',
}

function normalizeAlertSeverity(severity: string | undefined): AlertSeverity {
  if (severity === 'warning') return 'medium'
  if (severity === 'info') return 'low'
  if (severity === 'critical' || severity === 'high' || severity === 'medium' || severity === 'low') {
    return severity
  }
  return 'low'
}

function normalizeAlert(alert: Alert): Alert {
  return {
    ...alert,
    severity: normalizeAlertSeverity(alert.severity),
  }
}

const matchesAlertFilters = (
  alert: Pick<Alert, 'severity' | 'acknowledged'>,
  severity: AlertSeverity | '',
  showAcknowledged: boolean | undefined,
) => {
  if (severity && alert.severity !== severity) return false
  if (showAcknowledged !== undefined && alert.acknowledged !== showAcknowledged) return false
  return true
}

export default function Alerts() {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [loading, setLoading] = useState(true)
  const [severity, setSeverity] = useState<AlertSeverity | ''>('')
  const [showAcknowledged, setShowAcknowledged] = useState<boolean | undefined>(undefined)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.alerts({ severity: severity || undefined, acknowledged: showAcknowledged, limit: 100 })
      setAlerts(data.map(normalizeAlert))
    } catch { /* ignore */ }
    setLoading(false)
  }, [severity, showAcknowledged])

  useEffect(() => { load() }, [load])
  useEffect(() => { const t = setInterval(load, 30_000); return () => clearInterval(t) }, [load])

  useEffect(() => {
    const es = connectSSE(['alert'])
    es.addEventListener('alert', (e: MessageEvent) => {
      try {
        const data: SSEAlertEvent = JSON.parse(e.data)
        const newAlert: Alert = {
          alert_id: data.alert_id,
          severity: normalizeAlertSeverity(data.severity),
          metric: data.metric,
          session_id: data.session_id,
          message: data.message,
          details: {},
          triggered_at: data.timestamp,
          acknowledged: false,
          acknowledged_by: null,
          acknowledged_at: null,
        }
        setAlerts(prev => matchesAlertFilters(newAlert, severity, showAcknowledged) ? [newAlert, ...prev] : prev)
      } catch { /* ignore */ }
    })
    return () => es.close()
  }, [severity, showAcknowledged])

  const handleAcknowledge = async (alertId: string) => {
    try {
      await api.acknowledgeAlert(alertId)
      setAlerts(prev => prev
        .map(a => a.alert_id === alertId ? { ...a, acknowledged: true, acknowledged_by: 'dashboard', acknowledged_at: new Date().toISOString() } : a)
        .filter(alert => matchesAlertFilters(alert, severity, showAcknowledged)))
    } catch { /* ignore */ }
  }

  const openCount = alerts.filter(a => !a.acknowledged).length

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 className="section-header" style={{ marginBottom: 0 }}>
          <AlertTriangle size={18} style={{ color: 'var(--color-defer)' }} />
          Alerts Workbench
          {openCount > 0 && (
            <span className="badge badge-defer" style={{ marginLeft: 4 }}>{openCount} open</span>
          )}
        </h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <select value={severity} onChange={e => setSeverity(e.target.value as AlertSeverity | '')}>
            <option value="">All Severities</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
          </select>
          <select
            value={showAcknowledged === undefined ? '' : String(showAcknowledged)}
            onChange={e => setShowAcknowledged(e.target.value === '' ? undefined : e.target.value === 'true')}
          >
            <option value="">All Status</option>
            <option value="false">Unacknowledged</option>
            <option value="true">Acknowledged</option>
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
              <th>Severity</th>
              <th>Metric</th>
              <th>Session</th>
              <th>Message</th>
              <th>Triggered</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {alerts.map(alert => (
              <tr key={alert.alert_id} style={alert.acknowledged ? { opacity: 0.45 } : undefined}>
                <td>
                  <span className="mono" style={{ fontSize: '0.72rem', fontWeight: 700, color: SEVERITY_COLORS[alert.severity] || 'var(--color-text)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    {alert.severity}
                  </span>
                </td>
                <td className="mono" style={{ fontSize: '0.78rem' }}>{alert.metric}</td>
                <td>
                  <Link to={`/sessions/${alert.session_id}`} style={{ color: 'var(--color-accent)', textDecoration: 'none', fontFamily: 'var(--font-mono)', fontSize: '0.72rem' }}>
                    {(alert.session_id ?? '').length > 12 ? (alert.session_id ?? '').slice(0, 12) + '…' : (alert.session_id ?? '—')}
                  </Link>
                </td>
                <td className="text-secondary" style={{ fontSize: '0.78rem', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {alert.message}
                </td>
                <td className="mono text-muted" style={{ fontSize: '0.68rem' }}>
                  {new Date(alert.triggered_at).toLocaleString()}
                </td>
                <td>
                  {alert.acknowledged ? (
                    <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--color-allow)', fontSize: '0.72rem' }}>
                      <CheckCircle size={13} /> ACK
                    </span>
                  ) : (
                    <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--color-defer)', fontSize: '0.72rem' }}>
                      <XCircle size={13} /> OPEN
                    </span>
                  )}
                </td>
                <td>
                  {!alert.acknowledged && (
                    <button className="btn btn-primary" style={{ padding: '3px 10px', fontSize: '0.68rem' }} onClick={() => handleAcknowledge(alert.alert_id)}>
                      Acknowledge
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {alerts.length === 0 && !loading && (
              <tr>
                <td colSpan={7} style={{ padding: 0, border: 'none' }}>
                  <EmptyState
                    icon={<AlertTriangle size={20} />}
                    title="No alerts"
                    subtitle="Alerts will appear here when risk thresholds are exceeded"
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
