import { useState, useRef, useEffect, useCallback } from 'react'
import { ChevronDown, Check } from 'lucide-react'
import clsx from 'clsx'

type ModelItem = {
  id: string
  provider?: string
}

type ModelPickerProps = {
  value: string
  onChange: (value: string) => void
  models: ModelItem[]
  showAuto?: boolean
  className?: string
}

export function ModelPicker({
  value,
  onChange,
  models,
  showAuto = false,
  className,
}: ModelPickerProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const handleClickOutside = useCallback((e: MouseEvent) => {
    if (ref.current && !ref.current.contains(e.target as Node)) {
      setOpen(false)
    }
  }, [])

  useEffect(() => {
    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [open, handleClickOutside])

  const selected = value || (showAuto ? 'auto' : '')
  const displayLabel =
    value === 'auto' || (!value && showAuto)
      ? 'Auto'
      : models.find((m) => m.id === value)?.id || value || 'Select model...'

  const handleSelect = (id: string) => {
    onChange(id)
    setOpen(false)
  }

  return (
    <div ref={ref} className={clsx('relative', className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={clsx(
          'flex items-center justify-between gap-2 w-full h-9 rounded-sm border border-border bg-surface-input px-3',
          'text-compact text-content-primary',
          'outline-none transition-colors duration-fast',
          'focus:border-border-focus focus:ring-2 focus:ring-accent-500/40',
          'hover:bg-surface-card-hover',
        )}
      >
        <span className="truncate">{displayLabel}</span>
        <ChevronDown
          className={clsx(
            'w-3.5 h-3.5 text-content-tertiary shrink-0 transition-transform duration-fast',
            open && 'rotate-180',
          )}
        />
      </button>

      {open && (
        <div className="absolute top-full mt-1 left-0 right-0 z-40 bg-surface-card border border-border rounded-lg shadow-lg py-1 max-h-60 overflow-y-auto animate-fade-in">
          {showAuto && (
            <button
              type="button"
              onClick={() => handleSelect('auto')}
              className={clsx(
                'flex items-center justify-between w-full px-3 py-1.5 text-compact text-left hover:bg-surface-card-hover transition-colors duration-fast',
                (selected === 'auto' || (!value && showAuto)) && 'text-accent',
              )}
            >
              <span>Auto</span>
              {(selected === 'auto' || (!value && showAuto)) && (
                <Check className="w-3.5 h-3.5" />
              )}
            </button>
          )}
          {models.map((model) => (
            <button
              key={model.id}
              type="button"
              onClick={() => handleSelect(model.id)}
              className={clsx(
                'flex items-center justify-between w-full px-3 py-1.5 text-compact text-left hover:bg-surface-card-hover transition-colors duration-fast',
                value === model.id && 'text-accent',
              )}
            >
              <div className="flex items-center gap-2 truncate">
                <span className="truncate">{model.id}</span>
                {model.provider && (
                  <span className="text-micro text-content-tertiary shrink-0">
                    {model.provider}
                  </span>
                )}
              </div>
              {value === model.id && <Check className="w-3.5 h-3.5 shrink-0" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
