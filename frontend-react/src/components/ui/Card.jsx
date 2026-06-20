/**
 * @file Card.jsx
 * @description Surface container components used throughout the MedMonitor UI.
 *
 * - `Card`       — a padded, rounded white card with a subtle fade-in animation.
 * - `CardHeader` — a standardised header row with optional icon, title, subtitle,
 *                  and an action slot for buttons or badges.
 */
import { clsx } from 'clsx'

/**
 * A generic surface container card.
 *
 * @param {Object}          props
 * @param {React.ReactNode} props.children        Content rendered inside the card.
 * @param {string}          [props.className='']  Additional Tailwind classes to merge.
 * @param {boolean}         [props.padded=true]   When true, applies `p-5` inner padding.
 * @returns {JSX.Element}
 */
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

/**
 * Standardised header row for a Card, providing icon, title, subtitle, and an
 * optional action slot aligned to the far right.
 *
 * @param {Object}          props
 * @param {string}          props.title          Primary heading text.
 * @param {string}          [props.subtitle]     Optional secondary descriptor shown below the title.
 * @param {React.ReactNode} [props.action]       Optional element (e.g. a Button) rendered on the right.
 * @param {React.ElementType} [props.icon]       Optional Lucide icon component rendered before the title.
 * @returns {JSX.Element}
 */
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
