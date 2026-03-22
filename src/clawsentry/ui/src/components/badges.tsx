import type { RiskLevel, DecisionVerdict } from '../api/types'

export function DecisionBadge({ decision }: { decision: DecisionVerdict }) {
  const cls = `badge badge-${decision}`
  return <span className={cls}>{decision}</span>
}

export function RiskBadge({ level }: { level: RiskLevel }) {
  const cls = `badge badge-risk-${level}`
  return <span className={cls}>{level}</span>
}
