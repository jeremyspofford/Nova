import clsx from 'clsx'

export function Metric({
  label,
  value,
  icon,
  change,
  className,
}: {
  label: string
  value: string | number
  icon?: React.ReactNode
  change?: { value: string; direction: 'up' | 'down' }
  className?: string
}) {
  return (
    <div className={clsx('flex flex-col gap-1', className)}>
      <span className="text-caption font-medium text-content-tertiary uppercase tracking-wider inline-flex items-center gap-1.5">
        {icon}
        {label}
      </span>
      <span className="text-display font-mono text-content-primary">{value}</span>
      {change && (
        <span
          className={clsx(
            'text-caption',
            change.direction === 'up' ? 'text-success' : 'text-danger',
          )}
        >
          {change.direction === 'up' ? '\u2191' : '\u2193'} {change.value}
        </span>
      )}
    </div>
  )
}
