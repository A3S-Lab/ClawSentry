import { useState, useEffect, useCallback } from 'react'
import { ShieldAlert, ShieldCheck, Clock } from 'lucide-react'
import { api, ApiError } from '../api/client'
import { connectSSE } from '../api/sse'
import { RiskBadge } from '../components/badges'
import CountdownTimer from '../components/CountdownTimer'
import EmptyState from '../components/EmptyState'
import type { SSEDecisionEvent } from '../api/types'

type DeferStatus = 'pending' | 'allowed' | 'denied' | 'expired'

interface DeferItem extends SSEDecisionEvent {
  status: DeferStatus
}

export default function DeferPanel() {
  const [items, setItems] = useState<DeferItem[]>([])
  const [resolveAvailable, setResolveAvailable] = useState(true)

  useEffect(() => {
    const es = connectSSE(['decision'])
    es.addEventListener('decision', (e: MessageEvent) => {
      try {
        const data: SSEDecisionEvent = JSON.parse(e.data)
        if (data.decision === 'defer' && data.approval_id) {
          setItems(prev => {
            if (prev.some(item => item.approval_id === data.approval_id)) return prev
            return [{ ...data, status: 'pending' as DeferStatus }, ...prev]
          })
        }
      } catch { /* ignore */ }
    })
    return () => es.close()
  }, [])

  const handleResolve = useCallback(async (approvalId: string, decision: 'allow-once' | 'deny') => {
    try {
      await api.resolve(approvalId, decision, decision === 'deny' ? 'operator denied via dashboard' : '')
      setItems(prev => prev.map(item =>
        item.approval_id === approvalId
          ? { ...item, status: decision === 'allow-once' ? 'allowed' : 'denied' }
          : item
      ))
    } catch (e) {
      if (e instanceof ApiError && e.status === 503) setResolveAvailable(false)
    }
  }, [])

  const handleExpired = useCallback((approvalId: string) => {
    setItems(prev => prev.map(item =>
      item.approval_id === approvalId && item.status === 'pending'
        ? { ...item, status: 'expired' }
        : item
    ))
  }, [])

  const pendingItems = items.filter(i => i.status === 'pending')
  const resolvedItems = items.filter(i => i.status !== 'pending')

  return (
    <div>
      <h2 className="section-header">
        <ShieldCheck size={18} style={{ color: 'var(--color-accent)' }} />
        DEFER Interactive Panel
        {pendingItems.length > 0 && (
          <span className="badge badge-defer" style={{ marginLeft: 4 }}>
            {pendingItems.length} pending
          </span>
        )}
      </h2>

      {!resolveAvailable && (
        <div className="card" style={{ marginBottom: 16, borderColor: 'rgba(245,158,11,0.3)', background: 'rgba(245,158,11,0.05)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--color-defer)', fontSize: '0.83rem' }}>
            <ShieldAlert size={15} />
            Resolve not available — OpenClaw enforcement is not connected
          </div>
        </div>
      )}

      {/* Pending */}
      <div style={{ marginBottom: 24 }}>
        <div className="text-muted mono" style={{ fontSize: '0.68rem', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.1em' }}>
          Pending ({pendingItems.length})
        </div>
        {pendingItems.length === 0 ? (
          <div className="card">
            <EmptyState
              icon={<ShieldCheck size={20} />}
              title="No pending DEFER decisions"
              subtitle="DEFER decisions will appear here in real-time when agents require approval"
            />
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {pendingItems.map(item => {
              const remaining = item.expires_at ? item.expires_at - Date.now() / 1000 : 999
              const isUrgent = remaining < 10
              return (
                <div
                  key={item.approval_id}
                  className={`card fade-in ${isUrgent ? 'defer-card-critical' : 'defer-card-pending'}`}
                  style={{ borderLeftWidth: 3, borderLeftStyle: 'solid', borderLeftColor: isUrgent ? 'var(--color-block)' : 'var(--color-defer)' }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                        <span className="mono" style={{ fontSize: '0.88rem', fontWeight: 600 }}>{item.tool_name}</span>
                        <RiskBadge level={item.risk_level} />
                      </div>
                      <div className="cmd-snippet" style={{ maxWidth: '100%', marginBottom: item.reason ? 6 : 0 }}>
                        {item.command || '—'}
                      </div>
                      {item.reason && (
                        <div className="text-secondary" style={{ fontSize: '0.73rem', marginTop: 4 }}>
                          {item.reason}
                        </div>
                      )}
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 10, flexShrink: 0 }}>
                      {item.expires_at ? (
                        <CountdownTimer
                          expiresAt={item.expires_at}
                          onExpired={() => handleExpired(item.approval_id!)}
                        />
                      ) : (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                          <Clock size={13} className="text-muted" />
                          <span className="mono text-muted" style={{ fontSize: '0.72rem' }}>No timeout</span>
                        </div>
                      )}
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button
                          className="btn btn-allow"
                          onClick={() => handleResolve(item.approval_id!, 'allow-once')}
                          disabled={!resolveAvailable}
                        >
                          Allow
                        </button>
                        <button
                          className="btn btn-deny"
                          onClick={() => handleResolve(item.approval_id!, 'deny')}
                          disabled={!resolveAvailable}
                        >
                          Deny
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Resolved */}
      {resolvedItems.length > 0 && (
        <div>
          <div className="text-muted mono" style={{ fontSize: '0.68rem', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.1em' }}>
            Resolved ({resolvedItems.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {resolvedItems.map(item => (
              <div key={item.approval_id} className="card" style={{ opacity: 0.45, padding: '9px 14px', display: 'flex', alignItems: 'center', gap: 10, fontSize: '0.78rem' }}>
                <span className={`badge ${item.status === 'allowed' ? 'badge-allow' : item.status === 'denied' ? 'badge-block' : 'badge-defer'}`}>
                  {item.status}
                </span>
                <span className="mono">{item.tool_name}</span>
                <span className="cmd-snippet" style={{ flex: 1 }}>{item.command || '—'}</span>
                <span className="text-muted mono" style={{ fontSize: '0.68rem' }}>
                  {new Date(item.timestamp).toLocaleTimeString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
