import { clsx } from 'clsx'

export default function Card({ children, className = '', padded = true, ...props }) {
  return (
    <div
      className={clsx('card animate-fade-in', padded && 'p-5', className)}
      {...props}
    >
      {children}
    </div>
  )
}

export function CardHeader({ title, subtitle, action, icon: Icon }) {
  return (
    <div className="flex items-start justify-between mb-4">
      <div className="flex items-center gap-2.5">
        {Icon && (
          <span className="p-1.5 rounded-lg bg-teal-50 text-teal-600">
            <Icon size={16} />
          </span>
        )}
        <div>
          <h3 className="font-heading font-semibold text-navy-900 text-sm leading-tight">{title}</h3>
          {subtitle && <p className="text-xs text-navy-400 mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}
