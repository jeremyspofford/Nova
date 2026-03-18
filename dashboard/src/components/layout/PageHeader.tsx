import type { ReactNode } from 'react'

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: string
  actions?: ReactNode
}) {
  return (
    <div className="flex items-start justify-between mb-8">
      <div>
        <h1 className="text-h1 text-content-primary">{title}</h1>
        {description && (
          <p className="text-body text-content-secondary mt-1">{description}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}
