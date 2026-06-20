/**
 * A shared time utility — avoids a date-fns dependency for just one function.
 */
/**
 * Convert an ISO 8601 timestamp to a human-readable relative time string.
 *
 * @param {string|null|undefined} isoString - ISO 8601 date-time string (e.g. `"2026-06-20T14:00:00Z"`).
 * @returns {string} Relative label such as `'Just now'`, `'5 min ago'`, `'2h ago'`, or `'3d ago'`.
 *   Returns an empty string if `isoString` is falsy.
 */
export function formatDistanceToNow(isoString) {
  if (!isoString) return ''
  const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000)
  if (diff < 60)   return 'Just now'
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

/**
 * Format an ISO 8601 date string as a short, locale-aware date (en-GB).
 *
 * @param {string|null|undefined} isoString - ISO 8601 date-time string.
 * @returns {string} Formatted date such as `'20 Jun 2026'`, or `'—'` if falsy.
 */
export function formatDate(isoString) {
  if (!isoString) return '—'
  return new Date(isoString).toLocaleDateString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric'
  })
}

/**
 * Calculate a patient's age in whole years from a date-of-birth string.
 *
 * @param {string|null|undefined} dobString - ISO 8601 date-of-birth string (e.g. `"1985-03-15"`).
 * @returns {string} Age as a string such as `'41 yrs'`, or `'—'` if falsy.
 */
export function calcAge(dobString) {
  if (!dobString) return '—'
  const diff = Date.now() - new Date(dobString).getTime()
  return Math.floor(diff / (365.25 * 24 * 3600 * 1000)) + ' yrs'
}
