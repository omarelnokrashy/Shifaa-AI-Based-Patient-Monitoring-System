/**
 * LoginPage.jsx — public authentication screen.
 *
 * Renders a two-panel layout (brand panel on desktop, login form on the right).
 * On successful login the JWT is stored via `useAuthStore` and the user is
 * redirected to their role-appropriate dashboard using `ROLE_REDIRECT`.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { HeartPulse, Eye, EyeOff, ShieldCheck } from 'lucide-react'
import useAuthStore from '../../store/authStore'
import { apiLogin } from '../../api/client'
import Button from '../../components/ui/Button'
import Input from '../../components/ui/Input'

/**
 * Maps each user role to its landing dashboard route.
 * Used after a successful login to navigate the user to the correct section.
 *
 * @type {Record<'doctor'|'nurse'|'admin', string>}
 */
const ROLE_REDIRECT = {
  doctor: '/doctor/dashboard',
  nurse:  '/nurse/dashboard',
  admin:  '/admin/dashboard',
}

/**
 * Login page component.
 *
 * Manages local form state (email, password, show/hide password, loading,
 * and error). Calls `apiLogin`, stores the returned JWT with `useAuthStore`,
 * then navigates the user to the dashboard matching their decoded role.
 *
 * @returns {JSX.Element} The full login page.
 */
export default function LoginPage() {
  const [email,    setEmail]    = useState('')
  const [password, setPassword] = useState('')
  const [showPwd,  setShowPwd]  = useState(false)
  const [error,    setError]    = useState('')
  const [loading,  setLoading]  = useState(false)

  const login    = useAuthStore((s) => s.login)
  const navigate = useNavigate()

  /**
   * Handles login form submission.
   *
   * Prevents the default form action, calls the `apiLogin` API, stores the
   * token, then redirects to the user's home dashboard. Sets an error message
   * if the request fails.
   *
   * @param {React.FormEvent<HTMLFormElement>} e - The form submit event.
   * @returns {Promise<void>}
   */
  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const token = await apiLogin(email, password)
      login(token)
      // Decode role from the token (authStore.login does this)
      const { user } = useAuthStore.getState()
      navigate(ROLE_REDIRECT[user?.role] || '/doctor/dashboard', { replace: true })
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Invalid credentials')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-navy-950 flex">
      {/* ── Left panel: brand ──────────────────────────────────────────── */}
      <div className="hidden lg:flex lg:w-[45%] flex-col justify-between p-12 bg-gradient-to-br from-navy-900 via-navy-950 to-teal-900/30">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-teal-600 flex items-center justify-center">
            <HeartPulse size={22} className="text-white" />
          </div>
          <span className="font-heading font-bold text-white text-lg">MedMonitor</span>
        </div>

        <div>
          <h1 className="font-heading font-bold text-4xl text-white leading-tight">
            Clinical decision support <br />
            <span className="text-teal-400">for every role.</span>
          </h1>
          <p className="mt-4 text-navy-300 text-base leading-relaxed max-w-sm">
            Real-time arrhythmia, fall, and seizure monitoring — unified with
            an AI-powered patient history assistant.
          </p>
          <div className="mt-8 grid grid-cols-3 gap-4">
            {[
              { label: 'Arrhythmia', sublabel: 'ECG cascade', color: 'text-teal-400' },
              { label: 'Fall',       sublabel: 'Vision AI',   color: 'text-teal-300' },
              { label: 'Seizure',    sublabel: 'VSViG+CJ',    color: 'text-teal-200' },
            ].map(({ label, sublabel, color }) => (
              <div key={label} className="bg-navy-900/60 rounded-xl p-4 border border-navy-800">
                <p className={`font-heading font-bold text-sm ${color}`}>{label}</p>
                <p className="text-navy-400 text-xs mt-0.5">{sublabel}</p>
              </div>
            ))}
          </div>
        </div>

        <p className="text-navy-500 text-xs">
          Graduation Project — Medical Monitoring System 2026
        </p>
      </div>

      {/* ── Right panel: login form ─────────────────────────────────────── */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-md">
          {/* Mobile brand */}
          <div className="flex items-center gap-2 mb-8 lg:hidden">
            <div className="w-8 h-8 rounded-lg bg-teal-600 flex items-center justify-center">
              <HeartPulse size={18} className="text-white" />
            </div>
            <span className="font-heading font-bold text-white text-base">MedMonitor</span>
          </div>

          <div className="bg-white rounded-2xl p-8 border border-navy-200 shadow-xl">
            <div className="mb-6">
              <h2 className="font-heading font-bold text-2xl text-navy-900">Sign in</h2>
              <p className="text-navy-500 text-sm mt-1">Enter your hospital credentials</p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <Input
                label="Email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="doctor@hospital.com"
                required
                autoFocus
                className="focus:border-teal-500"
              />
              <div className="relative">
                <Input
                  label="Password"
                  type={showPwd ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  required
                  className="focus:border-teal-500 pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowPwd((v) => !v)}
                  className="absolute right-3 bottom-2.5 text-navy-400 hover:text-navy-600 transition-colors"
                  aria-label={showPwd ? 'Hide password' : 'Show password'}
                >
                  {showPwd ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>

              {error && (
                <p className="text-red-600 text-sm bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                  {error}
                </p>
              )}

              <Button type="submit" className="w-full mt-2" size="lg" loading={loading}>
                Sign in
              </Button>
            </form>

            {/* Demo credentials */}
            <div className="mt-6 pt-5 border-t border-navy-100">
              <p className="text-navy-400 text-xs mb-3 flex items-center gap-1">
                <ShieldCheck size={12} /> Demo credentials
              </p>
              <div className="space-y-2">
                {[
                  { email: 'doctor@hospital.com', role: 'Doctor',  pwd: 'doctor123' },
                  { email: 'nurse@hospital.com',  role: 'Nurse',   pwd: 'nurse123' },
                  { email: 'admin@hospital.com',  role: 'Admin',   pwd: 'admin123' },
                ].map(({ email: e, role, pwd }) => (
                  <button
                    key={e}
                    type="button"
                    onClick={() => { setEmail(e); setPassword(pwd) }}
                    className="w-full text-left px-3 py-2 rounded-lg bg-navy-50 hover:bg-navy-100
                               border border-navy-100 hover:border-teal-600/30 transition-colors group"
                  >
                    <span className="text-teal-600 text-xs font-semibold group-hover:text-teal-700">{role}</span>
                    <span className="text-navy-600 text-xs ml-2">{e}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
