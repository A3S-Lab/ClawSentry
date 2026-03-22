import { useState, useEffect, useRef } from 'react'
import { connectSSE } from '../api/sse'
import { DecisionBadge, RiskBadge } from './badges'
import type { SSEDecisionEvent } from '../api/types'

export default function DecisionFeed() {
  const [events, setEvents] = useState<SSEDecisionEvent[]>([])
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const es = connectSSE(['decision'])

    es.addEventListener('decision', (e: MessageEvent) => {
      try {
        const data: SSEDecisionEvent = JSON.parse(e.data)
        setEvents(prev => [data, ...prev].slice(0, 50))
      } catch { /* ignore parse errors */ }
    })

    es.onerror = () => {
      // SSE will auto-reconnect
    }

    return () => es.close()
  }, [])

  return (
    <div className="card" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div className="card-header">Live Decision Feed</div>
      <div ref={containerRef} style={{ flex: 1, overflowY: 'auto', maxHeight: 400 }}>
        {events.length === 0 ? (
          <p className="text-muted" style={{ padding: 16, fontSize: '0.8rem' }}>
            Waiting for decisions...
          </p>
        ) : (
          events.map((evt, i) => (
            <div key={`${evt.event_id}-${i}`} className="fade-in" style={{
              padding: '8px 12px',
              borderBottom: '1px solid var(--color-border)',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              fontSize: '0.8rem',
            }}>
              <span className="mono text-muted" style={{ fontSize: '0.7rem', minWidth: 65 }}>
                {new Date(evt.timestamp).toLocaleTimeString()}
              </span>
              <span className="mono" style={{ minWidth: 110, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {evt.tool_name}
              </span>
              <DecisionBadge decision={evt.decision} />
              <RiskBadge level={evt.risk_level} />
              <span className="text-secondary" style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.75rem' }}>
                {evt.reason}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
