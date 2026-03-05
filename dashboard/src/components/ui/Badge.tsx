import clsx from 'clsx'

const COLORS: Record<string, string> = {
  neutral:  'bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-400',
  accent:   'bg-accent-50 dark:bg-accent-900/30 text-accent-700 dark:text-accent-400',
  emerald:  'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400',
  amber:    'bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400',
  red:      'bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400',
  sky:      'bg-sky-100 dark:bg-sky-900/30 text-sky-700 dark:text-sky-400',
  violet:   'bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-400',
  blue:     'bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
  purple:   'bg-purple-50 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400',
}

export function Badge({
  color = 'neutral',
  className,
  children,
}: {
  color?: keyof typeof COLORS | (string & {})
  className?: string
  children: React.ReactNode
}) {
  const colorCls = COLORS[color] ?? color
  return (
    <span className={clsx('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium', colorCls, className)}>
      {children}
    </span>
  )
}
