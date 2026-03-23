/**
 * Format a date string as an absolute timestamp in the user's chosen timezone.
 * Example: "Mar 6, 2026 5:45 PM EST"
 */
export function formatAbsoluteDate(iso: string, timezone: string): string {
  const d = new Date(iso)
  return d.toLocaleString('en-US', {
    timeZone: timezone,
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  })
}

/**
 * Format the duration between two ISO timestamps as a human-readable string.
 * Example: "3m 12s", "1h 5m", "< 1s"
 */
export function formatDuration(startIso: string, endIso: string): string {
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime()
  if (ms < 1000) return '< 1s'
  const totalSec = Math.floor(ms / 1000)
  const hours = Math.floor(totalSec / 3600)
  const minutes = Math.floor((totalSec % 3600) / 60)
  const seconds = totalSec % 60
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m ${seconds}s`
  return `${seconds}s`
}
