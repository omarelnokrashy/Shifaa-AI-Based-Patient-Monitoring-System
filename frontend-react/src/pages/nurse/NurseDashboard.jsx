/**
 * Nurse Dashboard — same alert-first principle as doctor, but read-only clinical data.
 * Primary job: triage and acknowledge alerts for assigned patients.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, CheckCheck, Users } from 'lucide-react'
import Card, { CardHeader } from '../../components/ui/Card'
import AlertFeed from '../../components/monitoring/AlertFeed'
import Button from '../../components/ui/Button'
import { apiGetAlerts, apiGetPatients } from '../../api/client'
import useAlertsStore from '../../store/alertsStore'

export default function NurseDashboard() {
  const navigate     = useNavigate()
  const [alerts, setAlerts]   = useState([])
  const [patients, setPatients] = useState([])
  const liveAlerts   = useAlertsStore((s) => s.alerts)

  useEffect(() => {
    Promise.all([apiGetAlerts(), apiGetPatients()]).then(([a, p]) => {
      setAlerts(a); setPatients(p)
    })
  }, [])

  const allAlerts = [...liveAlerts, ...alerts]
    .filter((a, i, arr) => arr.findIndex((x) => x.id === a.id) === i)
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))

  const unacknowledged = allAlerts.filter((a) => !a.acknowledged)

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      <div>
        <h1 className="font-heading font-bold text-2xl text-navy-900">Nurse Dashboard</h1>
        <p className="text-navy-400 text-sm">
          {unacknowledged.length > 0
            ? `${unacknowledged.length} alert${unacknowledged.length > 1 ? 's' : ''} requiring attention`
            : 'No unacknowledged alerts'}
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Alert feed — 2/3 */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader
              title="Alerts Requiring Attention"
              subtitle="Click to view patient — ✓ to acknowledge"
              icon={Bell}
            />
            <AlertFeed alerts={allAlerts.slice(0, 20)} />
          </Card>
        </div>

        {/* Patient quick list */}
        <Card>
          <CardHeader
            title="Patients"
            icon={Users}
            action={<Button size="sm" variant="ghost" onClick={() => navigate('/nurse/patients')}>All →</Button>}
          />
          <div className="space-y-1">
            {patients.slice(0, 8).map((p) => (
              <button
                key={p.id}
                onClick={() => navigate(`/nurse/patients/${p.id}`)}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-navy-50 transition-colors text-left"
              >
                <div className="w-7 h-7 rounded-full bg-teal-100 flex items-center justify-center text-teal-700 font-semibold text-xs shrink-0">
                  {p.name.split(' ').map((n) => n[0]).join('').slice(0, 2)}
                </div>
                <span className="text-sm font-medium text-navy-800 truncate">{p.name}</span>
              </button>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
