import { getToken } from './client'

export type SSEStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

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

/**
 * Create a managed SSE connection with auto-reconnect and status tracking.
 * Returns a cleanup function.
 */
export function createManagedSSE(
  types: string[],
  callbacks: {
    onEvent: (type: string, data: unknown) => void
    onStatusChange: (status: SSEStatus, detail?: string) => void
  },
  options?: { sessionId?: string; minRisk?: string; maxRetries?: number },
): () => void {
  let es: EventSource | null = null
  let retryCount = 0
  let retryTimer: ReturnType<typeof setTimeout> | null = null
  let stopped = false
  const maxRetries = options?.maxRetries ?? 10

  function connect() {
    if (stopped) return
    callbacks.onStatusChange('connecting')
    es = connectSSE(types, options)

    es.onopen = () => {
      retryCount = 0
      callbacks.onStatusChange('connected')
    }

    es.onerror = () => {
      if (stopped) return
      es?.close()
      es = null
      if (retryCount >= maxRetries) {
        callbacks.onStatusChange('error', `Failed after ${maxRetries} retries`)
        return
      }
      const delay = Math.min(1000 * 2 ** retryCount, 30000)
      retryCount++
      callbacks.onStatusChange('disconnected', `Reconnecting in ${Math.round(delay / 1000)}s...`)
      retryTimer = setTimeout(connect, delay)
    }

    for (const t of types) {
      es.addEventListener(t, (e: MessageEvent) => {
        try {
          callbacks.onEvent(t, JSON.parse(e.data))
        } catch { /* ignore parse errors */ }
      })
    }
  }

  connect()

  return () => {
    stopped = true
    if (retryTimer) clearTimeout(retryTimer)
    es?.close()
    es = null
  }
}
