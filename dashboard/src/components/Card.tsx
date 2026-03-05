import clsx from 'clsx'

const BASE = 'rounded-xl border border-neutral-200 dark:border-neutral-800 bg-card dark:bg-neutral-900'

export default function Card({
  className,
  children,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={clsx(BASE, className)} {...rest}>
      {children}
    </div>
  )
}
