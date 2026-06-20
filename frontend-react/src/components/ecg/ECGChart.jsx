/**
 * ECGChart — renders a subset of leads from a 12-lead ECG waveform.
 *
 * Uses Recharts LineChart with multiple data keys (one per lead).
 * The chart is intentionally styled with minimal chrome — no legend clutter —
 * because clinicians read waveform morphology, not data points.
 *
 * Props:
 *   data        : array from generateMockECG() — each item is { t, I, II, V1, V5 }
 *   leads       : array of lead names to show, default ["II", "V1", "V5"]
 *   height      : chart height in px
 *   result      : ArrhythmiaResult object (optional) — shown as annotation
 */
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  ResponsiveContainer, Tooltip, ReferenceLine,
} from 'recharts'
import { clsx } from 'clsx'
import { SeverityBadge } from '../ui/Badge'

const LEAD_COLORS = {
  I:   '#0d7377',  // teal-600
  II:  '#0a5a5d',  // teal-700
  V1:  '#627d98',  // navy-500
  V5:  '#334e68',  // navy-700
  aVF: '#82a9c8',
}

const SUBTYPE_META = {
  AF:    { label: 'Atrial Fibrillation',       color: '#dc2626' },
  IAVB:  { label: '1st Deg. AV Block',         color: '#ea580c' },
  SB:    { label: 'Sinus Bradycardia',          color: '#d97706' },
  STach: { label: 'Sinus Tachycardia',          color: '#d97706' },
  null:  { label: 'Normal Sinus Rhythm',        color: '#16a34a' },
}

export default function ECGChart({
  data = [],
  leads = ['II', 'V1', 'V5'],
  height = 220,
  result = null,
}) {
  return (
    <div className="space-y-3">
      {/* Result annotation card */}
      {result && (
        <ArrhythmiaResultCard result={result} />
      )}

      {/* Lead selector labels */}
      <div className="flex items-center gap-3 flex-wrap">
        {leads.map((lead) => (
          <span key={lead} className="flex items-center gap-1.5 text-xs font-medium text-navy-600">
            <span className="w-5 h-0.5 rounded" style={{ backgroundColor: LEAD_COLORS[lead] || '#627d98' }} />
            Lead {lead}
          </span>
        ))}
      </div>

      {/* Waveform chart */}
      <div className="bg-navy-950 rounded-xl p-4">
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: -24 }}>
            <CartesianGrid strokeDasharray="2 4" stroke="#1e3a5a" strokeOpacity={0.5} />
            <XAxis dataKey="t" hide />
            <YAxis domain={['auto', 'auto']} tickCount={5} tick={{ fill: '#627d98', fontSize: 10 }} />
            <Tooltip
              contentStyle={{ background: '#102a43', border: 'none', borderRadius: 8, fontSize: 11 }}
              labelStyle={{ color: '#9fb3c8' }}
              itemStyle={{ color: '#e2e8f0' }}
              formatter={(v, name) => [v.toFixed(3), `Lead ${name}`]}
            />
            {leads.map((lead) => (
              <Line
                key={lead}
                type="monotone"
                dataKey={lead}
                stroke={LEAD_COLORS[lead] || '#627d98'}
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

/**
 * Displays an annotation card summarising the two-stage arrhythmia classification result.
 * Renders a green card for normal sinus rhythm and a red card when an abnormality is detected.
 * Shows stage-1 classification, confidence percentage, and (when abnormal) the stage-2 subtype
 * with its label (e.g. "Atrial Fibrillation") and confidence.
 *
 * @param {Object}      props
 * @param {Object|null} props.result                  The arrhythmia result object; returns null when falsy.
 * @param {string}      props.result.stage1            Stage-1 label: `'Normal'` or `'Abnormal'`.
 * @param {number}      props.result.stage1_confidence Stage-1 classifier confidence (0–1).
 * @param {string|null} [props.result.stage2_class]   Stage-2 subtype code (e.g. `'AF'`, `'SB'`) or null.
 * @param {number}      [props.result.stage2_confidence] Stage-2 classifier confidence (0–1).
 * @returns {JSX.Element|null}
 */
export function ArrhythmiaResultCard({ result }) {
  if (!result) return null
  const isAbnormal = result.stage1 === 'Abnormal'
  const meta = SUBTYPE_META[result.stage2_class] || SUBTYPE_META[null]
  const severity = isAbnormal ? (result.stage2_class === 'AF' ? 'high' : 'medium') : 'ok'

  return (
    <div
      className={clsx(
        'rounded-xl border p-4 flex items-center gap-4',
        isAbnormal ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200',
      )}
    >
      {/* Color swatch */}
      <div
        className="w-1 self-stretch rounded-full shrink-0"
        style={{ backgroundColor: meta.color }}
      />

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-heading font-bold text-sm text-navy-900">
            {isAbnormal ? `Arrhythmia Detected` : 'Normal Sinus Rhythm'}
          </span>
          <SeverityBadge severity={severity} />
        </div>
        {isAbnormal && (
          <p className="text-sm font-medium mt-1" style={{ color: meta.color }}>
            {meta.label}
          </p>
        )}
        <div className="flex items-center gap-4 mt-2 text-xs text-navy-500 flex-wrap">
          <span>Stage 1: <strong className="text-navy-800">{result.stage1}</strong></span>
          <span>Confidence: <strong className="text-navy-800">{(result.stage1_confidence * 100).toFixed(1)}%</strong></span>
          {result.stage2_class && (
            <span>Subtype: <strong className="text-navy-800">{result.stage2_class} ({(result.stage2_confidence * 100).toFixed(1)}%)</strong></span>
          )}
        </div>
      </div>
    </div>
  )
}
