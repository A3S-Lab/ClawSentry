import { useState, useEffect } from 'react'
import { createManagedSSE, type SSEStatus } from '../api/sse'
import { DecisionBadge, RiskBadge } from './badges'
import EmptyState from './EmptyState'
import { Activity, Wifi, WifiOff } from 'lucide-react'
import type { SSEDecisionEvent } from '../api/types'

function TierBadge({ tier }: { tier: string }) {
  const t = tier.toUpperCase()
  const cls = t === 'L3' ? 'badge-tier-l3' : t === 'L2' ? 'badge-tier-l2' : 'badge-tier-l1'
  return <span className={`badge ${cls}`}>{t}</span>
}

function ConnectionStatus({ status, detail }: { status: SSEStatus; detail?: string }) {
  if (status === 'connected') return null
  const color = status === 'connecting' ? 'var(--color-amber)' :
                status === 'disconnected' ? 'var(--color-amber)' : 'var(--color-red)'
  const icon = status === 'error' ? <WifiOff size={10} /> : <Wifi size={10} />
  const label = status === 'connecting' ? 'Connecting...' :
                status === 'disconnected' ? (detail || 'Reconnecting...') :
                (detail || 'Connection failed')
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 5,
      padding: '4px 10px', fontSize: '0.65rem', color,
      borderBottom: '1px solid var(--color-border)',
    }}>
      {icon}
      <span className="mono">{label}</span>
    </div>
  )
}

export default function DecisionFeed() {
  const [events, setEvents] = useState<SSEDecisionEvent[]>([])
  const [sseStatus, setSSEStatus] = useState<SSEStatus>('connecting')
  const [statusDetail, setStatusDetail] = useState<string>()

  useEffect(() => {
    const cleanup = createManagedSSE(
      ['decision'],
      {
        onEvent: (_type, data) => {
          setEvents(prev => [data as SSEDecisionEvent, ...prev].slice(0, 60))
        },
        onStatusChange: (status, detail) => {
          setSSEStatus(status)
          setStatusDetail(detail)
        },
      },
    )
    return cleanup
  }, [])

  return (
    <div className="card" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div className="card-header">
        <Activity size={12} />
        Live Decision Feed
        {sseStatus === 'connected' && (
          <span style={{ marginLeft: 4, color: '#22c55e', fontSize: '0.5rem' }}>●</span>
        )}
        {events.length > 0 && (
          <span className="mono" style={{ marginLeft: 'auto', color: 'var(--color-text-muted)', fontSize: '0.65rem' }}>
            {events.length} events
          </span>
        )}
      </div>
      <ConnectionStatus status={sseStatus} detail={statusDetail} />
      <div style={{ flex: 1, overflowY: 'auto', maxHeight: 420 }}>
        {events.length === 0 ? (
          <EmptyState
            icon={<Activity size={20} />}
            title="Waiting for decisions"
            subtitle={sseStatus === 'connected'
              ? 'Real-time events will appear here as agents execute tools'
              : 'Establishing connection to gateway...'}
          />
        ) : (
          events.map((evt, i) => (
            <div key={`${evt.event_id}-${i}`} className="slide-in" style={{
              padding: '9px 14px',
              borderBottom: '1px solid var(--color-border)',
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                <span className="mono text-muted" style={{ fontSize: '0.65rem', minWidth: 60 }}>
                  {new Date(evt.timestamp).toLocaleTimeString()}
                </span>
                <span className="mono" style={{ fontSize: '0.8rem', fontWeight: 500, minWidth: 100, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {evt.tool_name}
                </span>
                <DecisionBadge decision={evt.decision} />
                <RiskBadge level={evt.risk_level} />
                <TierBadge tier={evt.actual_tier} />
              </div>
              {evt.command && (
                <div style={{ paddingLeft: 67 }}>
                  <span className="cmd-snippet">{evt.command}</span>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
