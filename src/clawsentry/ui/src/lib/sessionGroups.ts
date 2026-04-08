import type { RiskLevel, SessionSummary } from '../api/types'

const RISK_ORDER: RiskLevel[] = ['critical', 'high', 'medium', 'low']

export type WorkspaceGroup = {
  key: string
  workspaceRoot: string
  workspaceLabel: string
  framework: string
  callerAdapters: string[]
  sessionCount: number
  highRiskSessionCount: number
  criticalSessionCount: number
  totalEvents: number
  latestActivityAt: string
  highestRisk: RiskLevel
  sessions: SessionSummary[]
}

export type FrameworkGroup = {
  framework: string
  sessionCount: number
  workspaceCount: number
  highRiskSessionCount: number
  totalEvents: number
  latestActivityAt: string
  highestRisk: RiskLevel
  workspaces: WorkspaceGroup[]
}

export function riskRank(level: string): number {
  const normalized = String(level || 'low').toLowerCase() as RiskLevel
  return RISK_ORDER.indexOf(normalized)
}

export function normalizeFramework(framework: string): string {
  return framework || 'unknown'
}

export function workspaceLabel(workspaceRoot: string): string {
  if (!workspaceRoot) return 'Unknown Workspace'
  const trimmed = workspaceRoot.replace(/\/+$/, '')
  const segments = trimmed.split('/').filter(Boolean)
  return segments[segments.length - 1] || workspaceRoot
}

export function formatRelativeTime(timestamp: string): string {
  if (!timestamp) return 'No activity'
  const delta = Date.now() - new Date(timestamp).getTime()
  if (!Number.isFinite(delta) || delta < 0) return 'Just now'
  const seconds = Math.floor(delta / 1000)
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function activityState(timestamp: string): 'hot' | 'warm' | 'idle' {
  if (!timestamp) return 'idle'
  const deltaMinutes = (Date.now() - new Date(timestamp).getTime()) / 60_000
  if (deltaMinutes <= 2) return 'hot'
  if (deltaMinutes <= 15) return 'warm'
  return 'idle'
}

export function groupSessions(sessions: SessionSummary[]): FrameworkGroup[] {
  const frameworkMap = new Map<string, Map<string, SessionSummary[]>>()

  for (const session of sessions) {
    const framework = normalizeFramework(session.source_framework)
    const workspaceRoot = session.workspace_root || ''
    if (!frameworkMap.has(framework)) {
      frameworkMap.set(framework, new Map())
    }
    const workspaceMap = frameworkMap.get(framework)!
    const key = workspaceRoot || `unknown:${session.session_id}`
    const existing = workspaceMap.get(key) || []
    existing.push(session)
    workspaceMap.set(key, existing)
  }

  const groupedSessions = Array.from(frameworkMap.entries())
    .map(([framework, workspaceMap]) => {
      const workspaces: WorkspaceGroup[] = Array.from(workspaceMap.entries())
        .map(([key, workspaceSessions]) => {
          const sortedSessions = [...workspaceSessions].sort((a, b) => {
            const rankDiff = riskRank(a.current_risk_level) - riskRank(b.current_risk_level)
            if (rankDiff !== 0) return rankDiff
            return new Date(b.last_event_at).getTime() - new Date(a.last_event_at).getTime()
          })
          const highestRisk = sortedSessions[0]?.current_risk_level || 'low'
          const latestActivityAt = sortedSessions
            .map(session => session.last_event_at)
            .sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0] || ''
          const adapters = Array.from(
            new Set(sortedSessions.map(session => session.caller_adapter).filter(Boolean)),
          )
          return {
            key,
            workspaceRoot: sortedSessions[0]?.workspace_root || '',
            workspaceLabel: workspaceLabel(sortedSessions[0]?.workspace_root || ''),
            framework,
            callerAdapters: adapters,
            sessionCount: sortedSessions.length,
            highRiskSessionCount: sortedSessions.filter(session => riskRank(session.current_risk_level) <= 1).length,
            criticalSessionCount: sortedSessions.filter(session => session.current_risk_level === 'critical').length,
            totalEvents: sortedSessions.reduce((sum, session) => sum + session.event_count, 0),
            latestActivityAt,
            highestRisk,
            sessions: sortedSessions,
          }
        })
        .sort((a, b) => {
          const rankDiff = riskRank(a.highestRisk) - riskRank(b.highestRisk)
          if (rankDiff !== 0) return rankDiff
          return new Date(b.latestActivityAt).getTime() - new Date(a.latestActivityAt).getTime()
        })

      const allSessions = workspaces.flatMap(workspace => workspace.sessions)
      const latestActivityAt = allSessions
        .map(session => session.last_event_at)
        .sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0] || ''
      const highestRisk = workspaces[0]?.highestRisk || 'low'

      return {
        framework,
        sessionCount: allSessions.length,
        workspaceCount: workspaces.length,
        highRiskSessionCount: allSessions.filter(session => riskRank(session.current_risk_level) <= 1).length,
        totalEvents: allSessions.reduce((sum, session) => sum + session.event_count, 0),
        latestActivityAt,
        highestRisk,
        workspaces,
      }
    })
    .sort((a, b) => {
      const rankDiff = riskRank(a.highestRisk) - riskRank(b.highestRisk)
      if (rankDiff !== 0) return rankDiff
      return new Date(b.latestActivityAt).getTime() - new Date(a.latestActivityAt).getTime()
    })

  return groupedSessions
}
