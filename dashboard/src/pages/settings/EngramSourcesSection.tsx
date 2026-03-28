import { useQuery } from '@tanstack/react-query'
import { Database } from 'lucide-react'
import { apiFetch } from '../../api'
import { Section, EmptyState, Skeleton } from '../../components/ui'

interface EngramSource {
  id: string
  title: string | null
  source_kind: string
  engram_count: number
  summary: string | null
  trust_score: number
  stale: boolean
  completeness: string
  coverage_notes: string | null
  uri: string | null
}

export function EngramSourcesSection() {
  const { data: sources = [], isLoading } = useQuery<EngramSource[]>({
    queryKey: ['engram-sources'],
    queryFn: () => apiFetch('/mem/api/v1/engrams/sources'),
  })

  return (
    <Section icon={Database} title="Engram Sources" description="Tracked origins of ingested content — conversations, feeds, crawled pages, and documents that Nova has processed into memories.">
      {isLoading ? (
        <Skeleton lines={5} />
      ) : (
        <div className="space-y-3">
          {sources.length === 0 ? (
            <EmptyState
              icon={Database}
              title="No sources yet"
              description="Sources are created when content is ingested through conversations, feeds, or crawls."
            />
          ) : (
            sources.map((s) => (
              <div key={s.id} className="bg-surface-elevated rounded-lg p-3">
                <div className="flex justify-between items-start">
                  <div>
                    <span className="text-sm font-medium text-content-primary">{s.title || 'Untitled'}</span>
                    <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-surface-card text-content-tertiary">
                      {s.source_kind}
                    </span>
                  </div>
                  <span className="text-xs text-content-quaternary">{s.engram_count} engrams</span>
                </div>
                {s.summary && <p className="text-xs text-content-tertiary mt-1 line-clamp-2">{s.summary}</p>}
                <div className="flex gap-3 mt-2 text-xs text-content-quaternary">
                  <span>Trust: {(s.trust_score * 100).toFixed(0)}%</span>
                  {s.stale && <span className="text-warning">stale</span>}
                  {s.completeness !== 'complete' && (
                    <span className="text-warning">{s.completeness}: {s.coverage_notes}</span>
                  )}
                  {s.uri && <a href={s.uri} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline truncate max-w-[200px]">{s.uri}</a>}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </Section>
  )
}
