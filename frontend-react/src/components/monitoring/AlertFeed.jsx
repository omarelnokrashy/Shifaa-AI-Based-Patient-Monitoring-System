/**
 * AlertFeed — the real-time alert list for doctor/nurse dashboards.
 * Sorted by recency and severity. Unacknowledged alerts have a subtle pulse.
 * One-click navigates to the relevant patient.
 */
import { useNavigate } from 'react-router-dom'
import { formatDistanceToNow } from '../utils/time'
import { SeverityBadge, AlertTypeBadge } from '../ui/Badge'
import { CheckCheck, ExternalLink } from 'lucide-react'
import { clsx } from 'clsx'
import useAuthStore from '../../store/authStore'
import { apiAcknowledgeAlert } from '../../api/client'
import useAlertsStore from '../../store/alertsStore'

/**
 * Displays a sorted, clickable list of patient alerts.
 * Unacknowledged alerts pulse and are accented with a severity-coloured left border.
 * Renders a friendly empty state when no alerts are present.
 *
 * @param {Object}   props
 * @param {Array}    [props.alerts=[]]        Array of alert objects to display.
 * @param {Function} [props.onAcknowledge]    Optional callback fired after an alert is acknowledged,
 *                                            receiving `(alertId: number)` as argument.
 * @returns {JSX.Element}
 */
export default function AlertFeed({ alerts = [], onAcknowledge }) {
  const navigate = useNavigate()
  const user     = useAuthStore((s) => s.user)
  const ackStore = useAlertsStore((s) => s.acknowledge)

  /**
   * Acknowledges an alert via the API and updates the local store.
   * Stops click propagation so the parent `goToPatient` handler is not triggered.
   *
   * @param {React.MouseEvent} e      - The click event from the acknowledge button.
   * @param {Object}           alert  - The alert object to acknowledge.
   * @returns {Promise<void>}
   */
  const handleAck = async (e, alert) => {
    e.stopPropagation()
    await apiAcknowledgeAlert(alert.id, user?.id)
    ackStore(alert.id)
    onAcknowledge?.(alert.id)
  }

  /**
   * Navigates to the patient detail page for the given alert.
   * Builds the route prefix from the current user's role (`/doctor` or `/nurse`).
   *
   * @param {Object} alert - The alert object whose `patient_id` is used for navigation.
   * @returns {void}
   */
  const goToPatient = (alert) => {
    const prefix = user?.role === 'nurse' ? '/nurse' : '/doctor'
    navigate(`${prefix}/patients/${alert.patient_id}`)
  }

  if (!alerts.length) {
    return (
      <div className="text-center py-8 text-navy-400">
        <CheckCheck size={28} className="mx-auto mb-2 text-green-400" />
        <p className="text-sm font-medium text-green-600">No active alerts</p>
        <p className="text-xs text-navy-400 mt-0.5">All clear</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {alerts.map((alert) => (
        <div
          key={alert.id}
          onClick={() => goToPatient(alert)}
          className={clsx(
            'flex items-start gap-3 p-3 rounded-xl border cursor-pointer',
            'transition-all duration-150 hover:shadow-md hover:-translate-y-0.5',
            alert.acknowledged
              ? 'bg-white border-navy-100 opacity-60'
              : 'bg-white border-l-4',
            !alert.acknowledged && alert.severity === 'critical' && 'border-l-red-500',
            !alert.acknowledged && alert.severity === 'high'     && 'border-l-orange-500',
            !alert.acknowledged && alert.severity === 'medium'   && 'border-l-amber-500',
            !alert.acknowledged && alert.severity === 'low'      && 'border-l-blue-500',
          )}
        >
          {/* Pulse indicator (only unacknowledged) */}
          {!alert.acknowledged && (
            <span className="mt-1.5 shrink-0 w-2 h-2 rounded-full bg-red-500 animate-pulse-slow" />
          )}

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <AlertTypeBadge alertType={alert.alert_type} />
              <SeverityBadge severity={alert.severity} />
              {alert.acknowledged && (
                <span className="text-xs text-green-600 font-medium flex items-center gap-1">
                  <CheckCheck size={11} /> Acknowledged
                </span>
              )}
            </div>
            <p className="mt-1 text-sm font-semibold text-navy-900 truncate">
              {alert.patient_name || `Patient #${alert.patient_id}`}
            </p>
            <p className="text-xs text-navy-400">
              {formatDistanceToNow(alert.created_at)}
            </p>
            {alert.details && (
              <p className="text-xs text-navy-500 mt-0.5">
                {getAlertSummary(alert)}
              </p>
            )}
          </div>

          <div className="flex items-center gap-1 shrink-0">
            {!alert.acknowledged && (
              <button
                onClick={(e) => handleAck(e, alert)}
                title="Acknowledge"
                className="p-1.5 rounded-lg hover:bg-green-50 text-navy-400 hover:text-green-600 transition-colors"
              >
                <CheckCheck size={15} />
              </button>
            )}
            <ExternalLink size={13} className="text-navy-300" />
          </div>
        </div>
      ))}
    </div>
  )
}

/**
 * Derives a concise, human-readable summary string from an alert's `details` payload.
 * Returns an empty string for unknown alert types.
 *
 * @param {Object} alert              - The alert object.
 * @param {string} alert.alert_type   - Type discriminator: `'arrhythmia'`, `'fall'`, or `'seizure'`.
 * @param {Object} [alert.details]    - Type-specific detail payload.
 * @returns {string} A short summary suitable for inline display.
 */
function getAlertSummary(alert) {
  const d = alert.details || {}
  if (alert.alert_type === 'arrhythmia') {
    return d.stage2_class
      ? `${d.stage2_class} detected — ${(d.stage1_confidence * 100).toFixed(0)}% confidence`
      : 'Abnormal ECG detected'
  }
  if (alert.alert_type === 'fall') return `Fall probability: ${((d.fall_probability || 0) * 100).toFixed(0)}%`
  if (alert.alert_type === 'seizure') return `Gate score: ${(d.gate_score || 0).toFixed(2)} — ${d.status || 'SEIZURE'}`
  return ''
}
