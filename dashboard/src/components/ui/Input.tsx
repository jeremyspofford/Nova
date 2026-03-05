import { forwardRef } from 'react'
import clsx from 'clsx'

const BASE =
  'w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-100 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 outline-none placeholder:text-neutral-400 dark:placeholder:text-neutral-500 focus:border-accent-600'

type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  multiline?: false
}

type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
  multiline: true
}

type Props = InputProps | TextareaProps

export const Input = forwardRef<HTMLInputElement | HTMLTextAreaElement, Props>(
  ({ className, multiline, ...rest }, ref) => {
    const cls = clsx(BASE, multiline && 'resize-y', className)
    if (multiline) {
      return <textarea ref={ref as React.Ref<HTMLTextAreaElement>} className={cls} {...(rest as React.TextareaHTMLAttributes<HTMLTextAreaElement>)} />
    }
    return <input ref={ref as React.Ref<HTMLInputElement>} className={cls} {...(rest as React.InputHTMLAttributes<HTMLInputElement>)} />
  }
)
Input.displayName = 'Input'
