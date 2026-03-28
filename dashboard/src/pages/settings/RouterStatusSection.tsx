import { useQuery } from '@tanstack/react-query'
import { Activity } from 'lucide-react'
import { apiFetch } from '../../api'
import { Section, Metric } from '../../components/ui'

interface RouterStatus {
  observation_count: number
  ready: boolean
  phase: string
  message: string
}

export function RouterStatusSection() {
  const { data: status } = useQuery<RouterStatus>({
    queryKey: ['engram-router-status'],
    queryFn: () => apiFetch('/mem/api/v1/engrams/router-status'),
  })

  return (
    <Section
      icon={Activity}
      title="Neural Router"
      description="ML re-ranker that improves memory retrieval quality. Trains automatically after 200+ observations."
    >
      <div className="flex flex-wrap gap-6">
        <Metric label="Observations" value={status?.observation_count ?? 0} />
        <Metric label="Phase" value={status?.phase ?? '—'} />
        <Metric label="Status" value={status ? (status.ready ? 'Ready' : 'Training') : '—'} />
      </div>
      {status?.message && (
        <p className="text-caption text-content-tertiary">{status.message}</p>
      )}
    </Section>
  )
}
