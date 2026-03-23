import { useState, useEffect } from 'react'

interface CountdownTimerProps {
  expiresAt: number       // Unix timestamp (seconds)
  totalSeconds?: number   // for ring progress (default 30)
  onExpired?: () => void
}

export default function CountdownTimer({ expiresAt, totalSeconds = 30, onExpired }: CountdownTimerProps) {
  const [remaining, setRemaining] = useState(() => Math.max(0, expiresAt - Date.now() / 1000))

  useEffect(() => {
    const timer = setInterval(() => {
      const left = Math.max(0, expiresAt - Date.now() / 1000)
      setRemaining(left)
      if (left <= 0) { clearInterval(timer); onExpired?.() }
    }, 500)
    return () => clearInterval(timer)
  }, [expiresAt, onExpired])

  if (remaining <= 0) {
    return <span className="mono" style={{ fontSize: '0.75rem', color: 'var(--color-block)', fontWeight: 700 }}>EXPIRED</span>
  }

  const isUrgent = remaining < 10
  const color = isUrgent ? 'var(--color-block)' : 'var(--color-defer)'
  const pct = Math.min(1, remaining / totalSeconds)

  // SVG ring
  const R = 16
  const C = 2 * Math.PI * R
  const dash = pct * C

  const mins = Math.floor(remaining / 60)
  const secs = Math.floor(remaining % 60)
  const display = mins > 0 ? `${mins}:${String(secs).padStart(2, '0')}` : `${secs}s`

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <svg width={40} height={40} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={20} cy={20} r={R} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={3} />
        <circle
          cx={20} cy={20} r={R}
          fill="none"
          stroke={color}
          strokeWidth={3}
          strokeDasharray={`${dash} ${C}`}
          strokeLinecap="round"
          style={{ transition: 'stroke-dasharray 0.5s ease, stroke 0.3s ease' }}
        />
      </svg>
      <span className="mono" style={{ fontSize: '0.85rem', fontWeight: 700, color, minWidth: 32 }}>
        {display}
      </span>
    </div>
  )
}
