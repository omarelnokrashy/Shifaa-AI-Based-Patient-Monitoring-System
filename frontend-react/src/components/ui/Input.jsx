import { clsx } from 'clsx'

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
