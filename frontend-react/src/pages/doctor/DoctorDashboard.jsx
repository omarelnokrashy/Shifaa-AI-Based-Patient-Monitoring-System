/**
 * Doctor Dashboard — the first screen doctors land on after login.
 *
 * Layout: 3-column stat bar at top, then a 2/3 + 1/3 split:
 *   Left:  Active alert feed (real-time, from Zustand + WS)
 *   Right: Recent patients + quick stat cards
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  HeartPulse, PersonStanding, Activity,
  Users, MessageSquare, AlertTriangle,
} from 'lucide-react'
import Card, { CardHeader } from '../../components/ui/Card'
import AlertFeed from '../../components/monitoring/AlertFeed'
import Button from '../../components/ui/Button'
import { StatusBadge } from '../../components/ui/Badge'
import { apiGetDashboard } from '../../api/client'
import useAlertsStore from '../../store/alertsStore'
import { formatDistanceToNow, calcAge } from '../../components/utils/time'

/**
 * Doctor Dashboard page.
 *
 * Fetches the aggregated dashboard summary (alert counts, recent alerts,
 * service health, chat count) from the API and merges it with live WebSocket
 * alerts from Zustand. Refreshes automatically every 30 seconds.
 *
 * @returns {JSX.Element} The clinical dashboard with stat bar, alert feed, and service health.
 */
export default function DoctorDashboard() {
  const navigate = useNavigate()
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const liveAlerts = useAlertsStore((s) => s.alerts)

  useEffect(() => {
    apiGetDashboard().then((d) => { setSummary(d); setLoading(false) })
    const id = setInterval(() => apiGetDashboard().then(setSummary), 30000)
    return () => clearInterval(id)
  }, [])

  const alertCounts = summary?.alert_counts || []
  const staticAlerts = summary?.recent_alerts || []
  const allAlerts = [...liveAlerts, ...staticAlerts].filter(
    (a, i, arr) => arr.findIndex((x) => x.id === a.id) === i
  ).sort((a, b) => new Date(b.created_at) - new Date(a.created_at))

  const serviceHealth = summary?.service_health || {}
  const chatCount = summary?.chat_count_24h || 0

  return (
    <div className="space-y-5 max-w-7xl mx-auto">
      <div>
        <h1 className="font-heading font-bold text-2xl text-navy-900">Clinical Dashboard</h1>
        <p className="text-navy-400 text-sm mt-0.5">Real-time patient monitoring and AI insights</p>
      </div>

      {/* ── Stat bar ──────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          Icon={AlertTriangle} label="Active Alerts"
          value={allAlerts.filter((a) => !a.acknowledged).length}
          color="text-red-600" bg="bg-red-50"
        />
        <StatCard
          Icon={HeartPulse} label="ECG Alerts (24h)"
          value={alertCounts.find((c) => c.alert_type === 'arrhythmia')?.count || 0}
          color="text-teal-600" bg="bg-teal-50"
        />
        <StatCard
          Icon={Activity} label="Seizure Events (24h)"
          value={alertCounts.find((c) => c.alert_type === 'seizure')?.count || 0}
          color="text-orange-600" bg="bg-orange-50"
        />
        <StatCard
          Icon={MessageSquare} label="Chat Queries (24h)"
          value={chatCount}
          color="text-navy-600" bg="bg-navy-100"
        />
      </div>

      {/* ── Main grid ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

        {/* Alert feed — 2/3 */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader
              title="Active Alerts"
              subtitle="Real-time • auto-updates via WebSocket"
              icon={AlertTriangle}
              action={
                <Button size="sm" variant="ghost" onClick={() => navigate('/doctor/monitoring')}>
                  Live Monitor →
                </Button>
              }
            />
            {loading ? <Skeleton /> : (
              <AlertFeed alerts={allAlerts.slice(0, 15)} />
            )}
          </Card>
        </div>

        {/* Right column — 1/3 */}
        <div className="space-y-4">

          {/* Service health */}
          <Card>
            <CardHeader title="Service Health" icon={Activity} />
            <div className="space-y-2">
              {Object.entries(serviceHealth).map(([name, h]) => (
                <div key={name} className="flex items-center justify-between py-1.5 border-b border-navy-50 last:border-0">
                  <span className="text-sm font-medium text-navy-700 capitalize">{name}</span>
                  <StatusBadge status={h?.status || 'unreachable'} />
                </div>
              ))}
            </div>
          </Card>

          {/* Quick actions */}
          <Card>
            <CardHeader title="Quick Actions" />
            <div className="space-y-2">
              <Button variant="secondary" className="w-full justify-start" onClick={() => navigate('/doctor/patients')}>
                <Users size={15} /> View Patients
              </Button>
              <Button variant="secondary" className="w-full justify-start" onClick={() => navigate('/doctor/monitoring')}>
                <Activity size={15} /> Live Monitoring
              </Button>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}

/**
 * Small metric card showing an icon, a numeric value, and a descriptive label.
 *
 * @param {object} props
 * @param {React.ElementType} props.Icon  - Lucide icon component to display.
 * @param {string}            props.label - Text label below the value.
 * @param {number|string}     props.value - Metric value to display prominently.
 * @param {string}            props.color - Tailwind text colour class for the icon.
 * @param {string}            props.bg    - Tailwind background colour class for the icon container.
 * @returns {JSX.Element}
 */
function StatCard({ Icon, label, value, color, bg }) {
  return (
    <Card padded={false} className="p-4 flex items-center gap-3">
      <div className={`p-2.5 rounded-xl ${bg} shrink-0`}>
        <Icon size={20} className={color} />
      </div>
      <div>
        <p className="font-heading font-bold text-2xl text-navy-900 leading-none">{value}</p>
        <p className="text-xs text-navy-400 mt-0.5">{label}</p>
      </div>
    </Card>
  )
}

/**
 * Loading skeleton for the alert feed section.
 *
 * Renders three animated placeholder blocks while dashboard data is fetching.
 *
 * @returns {JSX.Element}
 */
function Skeleton() {
  return (
    <div className="space-y-3">
      {[1, 2, 3].map((i) => (
        <div key={i} className="h-16 bg-navy-100 rounded-xl animate-pulse" />
      ))}
    </div>
  )
}
