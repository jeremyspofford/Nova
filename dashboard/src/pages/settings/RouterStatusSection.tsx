import { useQuery } from '@tanstack/react-query'
import { Activity } from 'lucide-react'
import { apiFetch } from '../../api'
import { Section, Metric, Skeleton } from '../../components/ui'

interface RouterStatus {
  observation_count: number
  ready: boolean
  phase: string
  message: string
}

export function RouterStatusSection() {
  const { data: status, isLoading } = useQuery<RouterStatus>({
    queryKey: ['engram-router-status'],
    queryFn: () => apiFetch('/mem/api/v1/engrams/router-status'),
  })

  return (
    <Section
      icon={Activity}
      title="Neural Router"
      description="ML re-ranker that improves memory retrieval quality. Trains automatically after 200+ observations."
    >
      {isLoading ? (
        <Skeleton lines={2} />
      ) : (
        <>
          <div className="flex flex-wrap gap-6">
            <Metric label="Observations" value={status?.observation_count ?? '...'} tooltip="Retrieval feedback samples collected for training." />
            <Metric label="Phase" value={status?.phase ?? '...'} tooltip="Current training phase of the re-ranker." />
            <Metric label="Status" value={status?.ready ? 'Ready' : 'Training'} tooltip="Whether the router is active and influencing retrieval." />
          </div>
          {status?.message && (
            <p className="text-caption text-content-tertiary mt-3">{status.message}</p>
          )}
        </>
      )}
    </Section>
  )
}
