import { useState, useRef, useCallback } from 'react'
import clsx from 'clsx'

type TooltipSide = 'top' | 'bottom' | 'left' | 'right'

type TooltipProps = {
  content: string
  side?: TooltipSide
  children: React.ReactNode
}

const POSITIONS: Record<TooltipSide, string> = {
  top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
  bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
  left: 'right-full top-1/2 -translate-y-1/2 mr-2',
  right: 'left-full top-1/2 -translate-y-1/2 ml-2',
}

const ARROWS: Record<TooltipSide, string> = {
  top: 'top-full left-1/2 -translate-x-1/2 border-t-neutral-900 border-l-transparent border-r-transparent border-b-transparent',
  bottom: 'bottom-full left-1/2 -translate-x-1/2 border-b-neutral-900 border-l-transparent border-r-transparent border-t-transparent',
  left: 'left-full top-1/2 -translate-y-1/2 border-l-neutral-900 border-t-transparent border-b-transparent border-r-transparent',
  right: 'right-full top-1/2 -translate-y-1/2 border-r-neutral-900 border-t-transparent border-b-transparent border-l-transparent',
}

export function Tooltip({ content, side = 'top', children }: TooltipProps) {
  const [visible, setVisible] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const show = useCallback(() => {
    timerRef.current = setTimeout(() => setVisible(true), 300)
  }, [])

  const hide = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    setVisible(false)
  }, [])

  return (
    <span className="relative inline-flex" onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide}>
      {children}
      {visible && (
        <span
          className={clsx(
            'absolute z-50 max-w-xs whitespace-normal text-center',
            'bg-neutral-900/90 backdrop-blur-lg dark:border dark:border-white/[0.06] text-neutral-100 text-micro px-2 py-1 rounded-sm shadow-md',
            'pointer-events-none animate-fade-in',
            POSITIONS[side],
          )}
          role="tooltip"
        >
          {content}
          <span
            className={clsx('absolute border-4', ARROWS[side])}
          />
        </span>
      )}
    </span>
  )
}
