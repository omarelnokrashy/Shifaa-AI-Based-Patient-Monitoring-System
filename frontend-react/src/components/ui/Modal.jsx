import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'
import { clsx } from 'clsx'
import Button from './Button'

const sizes = {
  sm: 'max-w-md',
  md: 'max-w-xl',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
}

export default function Modal({ isOpen, onClose, title, children, size = 'md', footer }) {
  const dialogRef = useRef(null)

  // Focus trap & keyboard dismiss
  useEffect(() => {
    if (isOpen) {
      dialogRef.current?.focus()
    }
  }, [isOpen])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    if (isOpen) document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-navy-950/60 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
      />

      {/* Panel */}
      <div
        ref={dialogRef}
        tabIndex={-1}
        className={clsx(
          'relative w-full bg-white rounded-2xl shadow-modal overflow-hidden animate-slide-up',
          sizes[size],
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-navy-100">
          <h2 id="modal-title" className="font-heading font-semibold text-navy-900">
            {title}
          </h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-navy-400 hover:text-navy-700 hover:bg-navy-100 transition-colors"
            aria-label="Close modal"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 overflow-y-auto max-h-[70vh]">
          {children}
        </div>

        {/* Footer */}
        {footer && (
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-navy-100 bg-navy-50/50">
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}
