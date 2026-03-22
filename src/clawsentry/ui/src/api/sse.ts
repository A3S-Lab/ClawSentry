import { getToken } from './client'

export function connectSSE(
  types?: string[],
  options?: { sessionId?: string; minRisk?: string },
): EventSource {
  const params = new URLSearchParams()
  const token = getToken()
  if (token) params.set('token', token)
  if (types?.length) params.set('types', types.join(','))
  if (options?.sessionId) params.set('session_id', options.sessionId)
  if (options?.minRisk) params.set('min_risk', options.minRisk)

  const url = `/report/stream?${params}`
  return new EventSource(url)
}
