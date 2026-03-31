import { useState, useRef, useEffect, useCallback, useMemo, Fragment } from 'react'
import { ChevronDown, Check } from 'lucide-react'
import clsx from 'clsx'

type ModelItem = {
  id: string
  provider?: string
}

type ModelGroup = {
  provider: string
  models: ModelItem[]
}

type ModelPickerProps = {
  value: string
  onChange: (value: string) => void
  models: ModelItem[]
  showAuto?: boolean
  className?: string
  buttonClassName?: string
}

export function ModelPicker({
  value,
  onChange,
  models,
  showAuto = false,
  className,
  buttonClassName,
}: ModelPickerProps) {
  const [open, setOpen] = useState(false)
  const [flipUp, setFlipUp] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const groups = useMemo<ModelGroup[]>(() => {
    const map = new Map<string, ModelItem[]>()
    for (const m of models) {
      const key = m.provider ?? ''
      const list = map.get(key)
      if (list) list.push(m)
      else map.set(key, [m])
    }
    return Array.from(map, ([provider, items]) => ({ provider, models: items }))
  }, [models])

  const hasGroups = groups.some(g => g.provider !== '')

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

  const toggleOpen = () => {
    if (!open && ref.current) {
      const rect = ref.current.getBoundingClientRect()
      const spaceBelow = window.innerHeight - rect.bottom
      setFlipUp(spaceBelow < 260)
    }
    setOpen((v) => !v)
  }

  const handleSelect = (id: string) => {
    onChange(id)
    setOpen(false)
  }

  return (
    <div ref={ref} className={clsx('relative', className)}>
      <button
        type="button"
        onClick={toggleOpen}
        className={clsx(
          buttonClassName ?? 'flex items-center justify-between gap-2 w-full h-9 rounded-sm border border-border bg-surface-input px-3 text-compact text-content-primary',
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
        <div className={clsx(
          'absolute left-0 z-40 min-w-full w-max max-w-[28rem] bg-surface-card border border-border rounded-lg shadow-lg py-1 max-h-60 overflow-y-auto animate-fade-in',
          flipUp ? 'bottom-full mb-1' : 'top-full mt-1',
        )}>
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
          {groups.map((group) => (
            <Fragment key={group.provider}>
              {hasGroups && group.provider && (
                <div className="px-3 pt-2.5 pb-1 text-micro font-semibold uppercase tracking-wide text-content-tertiary select-none">
                  {group.provider}
                </div>
              )}
              {group.models.map((model) => (
                <button
                  key={model.id}
                  type="button"
                  onClick={() => handleSelect(model.id)}
                  className={clsx(
                    'flex items-center justify-between w-full py-1.5 text-compact text-left hover:bg-surface-card-hover transition-colors duration-fast',
                    hasGroups ? 'pl-5 pr-3' : 'px-3',
                    value === model.id && 'text-accent',
                  )}
                >
                  <span className="truncate">{model.id}</span>
                  {value === model.id && <Check className="w-3.5 h-3.5 shrink-0" />}
                </button>
              ))}
            </Fragment>
          ))}
        </div>
      )}
    </div>
  )
}
