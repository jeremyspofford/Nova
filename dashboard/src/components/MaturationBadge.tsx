import type { ReactElement } from 'react'
import clsx from 'clsx'

/**
 * Goal maturation status — populated by the Cortex maturation pipeline as
 * a goal moves from raw user request through scoping, speccing, human review,
 * building, and verification.
 */
export type MaturationStatus =
  | 'triaging'
  | 'scoping'
  | 'speccing'
  | 'review'
  | 'building'
  | 'verifying'
  | null
  | undefined

// Use semantic design tokens so the badge respects the active theme and the
// stone/teal/amber palette codified in DESIGN.md. Amber signals active
// cognition (Nova is thinking), teal signals operational/awaiting state,
// neutral signals dormant/triaging.
const STYLES: Record<NonNullable<MaturationStatus>, string> = {
  triaging:  'bg-neutral-200/60 text-content-tertiary dark:bg-neutral-700/60 dark:text-stone-400',
  scoping:   'bg-warning-dim text-amber-700 dark:text-amber-400',
  speccing:  'bg-warning-dim text-amber-700 dark:text-amber-400',
  review:    'bg-accent-dim text-accent-700 dark:text-accent-400',
  building:  'bg-warning-dim text-amber-700 dark:text-amber-400',
  verifying: 'bg-warning-dim text-amber-700 dark:text-amber-400 animate-pulse',
}

const LABELS: Record<NonNullable<MaturationStatus>, string> = {
  triaging:  'Triaging',
  scoping:   'Scoping',
  speccing:  'Speccing',
  review:    'Awaiting Review',
  building:  'Building',
  verifying: 'Verifying',
}

/**
 * Compact text badge for a goal's maturation status.
 *
 * Renders nothing when status is null/undefined so callers can include the
 * badge unconditionally for goals that have or have not entered the
 * maturation pipeline.
 */
export function MaturationBadge({
  status,
  className,
}: {
  status: MaturationStatus
  className?: string
}): ReactElement | null {
  if (!status) return null
  const style = STYLES[status as NonNullable<MaturationStatus>]
  const label = LABELS[status as NonNullable<MaturationStatus>]
  if (!style || !label) return null
  return (
    <span
      className={clsx(
        'inline-flex items-center h-5 px-1.5 rounded-xs text-micro font-medium',
        style,
        className,
      )}
    >
      {label}
    </span>
  )
}
