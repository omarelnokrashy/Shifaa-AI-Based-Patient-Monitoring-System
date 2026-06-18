/**
 * A shared time utility — avoids a date-fns dependency for just one function.
 */
export function formatDistanceToNow(isoString) {
  if (!isoString) return ''
  const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000)
  if (diff < 60)   return 'Just now'
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export function formatDate(isoString) {
  if (!isoString) return '—'
  return new Date(isoString).toLocaleDateString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric'
  })
}

export function calcAge(dobString) {
  if (!dobString) return '—'
  const diff = Date.now() - new Date(dobString).getTime()
  return Math.floor(diff / (365.25 * 24 * 3600 * 1000)) + ' yrs'
}
