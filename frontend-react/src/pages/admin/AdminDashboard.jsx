/**
 * Admin System Dashboard — no clinical data; pure operational monitoring.
 * Shows 4-service health grid, uptime indicators, and quick user stats.
 */
import { useEffect, useState } from 'react'
import { Server, CheckCircle2, XCircle, AlertTriangle, Users, Cpu } from 'lucide-react'
import Card, { CardHeader } from '../../components/ui/Card'
import { apiGetDashboard, apiGetUsers } from '../../api/client'
import { clsx } from 'clsx'

/**
 * Admin System Dashboard page.
 *
 * Fetches backend service health (main, arrhythmia, fall, seizure services)
 * and the user roster on mount. Refreshes service health every 15 seconds.
 * Renders a 4-card service health grid and a 3-cell user/activity summary row.
 *
 * @returns {JSX.Element} The admin system dashboard.
 */
export default function AdminDashboard() {
  const [health, setHealth] = useState({})
  const [users,  setUsers]  = useState([])
  const [chatCount, setChatCount] = useState(0)

  useEffect(() => {
    Promise.all([apiGetDashboard(), apiGetUsers()]).then(([d, u]) => {
      setHealth(d.service_health || {})
      setChatCount(d.chat_count_24h || 0)
      setUsers(u)
    })
    const id = setInterval(() => apiGetDashboard().then((d) => setHealth(d.service_health || {})), 15000)
    return () => clearInterval(id)
  }, [])

  const SERVICES = [
    { key: 'main',        label: 'Main Backend',         port: 8000 },
    { key: 'arrhythmia',  label: 'Arrhythmia Service',   port: 8001 },
    { key: 'fall',        label: 'Fall Detection',        port: 8002 },
    { key: 'seizure',     label: 'Seizure Detection',     port: 8003 },
  ]

  /**
   * Counts the number of active users with the given role.
   *
   * @param {'doctor'|'nurse'|'admin'} role - The role to filter by.
   * @returns {number} The count of active users with that role.
   */
  const roleCount = (role) => users.filter((u) => u.role === role && u.is_active).length

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      <div>
        <h1 className="font-heading font-bold text-2xl text-navy-900">System Dashboard</h1>
        <p className="text-navy-400 text-sm">Operational health of all backend services</p>
      </div>

      {/* Service health grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {SERVICES.map(({ key, label, port }) => {
          const h = health[key] || {}
          const isOk = h.status === 'ok'
          return (
            <Card key={key} padded={false} className={clsx(
              'p-5 border-l-4',
              isOk ? 'border-l-green-500' : 'border-l-red-500',
            )}>
              <div className="flex items-start justify-between mb-3">
                <div className={clsx('p-2 rounded-lg', isOk ? 'bg-green-50' : 'bg-red-50')}>
                  <Server size={16} className={isOk ? 'text-green-600' : 'text-red-600'} />
                </div>
                {isOk
                  ? <CheckCircle2 size={18} className="text-green-500" />
                  : <XCircle size={18} className="text-red-500 animate-pulse" />
                }
              </div>
              <p className="font-heading font-semibold text-sm text-navy-800">{label}</p>
              <p className="text-xs text-navy-400 mt-0.5">:{port}</p>
              {h.models_loaded != null && (
                <p className={clsx('text-xs mt-1 font-medium', h.models_loaded ? 'text-green-600' : 'text-amber-600')}>
                  {h.models_loaded ? '✓ Models loaded' : '⏳ Loading models…'}
                </p>
              )}
              {h.active_sessions != null && (
                <p className="text-xs text-navy-500 mt-1">{h.active_sessions} active sessions</p>
              )}
              {h.device && (
                <span className="inline-flex items-center gap-1 mt-1 text-xs font-mono text-navy-400">
                  <Cpu size={10} /> {h.device}
                </span>
              )}
            </Card>
          )
        })}
      </div>

      {/* User stats */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Doctors',   count: roleCount('doctor'), color: 'text-teal-600', bg: 'bg-teal-50' },
          { label: 'Nurses',    count: roleCount('nurse'),  color: 'text-navy-600', bg: 'bg-navy-100' },
          { label: 'Chat Queries (24h)', count: chatCount, color: 'text-purple-600', bg: 'bg-purple-50' },
        ].map(({ label, count, color, bg }) => (
          <Card key={label} padded={false} className="p-4 flex items-center gap-3">
            <div className={clsx('p-2.5 rounded-xl', bg)}>
              <Users size={18} className={color} />
            </div>
            <div>
              <p className="font-heading font-bold text-2xl text-navy-900">{count}</p>
              <p className="text-xs text-navy-400">{label}</p>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
