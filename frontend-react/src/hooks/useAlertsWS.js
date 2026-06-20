/**
 * useAlertsWS — maintains a persistent WebSocket connection to /api/ws/alerts
 * and pushes incoming events into the global alerts store.
 *
 * The connection reconnects automatically with exponential back-off (max 30 s).
 * In mock mode, synthetic alert events are injected on a timer instead.
 */
import { useEffect, useRef } from 'react'
import useAuthStore from '../store/authStore'
import useAlertsStore from '../store/alertsStore'
import { MOCK_ALERTS } from '../mock/data'

const IS_MOCK = import.meta.env.VITE_DATA_MODE !== 'live'
const WS_BASE = import.meta.env.VITE_WS_URL || 'ws://localhost:8000'

/**
 * React hook that opens (and maintains) a WebSocket connection to the alerts
 * endpoint and feeds incoming events into the global alerts store.
 *
 * **Side effects:**
 * - In live mode: opens a WebSocket to `WS_BASE/api/ws/alerts?token=…` and
 *   reconnects with exponential back-off (up to 30 s) on close/error.
 * - In mock mode: injects a synthetic alert from the mock dataset every 25 s
 *   via `setInterval`.
 * - Both modes clean up their timers / socket on unmount or token change.
 *
 * @returns {void} State changes are dispatched directly to `useAlertsStore`.
 */
export function useAlertsWS() {
  const token   = useAuthStore((s) => s.token)
  const addAlert = useAlertsStore((s) => s.addAlert)
  const wsRef    = useRef(null)
  const retryRef = useRef(0)
  const timerRef = useRef(null)

  useEffect(() => {
    if (!token) return

    if (IS_MOCK) {
      // Simulate a live alert arriving every ~25 s in mock mode
      let idx = 0
      timerRef.current = setInterval(() => {
        const a = MOCK_ALERTS[idx % MOCK_ALERTS.length]
        addAlert({ ...a, id: Date.now(), created_at: new Date().toISOString(), acknowledged: false })
        idx++
      }, 25000)
      return () => clearInterval(timerRef.current)
    }

    let cancelled = false

    /**
     * Open a new WebSocket connection. Called immediately on mount and
     * recursively scheduled after each unexpected close, using exponential
     * back-off capped at 30 seconds.
     */
    const connect = () => {
      if (cancelled) return
      const ws = new WebSocket(`${WS_BASE}/api/ws/alerts?token=${token}`)
      wsRef.current = ws

      ws.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data)
          if (event.type === 'alert') addAlert(event)
        } catch {/* ignore malformed frames */}
      }

      ws.onclose = () => {
        if (cancelled) return
        const delay = Math.min(1000 * 2 ** retryRef.current, 30000)
        retryRef.current++
        setTimeout(connect, delay)
      }

      ws.onerror = () => ws.close()
    }

    connect()

    return () => {
      cancelled = true
      clearTimeout(timerRef.current)
      wsRef.current?.close()
    }
  }, [token, addAlert])
}
