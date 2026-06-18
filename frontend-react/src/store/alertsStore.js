/**
 * Alerts store — in-memory list of live alerts received via WebSocket.
 * Persisted to sessionStorage so a page refresh doesn't lose the current
 * shift's alert feed, but it is cleared on tab close.
 */
import { create } from 'zustand'

const useAlertsStore = create((set, get) => ({
  alerts: [],       // AlertEvent[]
  unread: 0,

  addAlert: (alert) =>
    set((s) => ({
      alerts: [alert, ...s.alerts].slice(0, 200),  // cap at 200
      unread: s.unread + 1,
    })),

  acknowledge: (id) =>
    set((s) => ({
      alerts: s.alerts.map((a) =>
        a.id === id ? { ...a, acknowledged: true } : a
      ),
    })),

  clearUnread: () => set({ unread: 0 }),

  reset: () => set({ alerts: [], unread: 0 }),
}))

export default useAlertsStore
