import clsx from 'clsx'

const BASE = 'rounded-xl border border-neutral-200 dark:border-neutral-800 bg-card dark:bg-neutral-900'

export default function Card({
  className,
  glow = true,
  children,
  ...rest
}: React.HTMLAttributes<HTMLDivElement> & { glow?: boolean }) {
  return (
    <div className={clsx(BASE, glow && 'card-glow', className)} {...rest}>
      {children}
    </div>
  )
}
