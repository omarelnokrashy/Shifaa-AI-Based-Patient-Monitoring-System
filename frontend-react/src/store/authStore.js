/**
 * Zustand auth store.
 *
 * JWT storage decision: localStorage.
 * Tradeoff: httpOnly cookies prevent XSS token theft but require same-origin
 * or CORS-credentialed requests and a server-side logout endpoint. For a
 * hospital intranet deployment where the API and UI share a domain, httpOnly
 * cookies are preferred. For this prototype (cross-origin dev, simple setup)
 * localStorage is used with the tradeoff acknowledged — a future hardening
 * pass should move to httpOnly cookies via a `/api/auth/cookie` endpoint.
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { jwtDecode } from 'jwt-decode'

const useAuthStore = create(
  persist(
    (set) => ({
      token: null,
      user: null,   // { id, name, role, email }

      /**
       * Decode a JWT, extract user fields, and persist both token and user to state.
       *
       * @param {string} token - A valid JWT access token returned by the login endpoint.
       */
      login: (token) => {
        try {
          const payload = jwtDecode(token)
          set({
            token,
            user: {
              id:   payload.sub,
              name: payload.name,
              role: payload.role,
            },
          })
        } catch {
          console.error('Failed to decode JWT')
        }
      },

      /**
       * Clear the stored token and user, effectively ending the session.
       * The Axios interceptor will stop attaching the Authorization header
       * after this call.
       */
      logout: () => set({ token: null, user: null }),
    }),
    {
      name: 'med-auth',   // localStorage key
      partialize: (s) => ({ token: s.token, user: s.user }),
    }
  )
)

export default useAuthStore
