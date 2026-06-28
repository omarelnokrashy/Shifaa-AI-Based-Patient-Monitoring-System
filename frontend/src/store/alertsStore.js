/**
 * Alerts store — in-memory list of live alerts received via WebSocket.
 * Persisted to sessionStorage so a page refresh doesn't lose the current
 * shift's alert feed, but it is cleared on tab close.
 */
import { create } from 'zustand'

const useAlertsStore = create((set, get) => ({
  alerts: [],       // AlertEvent[]
  unread: 0,
  currentAudio: null, // Audio instance

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
   * Initialize/set active alerts list.
   *
   * @param {Object[]} alerts - Array of active alerts.
   */
  setAlerts: (alerts) =>
    set({ alerts }),

  /**
   * Remove a specific alert from the active list.
   *
   * @param {number|string} id - The ID of the alert to remove.
   */
  removeAlert: (id) =>
    set((s) => ({
      alerts: s.alerts.filter((a) => a.id !== id),
    })),

  /** Mark a specific alert as acknowledged. */
  acknowledge: (id) =>
    set((s) => ({
      alerts: s.alerts.map((a) =>
        a.id === id ? { ...a, acknowledged: true } : a
      ),
    })),

  /** Reset the unread counter to zero (e.g. when the alert panel is opened). */
  clearUnread: () => set({ unread: 0 }),

  /** Play the security alarm sound (loops, auto-stops after 30s) */
  playAlarmSound: () => {
    const current = get().currentAudio
    if (current) {
      current.pause()
      current.currentTime = 0
    }
    const audio = new Audio('/uploads/freesound_community-security-alarm-63578.mp3')
    audio.loop = true
    set({ currentAudio: audio })
    audio.play().catch((err) => {
      console.warn('Alert audio play blocked by browser:', err)
    })

    // Auto-stop after 30 seconds max
    setTimeout(() => {
      const active = get().currentAudio
      if (active === audio) {
        audio.pause()
        audio.currentTime = 0
        set({ currentAudio: null })
      }
    }, 30000)
  },

  /** Stop the security alarm sound if active */
  stopAlarmSound: () => {
    const audio = get().currentAudio
    if (audio) {
      audio.pause()
      audio.currentTime = 0
      set({ currentAudio: null })
    }
  },

  /** Clear all alerts and reset the unread counter (e.g. on logout). */
  reset: () => {
    get().stopAlarmSound()
    set({ alerts: [], unread: 0 })
  },
}))

export default useAlertsStore
