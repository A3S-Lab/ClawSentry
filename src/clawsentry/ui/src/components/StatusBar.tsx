import { useState, useEffect } from 'react'
import { api } from '../api/client'
import type { HealthResponse } from '../api/types'

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`
}

export default function StatusBar() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [status, setStatus] = useState<'online' | 'offline' | 'checking'>('checking')

  useEffect(() => {
    const check = async () => {
      try {
        const data = await api.health()
        setHealth(data)
        setStatus('online')
      } catch {
        setStatus('offline')
        setHealth(null)
      }
    }
    check()
    const timer = setInterval(check, 30_000)
    return () => clearInterval(timer)
  }, [])

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: '0.75rem' }}>
      {health && status === 'online' && (
        <span className="text-muted mono" style={{ fontSize: '0.68rem' }}>
          {formatUptime(health.uptime_seconds)} uptime · {health.trajectory_count.toLocaleString()} events
        </span>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span className={`status-dot ${status}`} />
        <span className="mono" style={{
          fontSize: '0.68rem',
          fontWeight: 600,
          color: status === 'online' ? 'var(--color-allow)' : status === 'offline' ? 'var(--color-block)' : 'var(--color-defer)',
        }}>
          {status === 'online' ? 'CONNECTED' : status === 'offline' ? 'DISCONNECTED' : 'CHECKING…'}
        </span>
      </div>
    </div>
  )
}
