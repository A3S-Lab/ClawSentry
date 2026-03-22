import { useState, useEffect, useCallback } from 'react'
import { ShieldAlert, ShieldCheck, Clock } from 'lucide-react'
import { api, ApiError } from '../api/client'
import { connectSSE } from '../api/sse'
import { RiskBadge } from '../components/badges'
import CountdownTimer from '../components/CountdownTimer'
import type { SSEDecisionEvent } from '../api/types'

type DeferStatus = 'pending' | 'allowed' | 'denied' | 'expired'

interface DeferItem extends SSEDecisionEvent {
  status: DeferStatus
}

export default function DeferPanel() {
  const [items, setItems] = useState<DeferItem[]>([])
  const [resolveAvailable, setResolveAvailable] = useState(true)

  // Listen for DEFER decisions via SSE
  useEffect(() => {
    const es = connectSSE(['decision'])

    es.addEventListener('decision', (e: MessageEvent) => {
      try {
        const data: SSEDecisionEvent = JSON.parse(e.data)
        // Only track DEFER decisions with an approval_id
        if (data.decision === 'defer' && data.approval_id) {
          setItems(prev => {
            // Avoid duplicates
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
      const reason = decision === 'deny' ? 'operator denied via dashboard' : ''
      await api.resolve(approvalId, decision, reason)
      setItems(prev => prev.map(item =>
        item.approval_id === approvalId
          ? { ...item, status: decision === 'allow-once' ? 'allowed' : 'denied' }
          : item
      ))
    } catch (e) {
      if (e instanceof ApiError && e.status === 503) {
        setResolveAvailable(false)
      }
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
      <h2 className="section-header">DEFER Interactive Panel</h2>

      {!resolveAvailable && (
        <div className="card" style={{
          marginBottom: 16,
          borderColor: 'var(--color-defer)',
          background: 'rgba(210, 153, 34, 0.08)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--color-defer)', fontSize: '0.85rem' }}>
            <ShieldAlert size={16} />
            <span>Resolve not available — OpenClaw enforcement is not connected</span>
          </div>
        </div>
      )}

      {/* Pending items */}
      <div style={{ marginBottom: 24 }}>
        <div className="text-muted mono" style={{ fontSize: '0.7rem', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.1em' }}>
          Pending ({pendingItems.length})
        </div>
        {pendingItems.length === 0 ? (
          <div className="card" style={{ textAlign: 'center', padding: 32 }}>
            <ShieldCheck size={32} style={{ color: 'var(--color-text-muted)', marginBottom: 8 }} />
            <p className="text-muted" style={{ fontSize: '0.85rem' }}>No pending DEFER decisions</p>
            <p className="text-muted" style={{ fontSize: '0.75rem', marginTop: 4 }}>
              DEFER decisions will appear here in real-time
            </p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {pendingItems.map(item => (
              <div key={item.approval_id} className="card fade-in" style={{
                borderLeft: '3px solid var(--color-defer)',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      <span className="mono" style={{ fontSize: '0.85rem', fontWeight: 600 }}>{item.tool_name}</span>
                      <RiskBadge level={item.risk_level} />
                    </div>
                    <div className="mono" style={{
                      fontSize: '0.8rem',
                      color: 'var(--color-text-secondary)',
                      background: 'var(--color-surface-raised)',
                      padding: '6px 10px',
                      borderRadius: 'var(--radius)',
                      border: '1px solid var(--color-border)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}>
                      {item.command || '\u2014'}
                    </div>
                    {item.reason && (
                      <div className="text-secondary" style={{ fontSize: '0.75rem', marginTop: 4 }}>
                        {item.reason}
                      </div>
                    )}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, marginLeft: 16 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <Clock size={14} className="text-muted" />
                      {item.expires_at ? (
                        <CountdownTimer
                          expiresAt={item.expires_at}
                          onExpired={() => handleExpired(item.approval_id!)}
                        />
                      ) : (
                        <span className="mono text-muted" style={{ fontSize: '0.75rem' }}>No timeout</span>
                      )}
                    </div>
                    <div style={{ display: 'flex', gap: 6 }}>
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
            ))}
          </div>
        )}
      </div>

      {/* Resolved items */}
      {resolvedItems.length > 0 && (
        <div>
          <div className="text-muted mono" style={{ fontSize: '0.7rem', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.1em' }}>
            Resolved ({resolvedItems.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {resolvedItems.map(item => (
              <div key={item.approval_id} className="card" style={{
                opacity: 0.5,
                padding: '10px 16px',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                fontSize: '0.8rem',
              }}>
                <span className={`badge ${
                  item.status === 'allowed' ? 'badge-allow' :
                  item.status === 'denied' ? 'badge-block' :
                  'badge-defer'
                }`} style={{ textTransform: 'uppercase' }}>
                  {item.status}
                </span>
                <span className="mono">{item.tool_name}</span>
                <span className="text-secondary" style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {item.command || '\u2014'}
                </span>
                <span className="text-muted mono" style={{ fontSize: '0.7rem' }}>
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
