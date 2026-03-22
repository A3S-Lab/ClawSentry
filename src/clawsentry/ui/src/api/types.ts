export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'
export type DecisionVerdict = 'allow' | 'block' | 'defer' | 'modify'

export interface HealthResponse {
  status: string
  uptime_seconds: number
  cache_size: number
  trajectory_count: number
  policy_engine: string
  auth_enabled: boolean
}

export interface SummaryResponse {
  total_records: number
  by_source_framework: Record<string, number>
  by_event_type: Record<string, number>
  by_decision: Record<string, number>
  by_risk_level: Record<string, number>
  by_actual_tier: Record<string, number>
  by_caller_adapter: Record<string, number>
  generated_at: string
  window_seconds: number | null
}

export interface SessionSummary {
  session_id: string
  agent_id: string
  source_framework: string
  caller_adapter: string
  current_risk_level: RiskLevel
  cumulative_score: number
  event_count: number
  high_risk_event_count: number
  decision_distribution: Record<string, number>
  first_event_at: string
  last_event_at: string
}

export interface SessionRisk {
  current_risk_level: RiskLevel
  cumulative_score: number
  dimensions_latest: { d1: number; d2: number; d3: number; d4: number; d5: number }
  risk_timeline: Array<{
    event_id: string
    occurred_at: string
    risk_level: RiskLevel
    composite_score: number
    tool_name: string
    decision: DecisionVerdict
  }>
  risk_hints_seen: string[]
  tools_used: string[]
  actual_tier_distribution: Record<string, number>
}

export interface TrajectoryRecord {
  event: Record<string, unknown>
  decision: {
    decision: DecisionVerdict
    reason: string
    risk_level: RiskLevel
    decision_latency_ms: number
  }
  risk_snapshot: {
    risk_level: RiskLevel
    composite_score: number
    dimensions: { d1: number; d2: number; d3: number; d4: number; d5: number }
  }
  meta: { actual_tier: string; caller_adapter: string }
  recorded_at: string
}

export interface Alert {
  alert_id: string
  severity: string
  metric: string
  session_id: string
  message: string
  details: Record<string, unknown>
  triggered_at: string
  acknowledged: boolean
  acknowledged_by: string | null
  acknowledged_at: string | null
}

export interface SSEDecisionEvent {
  session_id: string
  event_id: string
  risk_level: RiskLevel
  decision: DecisionVerdict
  tool_name: string
  actual_tier: string
  timestamp: string
  reason: string
  command: string
  approval_id?: string
  expires_at?: number
}

export interface SSEAlertEvent {
  alert_id: string
  severity: string
  metric: string
  session_id: string
  current_risk: string
  message: string
  timestamp: string
}
