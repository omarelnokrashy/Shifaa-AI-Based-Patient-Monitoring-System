/**
 * Patient Detail — tabbed view with Overview, Chat, ECG, Monitoring, Vitals tabs.
 * The heaviest page in the app; each tab is lazy-loaded via conditional rendering.
 */
import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { clsx } from 'clsx'
import {
  ArrowLeft, User, MessageSquare, HeartPulse,
  Activity, AlertCircle,
} from 'lucide-react'
import Card, { CardHeader } from '../../components/ui/Card'
import Button from '../../components/ui/Button'
import { SeverityBadge } from '../../components/ui/Badge'
import ChatPanel from '../../components/chat/ChatPanel'
import ECGChart, { ArrhythmiaResultCard } from '../../components/ecg/ECGChart'
import AlertFeed from '../../components/monitoring/AlertFeed'
import { apiGetPatient, apiGetAlerts, apiAnalyzeECG } from '../../api/client'
import { generateMockECG } from '../../mock/data'
import { calcAge, formatDate } from '../../components/utils/time'
import useAuthStore from '../../store/authStore'


const TABS = [
  { id: 'overview',    label: 'Overview',   Icon: User },
  { id: 'chat',        label: 'Chat',        Icon: MessageSquare },
  { id: 'ecg',         label: 'ECG / Arrhythmia', Icon: HeartPulse },
  { id: 'monitoring',  label: 'Monitoring',  Icon: Activity },
]

/**
 * Patient Detail page — tabbed deep-dive for a single patient.
 *
 * Loads patient data and alert history in parallel on mount. Renders a tab bar
 * (Overview, Chat, ECG, Monitoring) and conditionally shows the Chat tab only
 * for the doctor role. Nurses receive a read-only view of the same page.
 *
 * @returns {JSX.Element} The full patient detail view, or a loading/not-found state.
 */
