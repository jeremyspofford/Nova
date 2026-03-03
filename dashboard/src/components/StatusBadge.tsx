import clsx from 'clsx'

type Status = 'idle' | 'running' | 'stopped'

const config: Record<Status, { label: string; dot: string; bg: string; text: string }> = {
  idle:    { label: 'idle',    dot: 'bg-emerald-400',               bg: 'bg-emerald-400/10', text: 'text-emerald-400' },
  running: { label: 'running', dot: 'bg-amber-400 animate-pulse',   bg: 'bg-amber-400/10',   text: 'text-amber-400'   },
  stopped: { label: 'stopped', dot: 'bg-gray-500',                  bg: 'bg-gray-500/10',    text: 'text-neutral-500 dark:text-neutral-400'    },
}

export function StatusBadge({ status }: { status: Status }) {
  const c = config[status] ?? config.stopped
  return (
    <span className={clsx('inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium', c.bg, c.text)}>
      <span className={clsx('h-1.5 w-1.5 rounded-full', c.dot)} />
      {c.label}
    </span>
  )
}
