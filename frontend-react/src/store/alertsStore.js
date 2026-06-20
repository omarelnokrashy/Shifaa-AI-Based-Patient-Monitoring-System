/**
 * Alerts store — in-memory list of live alerts received via WebSocket.
 * Persisted to sessionStorage so a page refresh doesn't lose the current
 * shift's alert feed, but it is cleared on tab close.
 */
import { create } from 'zustand'

const useAlertsStore = create((set, get) => ({
  alerts: [],       // AlertEvent[]
  unread: 0,

  /**
   * Prepend a new alert to the list (capped at 200) and increment the unread counter.
   *
   * @param {Object} alert - The alert event object received from the WebSocket.
   */
  addAlert: (alert) =>
    set((s) => ({
      alerts: [alert, ...s.alerts].slice(0, 200),  // cap at 200
      unread: s.unread + 1,
    })),

  /**
   * Mark a specific alert as acknowledged.
   *
   * @param {number|string} id - The `id` of the alert to acknowledge.
   */
  acknowledge: (id) =>
    set((s) => ({
      alerts: s.alerts.map((a) =>
        a.id === id ? { ...a, acknowledged: true } : a
      ),
    })),

  /** Reset the unread counter to zero (e.g. when the alert panel is opened). */
  clearUnread: () => set({ unread: 0 }),

  /** Clear all alerts and reset the unread counter (e.g. on logout). */
  reset: () => set({ alerts: [], unread: 0 }),
}))

export default useAlertsStore