export default function PatientDetailPage() {
  const { id }     = useParams()
  const navigate   = useNavigate()
  const [tab, setTab]         = useState('overview')
  const [patient, setPatient] = useState(null)
  const [alerts, setAlerts]   = useState([])
  const [loading, setLoading] = useState(true)
  const user                  = useAuthStore((s) => s.user)

  useEffect(() => {
    Promise.all([
      apiGetPatient(id),
      apiGetAlerts(id),
    ]).then(([p, a]) => {
      setPatient(p); setAlerts(a); setLoading(false)
    })
  }, [id])

  if (loading) return <LoadingState />
  if (!patient) return <p className="text-navy-400 p-8">Patient not found.</p>

  const availableTabs = TABS.filter(t => {
    if (t.id === 'chat' && user?.role === 'nurse') return false
    return true
  })

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => navigate(-1)} aria-label="Back">
          <ArrowLeft size={18} />
        </Button>
        <div className="flex items-center gap-3 flex-1 min-w-0">
          <div className="w-10 h-10 rounded-full bg-teal-100 flex items-center justify-center text-teal-700 font-bold shrink-0">
            {patient.name.split(' ').map((n) => n[0]).join('').slice(0, 2).toUpperCase()}
          </div>
          <div className="min-w-0">
            <h1 className="font-heading font-bold text-xl text-navy-900 truncate">{patient.name}</h1>
            <p className="text-navy-400 text-xs">
              {calcAge(patient.dob)} · {patient.gender} · {patient.blood_type || 'Blood type unknown'}
              {patient.allergies?.length > 0 && (
                <span className="ml-2 text-red-600 font-semibold">⚠ {patient.allergies[0].allergen} allergy</span>
              )}
            </p>
          </div>
        </div>
        {alerts.filter((a) => !a.acknowledged).length > 0 && (
          <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs font-semibold animate-pulse-slow">
            <AlertCircle size={13} />
            {alerts.filter((a) => !a.acknowledged).length} active alert{alerts.length > 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 bg-white border border-navy-100 rounded-xl p-1 w-fit">
        {availableTabs.map(({ id: tid, label, Icon }) => (
          <button
            key={tid}
            onClick={() => setTab(tid)}
            className={clsx(
              'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
              tab === tid
                ? 'bg-navy-900 text-white shadow-sm'
                : 'text-navy-500 hover:text-navy-800 hover:bg-navy-50',
            )}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'overview'   && <OverviewTab patient={patient} />}
      {tab === 'chat'       && user?.role !== 'nurse' && (
        <div className="h-[600px]">
          <ChatPanel patient={patient} />
        </div>
      )}
      {tab === 'ecg'        && <ECGTab patient={patient} />}
      {tab === 'monitoring' && <MonitoringTab patient={patient} alerts={alerts} />}
    </div>
  )
}

// ── Overview tab ────────────────────────────────────────────────────────────────
/**
 * Renders a 2-column card grid with the patient's active diagnoses,
 * current medications, recent lab results (highlighting abnormal values),
 * and known allergies.
 *
 * @param {object} props
 * @param {object} props.patient - Full patient object from the API.
 * @returns {JSX.Element}
 */
function OverviewTab({ patient }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {/* Diagnoses */}
      <Card>
        <CardHeader title="Active Diagnoses" icon={AlertCircle} />
        {patient.diagnoses?.filter((d) => d.is_active).length === 0
          ? <EmptyState text="No active diagnoses" />
          : (
            <div className="space-y-2">
              {patient.diagnoses
                .filter((d) => d.is_active)
                .sort((a, b) => b.diagnosed_on.localeCompare(a.diagnosed_on))
                .map((d) => (
                <div key={d.id} className="flex items-start justify-between gap-3 py-2 border-b border-navy-50 last:border-0">
                  <div>
                    <p className="text-sm font-medium text-navy-800">{d.description}</p>
                    <p className="text-xs text-navy-400">{d.icd10_code} · Since {formatDate(d.diagnosed_on)}</p>
                  </div>
                  <SeverityBadge severity={d.severity === 'severe' ? 'high' : d.severity === 'moderate' ? 'medium' : 'low'} />
                </div>
              ))}
            </div>
          )
        }
      </Card>

      {/* Medications */}
      <Card>
        <CardHeader title="Current Medications" />
        {patient.medications?.filter((m) => m.is_active).length === 0
          ? <EmptyState text="No active medications" />
          : (
            <div className="space-y-2">
              {patient.medications.filter((m) => m.is_active).map((m) => (
                <div key={m.id} className="py-2 border-b border-navy-50 last:border-0">
                  <p className="text-sm font-medium text-navy-800">{m.drug_name}</p>
                  <p className="text-xs text-navy-400">{m.dose}</p>
                </div>
              ))}
            </div>
          )
        }
      </Card>

      {/* Lab results */}
      <Card>
        <CardHeader title="Recent Lab Results" />
        {patient.lab_results?.length === 0
          ? <EmptyState text="No lab results" />
          : (
            <table className="w-full text-sm">
              <thead><tr>{['Test', 'Value', 'Ref', ''].map((h) => <th key={h} className="text-left text-xs font-semibold text-navy-400 uppercase pb-2 pr-3">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-navy-50">
                {patient.lab_results.map((l) => (
                  <tr key={l.id}>
                    <td className="py-2 pr-3 text-navy-700 font-medium">{l.test_name}</td>
                    <td className={clsx('py-2 pr-3 font-mono', l.is_abnormal ? 'text-red-600 font-bold' : 'text-navy-700')}>
                      {l.value} {l.unit}
                    </td>
                    <td className="py-2 pr-3 text-navy-400 text-xs">{l.reference}</td>
                    <td className="py-2">{l.is_abnormal && <span className="text-red-500 text-xs font-semibold">↑</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
      </Card>

      {/* Allergies */}
      <Card>
        <CardHeader title="Allergies" />
        {patient.allergies?.length === 0
          ? <EmptyState text="No known allergies" />
          : (
            <div className="space-y-2">
              {patient.allergies.map((a) => (
                <div key={a.id} className="flex items-center justify-between py-2 border-b border-navy-50 last:border-0">
                  <div>
                    <p className="text-sm font-semibold text-red-700">{a.allergen}</p>
                    <p className="text-xs text-navy-400">{a.reaction}</p>
                  </div>
                  <SeverityBadge severity={a.severity === 'severe' ? 'critical' : a.severity === 'moderate' ? 'medium' : 'low'} />
                </div>
              ))}
            </div>
          )
        }
      </Card>
    </div>
  )
}

// ── ECG tab ───────────────────────────────────────────────────────────────────
/**
 * Renders the ECG waveform chart for the patient together with an
 * "Run AI Analysis" button that triggers arrhythmia detection.
 *
 * @param {object} props
 * @param {object} props.patient - Patient object; `patient.id` is sent to the ECG API.
 * @returns {JSX.Element}
 */
function ECGTab({ patient }) {
  const [ecgData,  setEcgData]  = useState(generateMockECG())
  const [result,   setResult]   = useState(null)
  const [running,  setRunning]  = useState(false)

  /**
   * Sends a 12-lead ECG signal array to the arrhythmia analysis API and
   * stores the classification result in component state.
   *
   * In production the real signal data would come from `patient.ecg_file`;
   * for now a random signal is generated as a placeholder.
   *
   * @async
   * @returns {Promise<void>}
   */
  const runAnalysis = async () => {
    setRunning(true)
    setResult(null)
    // In real: send patient.ecg_file → signal array
    const signal = Array.from({ length: 5000 }, () => Array.from({ length: 12 }, () => Math.random() * 2 - 1))
    const r = await apiAnalyzeECG(patient.id, signal)
    setResult(r)
    setRunning(false)
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="12-Lead ECG Waveform"
          subtitle="Representative leads II, V1, V5"
          action={
            <Button onClick={runAnalysis} loading={running} size="sm">
              <HeartPulse size={14} /> {running ? 'Analyzing…' : 'Run AI Analysis'}
            </Button>
          }
        />
        <ECGChart data={ecgData} result={result} />
      </Card>
    </div>
  )
}

// ── Monitoring tab ────────────────────────────────────────────────────────────
/**
 * Renders the full alert history for the patient inside a labelled card.
 *
 * @param {object}   props
 * @param {object}   props.patient - Patient object (used for the card subtitle).
 * @param {object[]} props.alerts  - Array of alert objects to display in the feed.
 * @returns {JSX.Element}
 */
function MonitoringTab({ patient, alerts }) {
  return (
    <Card>
      <CardHeader title="Monitoring History" subtitle={`Alerts for ${patient.name}`} icon={Activity} />
      <AlertFeed alerts={alerts} />
    </Card>
  )
}

/**
 * Generic empty-state message used inside tab cards when a list has no items.
 *
 * @param {object} props
 * @param {string} props.text - The message to display.
 * @returns {JSX.Element}
 */
function EmptyState({ text }) {
  return <p className="text-navy-400 text-sm py-2">{text}</p>
}

/**
 * Full-page animated skeleton shown while the patient data is loading.
 *
 * @returns {JSX.Element}
 */
function LoadingState() {
  return (
    <div className="space-y-4 max-w-6xl mx-auto animate-pulse">
      <div className="h-12 bg-navy-100 rounded-xl" />
      <div className="h-10 w-80 bg-navy-100 rounded-xl" />
      <div className="grid grid-cols-2 gap-4">
        {[1, 2, 3, 4].map((i) => <div key={i} className="h-48 bg-navy-100 rounded-xl" />)}
      </div>
    </div>
  )
}

