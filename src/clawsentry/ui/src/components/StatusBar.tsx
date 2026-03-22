import { useState, useEffect } from 'react'
import { api } from '../api/client'
import type { HealthResponse } from '../api/types'

export default function StatusBar() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [status, setStatus] = useState<'online' | 'offline' | 'checking'>('checking')

  useEffect(() => {
    let timer: ReturnType<typeof setInterval>

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
    timer = setInterval(check, 30_000)
    return () => clearInterval(timer)
  }, [])

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: '0.8rem' }}>
      {health && (
        <span className="text-muted mono" style={{ fontSize: '0.7rem' }}>
          {health.trajectory_count} trajectories
        </span>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span className={`status-dot ${status}`} />
        <span className="mono" style={{
          fontSize: '0.7rem',
          color: status === 'online' ? 'var(--color-allow)' : status === 'offline' ? 'var(--color-block)' : 'var(--color-defer)'
        }}>
          {status === 'online' ? 'CONNECTED' : status === 'offline' ? 'DISCONNECTED' : 'CHECKING'}
        </span>
      </div>
    </div>
  )
}
