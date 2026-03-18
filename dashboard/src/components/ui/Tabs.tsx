import clsx from 'clsx'

type TabItem = {
  id: string
  label: string
  icon?: React.ElementType
}

type TabsProps = {
  tabs: TabItem[]
  activeTab: string
  onChange: (id: string) => void
  className?: string
}

export function Tabs({ tabs, activeTab, onChange, className }: TabsProps) {
  return (
    <div
      className={clsx(
        'flex overflow-x-auto border-b border-border-subtle',
        className,
      )}
    >
      {tabs.map((tab) => {
        const Icon = tab.icon
        const active = tab.id === activeTab
        return (
          <button
            key={tab.id}
            type="button"
            onClick={() => onChange(tab.id)}
            className={clsx(
              'px-3 py-2 text-compact font-medium whitespace-nowrap transition-colors duration-fast',
              'border-b-2 -mb-px',
              active
                ? 'text-accent border-accent'
                : 'text-content-tertiary hover:text-content-secondary border-transparent',
            )}
          >
            <span className="inline-flex items-center gap-1.5">
              {Icon && <Icon className="w-3.5 h-3.5" />}
              {tab.label}
            </span>
          </button>
        )
      })}
    </div>
  )
}
