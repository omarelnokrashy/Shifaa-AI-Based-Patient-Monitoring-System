/**
 * Zustand chat-history store.
 *
 * Persists saved AI chat sessions to localStorage so conversations survive
 * reloads and can be revisited from the "Ask AI" page. This is a pure
 * front-end concern — the backend streaming protocol is untouched; we simply
 * snapshot the settled messages of each conversation here.
 *
 * Sessions are namespaced per user via the `userId` field (filter with
 * `sessionsForUser`) so doctors and nurses never see each other's history.
 *
 * Session shape:
 *   {
 *     id:          string,            // stable client id (uuid-ish)
 *     userId:      string,            // owning user's id (authStore user.id)
 *     title:       string,            // derived from the first user message
 *     mode:        'patient'|'general',
 *     patientId:   number|string|null,
 *     patientName: string|null,
 *     messages:    Array<{role,content,id,...}>,
 *     createdAt:   string,            // ISO
 *     updatedAt:   string,            // ISO
 *   }
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/**
 * Build a concise title from a conversation's first user message.
 *
 * @param {Array<{role:string, content:string}>} messages
 * @returns {string} A trimmed, length-capped title (falls back to 'New chat').
 */
function deriveTitle(messages) {
  const firstUser = messages.find((m) => m.role === 'user' && m.content?.trim())
  const text = firstUser?.content?.trim() || ''
  if (!text) return 'New chat'
  return text.length > 48 ? `${text.slice(0, 48)}…` : text
}

const useChatStore = create(
  persist(
    (set, get) => ({
      sessions: [],

      /**
       * Return this user's sessions, newest-updated first.
       *
       * @param {string} userId
       * @returns {Array<object>}
       */
      sessionsForUser: (userId) =>
        get().sessions
          .filter((s) => String(s.userId) === String(userId))
          .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),

      /**
       * Create or update a session by id. New sessions are prepended; existing
       * ones are patched (and their `updatedAt` bumped). The title is always
       * re-derived from the latest messages unless one was set manually.
       *
       * @param {object} session - Partial session; must include `id`.
       */
      upsertSession: (session) =>
        set((state) => {
          const now = new Date().toISOString()
          const idx = state.sessions.findIndex((s) => s.id === session.id)
          if (idx === -1) {
            return {
              sessions: [
                {
                  title: deriveTitle(session.messages || []),
                  createdAt: now,
                  updatedAt: now,
                  ...session,
                },
                ...state.sessions,
              ],
            }
          }
          const next = [...state.sessions]
          const prev = next[idx]
          next[idx] = {
            ...prev,
            ...session,
            // Keep a user-renamed title; otherwise refresh from messages.
            title: prev.titleEdited ? prev.title : deriveTitle(session.messages || prev.messages || []),
            updatedAt: now,
          }
          return { sessions: next }
        }),

      /**
       * Manually rename a session and mark it as user-edited so future
       * message updates don't overwrite the chosen title.
       *
       * @param {string} id
       * @param {string} title
       */
      renameSession: (id, title) =>
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === id ? { ...s, title, titleEdited: true, updatedAt: new Date().toISOString() } : s,
          ),
        })),

      /**
       * Delete a single session by id.
       *
       * @param {string} id
       */
      deleteSession: (id) =>
        set((state) => ({ sessions: state.sessions.filter((s) => s.id !== id) })),

      /**
       * Remove every session belonging to a user (e.g. "Clear history").
       *
       * @param {string} userId
       */
      clearUserSessions: (userId) =>
        set((state) => ({
          sessions: state.sessions.filter((s) => String(s.userId) !== String(userId)),
        })),
    }),
    {
      name: 'med-chat-history', // localStorage key
      partialize: (s) => ({ sessions: s.sessions }),
    },
  ),
)

export default useChatStore
