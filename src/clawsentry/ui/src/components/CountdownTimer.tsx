import { useState, useEffect } from 'react'

interface CountdownTimerProps {
  expiresAt: number  // Unix timestamp in seconds
  onExpired?: () => void
}

export default function CountdownTimer({ expiresAt, onExpired }: CountdownTimerProps) {
  const [remaining, setRemaining] = useState(() => Math.max(0, expiresAt - Date.now() / 1000))

  useEffect(() => {
    const timer = setInterval(() => {
      const left = Math.max(0, expiresAt - Date.now() / 1000)
      setRemaining(left)
      if (left <= 0) {
        clearInterval(timer)
        onExpired?.()
      }
    }, 1000)
    return () => clearInterval(timer)
  }, [expiresAt, onExpired])

  const isUrgent = remaining < 10
  const mins = Math.floor(remaining / 60)
  const secs = Math.floor(remaining % 60)
  const display = mins > 0 ? `${mins}:${String(secs).padStart(2, '0')}` : `${secs}s`

  return (
    <span className="mono" style={{
      fontSize: '0.8rem',
      fontWeight: 600,
      color: isUrgent ? 'var(--color-block)' : 'var(--color-defer)',
      animation: isUrgent ? 'pulse 1s ease-in-out infinite' : undefined,
    }}>
      {remaining <= 0 ? 'EXPIRED' : display}
    </span>
  )
}
