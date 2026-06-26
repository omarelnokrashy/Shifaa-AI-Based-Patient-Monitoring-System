import { clsx } from 'clsx'
import {
  AlertTriangle, AlertCircle, Info, CheckCircle2,
  Heart, Activity, PersonStanding,
} from 'lucide-react'

const SEVERITY_CONFIG = {
  critical: { label: 'Critical', cls: 'severity-critical', Icon: AlertTriangle },
  high:     { label: 'High',     cls: 'severity-high',     Icon: AlertCircle },
  medium:   { label: 'Medium',   cls: 'severity-medium',   Icon: AlertCircle },
  low:      { label: 'Low',      cls: 'severity-low',      Icon: Info },
  ok:       { label: 'OK',       cls: 'severity-ok',       Icon: CheckCircle2 },
}

const ALERT_TYPE_ICON = {
  arrhythmia: Heart,
  fall:        PersonStanding,
  seizure:     Activity,
}

/** Severity badge: shows icon + label, color-paired — never relies on color alone. */
export function SeverityBadge({ severity = 'medium', className = '' }) {
  const config = SEVERITY_CONFIG[severity] || SEVERITY_CONFIG.medium
  const { label, cls, Icon } = config
  return (
    <span className={clsx('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold border', cls, className)}>
      <Icon size={11} />
      {label}
    </span>
  )
}

/** Alert type badge: arrhythmia / fall / seizure. */
export function AlertTypeBadge({ alertType = 'arrhythmia', className = '' }) {
  const Icon = ALERT_TYPE_ICON[alertType] || AlertCircle
  const labels = { arrhythmia: 'ECG', fall: 'Fall', seizure: 'Seizure' }
  return (
    <span className={clsx('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-navy-100 text-navy-700 border border-navy-200', className)}>
      <Icon size={11} />
      {labels[alertType] || alertType}
    </span>
  )
}

/** Generic status badge */
export function StatusBadge({ status, className = '' }) {
  const map = {
    SEIZURE:       'bg-red-100 text-red-700 border-red-200',
    NORMAL:        'bg-green-100 text-green-700 border-green-200',
    INITIALISING:  'bg-amber-100 text-amber-700 border-amber-200',
    ok:            'bg-green-100 text-green-700 border-green-200',
    unreachable:   'bg-red-100 text-red-700 border-red-200',
    active:        'bg-teal-100 text-teal-700 border-teal-200',
    inactive:      'bg-navy-100 text-navy-500 border-navy-200',
  }
  return (
    <span className={clsx('inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border', map[status] || map.active, className)}>
      {status}
    </span>
  )
}
