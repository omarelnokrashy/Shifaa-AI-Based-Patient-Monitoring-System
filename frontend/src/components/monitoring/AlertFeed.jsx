import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { formatDistanceToNow, parseUTCDate } from '../utils/time'
import { SeverityBadge, AlertTypeBadge } from '../ui/Badge'
import { CheckCheck, ExternalLink, Trash2 } from 'lucide-react'
import { clsx } from 'clsx'
import useAuthStore from '../../store/authStore'
import { apiAcknowledgeAlert, apiCancelAlert } from '../../api/client'
import useAlertsStore from '../../store/alertsStore'

/**
 * Displays a sorted, clickable list of patient alerts.
 * Unacknowledged alerts pulse and are accented with a severity-coloured left border.
 * Renders a friendly empty state when no alerts are present.
 *
 * @param {Object}   props
 * @param {Array}    [props.alerts=[]]        Array of alert objects to display.
 * @param {string}   [props.mode='active']    Mode of display: 'active' or 'history'.
 * @param {number|string} [props.highlightId] ID of the alert to highlight and scroll to.
 * @param {Function} [props.onAcknowledge]    Optional callback fired after an alert is acknowledged,
 *                                            receiving `(alertId: number)` as argument.
 * @returns {JSX.Element}
 */
export default function AlertFeed({ alerts = [], mode = 'active', highlightId, onAcknowledge }) {
  const navigate = useNavigate()
  const user     = useAuthStore((s) => s.user)
  const ackStore = useAlertsStore((s) => s.acknowledge)

  // Scroll highlight element into view when active
  useEffect(() => {
    if (highlightId) {
      const el = document.getElementById(`alert-card-${highlightId}`)
      if (el) {
        setTimeout(() => {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }, 300)
      }
    }
  }, [highlightId, alerts])

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
    window.location.reload()
  }

  /**
   * Cancels/deletes an active alert via the API.
   *
   * @param {React.MouseEvent} e      - The click event from the cancel button.
   * @param {Object}           alert  - The alert object to cancel.
   * @returns {Promise<void>}
   */
  const handleCancel = async (e, alert) => {
    e.stopPropagation()
    await apiCancelAlert(alert.id)
    useAlertsStore.getState().removeAlert(alert.id)
    window.location.reload()
  }

  /**
   * Navigates to the patient detail page for the given alert.
   * Builds the route prefix from the current user's role (`/doctor` or `/nurse`).
   * Passes the highlightAlert parameter in the query string.
   *
   * @param {Object} alert - The alert object whose `patient_id` is used for navigation.
   * @returns {void}
   */
  const goToPatient = (alert) => {
    const prefix = user?.role === 'nurse' ? '/nurse' : '/doctor'
    navigate(`${prefix}/patients/${alert.patient_id}?highlightAlert=${alert.id}`)
  }

  const handleExport = (e, alert) => {
    e.stopPropagation()
    goToPatient(alert)
  }

  if (!alerts.length) {
    return (
      <div className="text-center py-8 text-navy-400">
        <CheckCheck size={28} className="mx-auto mb-2 text-green-400" />
        <p className="text-sm font-medium text-green-600">No alerts found</p>
        <p className="text-xs text-navy-400 mt-0.5">All clear</p>
      </div>
    )
  }

  const isHighlighted = (alert) => Number(alert.id) === Number(highlightId)
  const showSeverityAccent = (alert) => mode !== 'history' && !isHighlighted(alert) && !alert.acknowledged

  return (
    <div className="space-y-2">
      {alerts.map((alert) => (
        <div
          id={`alert-card-${alert.id}`}
          key={alert.id}
          onClick={() => goToPatient(alert)}
          aria-current={isHighlighted(alert) ? 'true' : undefined}
          className={clsx(
            'flex items-start gap-3 p-3 rounded-xl border cursor-pointer',
            'transition-all duration-150 hover:shadow-md hover:-translate-y-0.5',
            isHighlighted(alert)
              ? 'bg-amber-50 border-amber-400 ring-2 ring-amber-300 shadow-sm'
              : alert.acknowledged && mode !== 'history'
              ? 'bg-white border-navy-100 opacity-60'
              : showSeverityAccent(alert)
              ? 'bg-white border-l-4'
              : 'bg-white border-navy-100',
            showSeverityAccent(alert) && alert.severity === 'critical' && 'border-l-red-500',
            showSeverityAccent(alert) && alert.severity === 'high'     && 'border-l-orange-500',
            showSeverityAccent(alert) && alert.severity === 'medium'   && 'border-l-amber-500',
            showSeverityAccent(alert) && alert.severity === 'low'      && 'border-l-blue-500',
          )}
        >
          {/* Pulse indicator (only active unacknowledged) */}
          {mode !== 'history' && !alert.acknowledged && !isHighlighted(alert) && (
            <span className="mt-1.5 shrink-0 w-2 h-2 rounded-full bg-red-500 animate-pulse-slow" />
          )}

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <AlertTypeBadge alertType={alert.alert_type} />
              <SeverityBadge severity={alert.severity} />
              {alert.acknowledged && (
                <span className="text-xs text-green-600 font-medium flex items-center gap-1">
                  <CheckCheck size={11} /> Acknowledged {alert.acknowledged_by ? `by ${alert.acknowledged_by}` : ''}
                </span>
              )}
              {isHighlighted(alert) && (
                <span className="text-xs text-amber-600 font-semibold px-1.5 py-0.5 rounded bg-amber-100">
                  Targeted Alert
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
            {alert.acknowledged && alert.acknowledged_at && (
              <p className="text-[10px] text-navy-400 mt-0.5">
                Acknowledged at: {parseUTCDate(alert.acknowledged_at)?.toLocaleString()}
              </p>
            )}
          </div>

          {mode !== 'history' && (
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
              {!alert.acknowledged && (
                <button
                  onClick={(e) => handleCancel(e, alert)}
                  title="Cancel"
                  className="p-1.5 rounded-lg hover:bg-red-50 text-navy-400 hover:text-red-600 transition-colors"
                >
                  <Trash2 size={15} />
                </button>
              )}
              <button
                onClick={(e) => handleExport(e, alert)}
                title="Export"
                className="p-1.5 rounded-lg hover:bg-blue-50 text-navy-400 hover:text-blue-600 transition-colors"
              >
                <ExternalLink size={15} />
              </button>
            </div>
          )}
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
