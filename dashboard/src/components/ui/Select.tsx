import { forwardRef } from 'react'
import clsx from 'clsx'

const BASE =
  'w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-100 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600'

export const Select = forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, children, ...rest }, ref) => (
  <select ref={ref} className={clsx(BASE, className)} {...rest}>
    {children}
  </select>
))
Select.displayName = 'Select'
