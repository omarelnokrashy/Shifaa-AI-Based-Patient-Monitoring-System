import { clsx } from 'clsx'

const variants = {
  primary:   'bg-teal-600 text-white hover:bg-teal-700 active:bg-teal-800 shadow-sm',
  secondary: 'bg-white text-navy-700 border border-navy-200 hover:bg-navy-50 active:bg-navy-100',
  danger:    'bg-red-600 text-white hover:bg-red-700 active:bg-red-800 shadow-sm',
  ghost:     'text-navy-600 hover:bg-navy-100 active:bg-navy-200',
  nav:       'text-navy-200 hover:text-white hover:bg-navy-700 active:bg-navy-600',
}

const sizes = {
  sm:   'px-3 py-1.5 text-xs font-medium rounded-md',
  md:   'px-4 py-2 text-sm font-medium rounded-lg',
  lg:   'px-5 py-2.5 text-sm font-semibold rounded-lg',
  icon: 'p-2 rounded-lg',
}

export default function Button({
  variant = 'primary',
  size = 'md',
  className = '',
  disabled = false,
  loading = false,
  children,
  ...props
}) {
  return (
    <button
      className={clsx(
        'inline-flex items-center justify-center gap-2 transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600',
        variants[variant],
        sizes[size],
        (disabled || loading) && 'opacity-50 cursor-not-allowed pointer-events-none',
        className,
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading && (
        <svg className="animate-spin h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      )}
      {children}
    </button>
  )
}
