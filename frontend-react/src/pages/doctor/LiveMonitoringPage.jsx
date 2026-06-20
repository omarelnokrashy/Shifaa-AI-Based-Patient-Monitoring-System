/**
 * Live Monitoring View — shows all active fall/seizure sessions as a card grid.
 *
 * Each card clearly shows:
 *  - Session type (fall / seizure), patient name, mode
 *  - Current status: NORMAL (green) / INITIALISING (amber) / SEIZURE or FALL DETECTED (red)
 *  - A visible latch bar for the 30-second seizure hold window
 *  - One-click navigation to the patient
 *
 * Cards pulse when alert is active, stay calm when NORMAL — motion is
 * reserved strictly for alerting conditions.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Activity, PersonStanding, HeartPulse, Wifi, WifiOff } from 'lucide-react'
import Card, { CardHeader } from '../../components/ui/Card'
import { StatusBadge } from '../../components/ui/Badge'
import Button from '../../components/ui/Button'
import { MOCK_MONITORING_SESSIONS } from '../../mock/data'
import { clsx } from 'clsx'

const IS_MOCK = import.meta.env.VITE_DATA_MODE !== 'live'

/**
 * Live Monitoring page component.
 *
 * Displays a responsive card grid of all active fall/seizure monitoring sessions.
 * In mock mode (`VITE_DATA_MODE !== 'live'`) it uses static fixture data; in live
 * mode it polls `/api/monitoring/status` via the dashboard endpoint every 5 seconds.
 * A separate interval counts down the 30-second seizure latch window per session.
 *
 * @returns {JSX.Element} The live monitoring grid view.
 */
export default function LiveMonitoringPage() {
  const navigate  = useNavigate()
  const [sessions, setSessions] = useState([])
  const [latch,    setLatch]    = useState({})   // { sessionId: secondsRemaining }

  useEffect(() => {
    if (IS_MOCK) {
      setSessions(MOCK_MONITORING_SESSIONS)
      // Simulate latch countdown for the SEIZURE session
      const seiz = MOCK_MONITORING_SESSIONS.find((s) => s.status === 'SEIZURE')
      if (seiz) setLatch({ [seiz.room_id]: 28 })
      return
    }
    // Live: poll /api/monitoring/status every 5 s
    /**
     * Fetches active fall and seizure sessions from the dashboard API and
     * merges them into a single flat list annotated with a `type` field.
     *
     * @async
     * @returns {Promise<void>}
     */
    const fetchSessions = async () => {
      const { apiGetDashboard } = await import('../../api/client')
      const d = await apiGetDashboard()
      const combined = [
        ...(d.active_sessions?.fall    || []).map((s) => ({ ...s, type: 'fall' })),
        ...(d.active_sessions?.seizure || []).map((s) => ({ ...s, type: 'seizure' })),
      ]
      setSessions(combined)
    }
    fetchSessions()
    const id = setInterval(fetchSessions, 5000)
    return () => clearInterval(id)
  }, [])

  // Countdown the latch timer
  useEffect(() => {
    const id = setInterval(() => {
      setLatch((prev) => {
        const next = { ...prev }
        for (const k in next) {
          next[k] = Math.max(0, next[k] - 1)
          if (next[k] === 0) delete next[k]
        }
        return next
      })
    }, 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      <div>
        <h1 className="font-heading font-bold text-2xl text-navy-900">Live Monitoring</h1>
        <p className="text-navy-400 text-sm">{sessions.length} active sessions</p>
      </div>

      {sessions.length === 0 && (
        <Card className="py-12 text-center">
          <WifiOff size={32} className="mx-auto mb-3 text-navy-300" />
          <p className="text-navy-500 font-medium">No active monitoring sessions</p>
          <p className="text-navy-400 text-sm mt-1">Start monitoring from a patient's detail page.</p>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {sessions.map((session) => (
          <SessionCard
            key={session.room_id || session.session_id}
            session={session}
            latchSeconds={latch[session.room_id || session.session_id] || 0}
            onNavigate={() => navigate(`/doctor/patients/${session.patient_id}`)}
          />
        ))}
      </div>
    </div>
  )
}

/**
 * Card representing a single active monitoring session.
 *
 * Applies visual states based on session status:
 *  - Pulsing red border when a SEIZURE or FALL_DETECTED alert is active.
 *  - Amber border and a countdown progress bar during the 30-second latch window.
 *  - Neutral card otherwise.
 *
 * @param {object}   props
 * @param {object}   props.session      - Session data object (type, patient_name, status, etc.).
 * @param {number}   props.latchSeconds - Seconds remaining in the alert hold window (0 = no latch).
 * @param {Function} props.onNavigate   - Callback invoked when the card is clicked to navigate to the patient.
 * @returns {JSX.Element}
 */
function SessionCard({ session, latchSeconds, onNavigate }) {
  const isAlert    = session.status === 'SEIZURE' || session.status === 'FALL_DETECTED'
  const isLatched  = latchSeconds > 0 && !isAlert
  const TypeIcon   = session.type === 'seizure' ? Activity : PersonStanding

  return (
    <div
      className={clsx(
        'rounded-2xl border-2 p-5 transition-all duration-300 cursor-pointer',
        isAlert
          ? 'bg-red-50 border-red-400 animate-pulse-slow shadow-lg shadow-red-100'
          : isLatched
          ? 'bg-amber-50 border-amber-300'
          : 'bg-white border-navy-100 hover:border-teal-300 hover:shadow-md',
      )}
      onClick={onNavigate}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className={clsx(
            'p-2 rounded-lg',
            isAlert ? 'bg-red-100 text-red-600' : 'bg-navy-100 text-navy-600',
          )}>
            <TypeIcon size={16} />
          </div>
          <div>
            <p className="text-sm font-semibold text-navy-900">{session.patient_name}</p>
            <p className="text-xs text-navy-400 capitalize">{session.type} · {session.mode || 'monitor'}</p>
          </div>
        </div>
        <div className="flex items-center gap-1 text-xs text-teal-600">
          <Wifi size={12} className="animate-pulse" />
          <span>Live</span>
        </div>
      </div>

      {/* Status */}
      <div className="flex items-center justify-between mb-3">
        <StatusBadge status={session.status} />
        {session.type === 'seizure' && session.gate_score != null && (
          <span className="text-xs text-navy-500 font-mono">
            gate: {session.gate_score.toFixed(3)}
          </span>
        )}
        {session.type === 'fall' && session.fall_probability != null && (
          <span className="text-xs text-navy-500 font-mono">
            p(fall): {(session.fall_probability * 100).toFixed(0)}%
          </span>
        )}
      </div>

      {/* Latch countdown bar */}
      {isLatched && (
        <div className="mt-2">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-amber-700 font-semibold">Alert hold — {latchSeconds}s remaining</span>
          </div>
          <div className="h-1.5 bg-amber-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-amber-500 rounded-full transition-all duration-1000"
              style={{ width: `${(latchSeconds / 30) * 100}%` }}
            />
          </div>
        </div>
      )}

      {isAlert && (
        <div className="mt-3 text-xs font-bold text-red-700 text-center bg-red-100 rounded-lg py-2 uppercase tracking-wide">
          ⚠ {session.type === 'seizure' ? 'Seizure Detected' : 'Fall Detected'} — Alert Active
        </div>
      )}
    </div>
  )
}
