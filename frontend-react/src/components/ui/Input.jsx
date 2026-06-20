/**
 * @file Input.jsx
 * @description Form field components for the MedMonitor UI.
 *
 * - `Input`  — a labelled text input with optional error and hint messages.
 * - `Select` — a labelled native `<select>` with matching visual styling.
 *
 * Both components automatically derive an `id` from the label when no explicit
 * `id` prop is provided, ensuring label-input association for accessibility.
 */
import { clsx } from 'clsx'

/**
 * A styled text input field with label, error, and hint support.
 *
 * @param {Object}  props
 * @param {string}  [props.label]          Optional label text rendered above the input.
 * @param {string}  [props.error]          Validation error message; styles the input red when set.
 * @param {string}  [props.hint]           Helper text shown below the input (hidden when `error` is set).
 * @param {string}  [props.className='']   Additional Tailwind classes applied to the `<input>` element.
 * @param {string}  [props.wrapperClass=''] Additional classes applied to the outer wrapper `<div>`.
 * @param {string}  [props.id]             Explicit `id` for the input; derived from `label` if omitted.
 * @param {string}  [props.type='text']    HTML input type (e.g. `'text'`, `'password'`, `'email'`).
 * @returns {JSX.Element}
 */
export default function Input({
  label,
  error,
  hint,
  className = '',
  wrapperClass = '',
  id,
  type = 'text',
  ...props
}) {
  const inputId = id || label?.toLowerCase().replace(/\s+/g, '-')
  return (
    <div className={clsx('flex flex-col gap-1', wrapperClass)}>
      {label && (
        <label htmlFor={inputId} className="text-xs font-semibold text-navy-700 uppercase tracking-wide">
          {label}
        </label>
      )}
      <input
        id={inputId}
        type={type}
        className={clsx(
          'w-full px-3 py-2.5 text-sm bg-white border rounded-lg text-navy-900 placeholder-navy-400',
          'transition-colors duration-150',
          'focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500',
          error ? 'border-red-400 bg-red-50' : 'border-navy-200 hover:border-navy-300',
          className,
        )}
        {...props}
      />
      {error && <p className="text-xs text-red-600">{error}</p>}
      {hint && !error && <p className="text-xs text-navy-400">{hint}</p>}
    </div>
  )
}

/**
 * A styled native `<select>` element with label and error support.
 *
 * @param {Object}          props
 * @param {string}          [props.label]           Optional label text rendered above the select.
 * @param {React.ReactNode} props.children           `<option>` elements to render inside the select.
 * @param {string}          [props.error]            Validation error message; styles the border red when set.
 * @param {string}          [props.wrapperClass='']  Additional classes applied to the outer wrapper `<div>`.
 * @param {string}          [props.id]               Explicit `id`; derived from `label` if omitted.
 * @returns {JSX.Element}
 */
export function Select({ label, children, error, wrapperClass = '', id, ...props }) {
  const inputId = id || label?.toLowerCase().replace(/\s+/g, '-')
  return (
    <div className={clsx('flex flex-col gap-1', wrapperClass)}>
      {label && (
        <label htmlFor={inputId} className="text-xs font-semibold text-navy-700 uppercase tracking-wide">
          {label}
        </label>
      )}
      <select
        id={inputId}
        className={clsx(
          'w-full px-3 py-2.5 text-sm bg-white border rounded-lg text-navy-900',
          'focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500',
          error ? 'border-red-400' : 'border-navy-200 hover:border-navy-300',
        )}
        {...props}
      >
        {children}
      </select>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}
