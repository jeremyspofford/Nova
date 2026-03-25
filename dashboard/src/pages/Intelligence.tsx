import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Lightbulb, Rss } from 'lucide-react'
import { getIntelRecommendations, getIntelStats, updateRecommendation } from '../api'
import type { IntelRecommendation } from '../api'
import { PageHeader } from '../components/layout/PageHeader'
import { Card, Metric, Tabs, Button, EmptyState, Skeleton } from '../components/ui'
import { RecommendationCard } from '../components/intel/RecommendationCard'

type StatusFilter = 'pending' | 'approved' | 'deferred' | 'implemented' | 'all'

const STATUS_TABS: { id: StatusFilter; label: string }[] = [
  { id: 'pending', label: 'Pending' },
  { id: 'approved', label: 'Approved' },
  { id: 'deferred', label: 'Deferred' },
  { id: 'implemented', label: 'Implemented' },
  { id: 'all', label: 'All' },
]

const HELP_ENTRIES = [
  { term: 'Intelligence', definition: 'Automated feed scanning that discovers relevant tools, libraries, and techniques, then grades them for Nova\'s use.' },
  { term: 'Grade', definition: 'A = strong recommendation (high confidence), B = worth considering, C = low confidence or niche.' },
  { term: 'Feeds', definition: 'RSS, Hacker News, Reddit, or GitHub sources Nova monitors for new content.' },
  { term: 'Approve', definition: 'Mark a recommendation for implementation. Nova may create a goal from it.' },
  { term: 'Defer', definition: 'Postpone a recommendation for later review without dismissing it.' },
]

export function Intelligence() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('pending')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [feedManagerOpen, setFeedManagerOpen] = useState(false)
  const qc = useQueryClient()

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['intel-stats'],
    queryFn: getIntelStats,
    staleTime: 30_000,
  })

  const { data: recs = [], isLoading: recsLoading } = useQuery({
    queryKey: ['intel-recs', statusFilter],
    queryFn: () => getIntelRecommendations(
      statusFilter === 'all' ? {} : { status: statusFilter },
    ),
    staleTime: 10_000,
  })

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      updateRecommendation(id, { status }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['intel-recs'] })
      qc.invalidateQueries({ queryKey: ['intel-stats'] })
    },
  })

  const handleStatusChange = (id: string) => (status: string) => {
    statusMutation.mutate({ id, status })
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Intelligence"
        description="Feed-driven recommendations graded and queued for review"
        helpEntries={HELP_ENTRIES}
        actions={
          <Button
            variant="secondary"
            icon={<Rss size={14} />}
            onClick={() => setFeedManagerOpen(true)}
          >
            Manage Feeds
          </Button>
        }
      />

      {/* Stats bar */}
      {statsLoading ? (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <Card key={i} className="p-4">
              <Skeleton lines={2} />
            </Card>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          <Card className="p-4">
            <Metric
              label="This Week"
              value={stats?.items_this_week ?? 0}
              tooltip="New content items discovered across all feeds in the past 7 days."
            />
          </Card>
          <Card className="p-4">
            <Metric
              label="Active Feeds"
              value={stats?.active_feeds ?? 0}
              icon={<Rss size={12} />}
              tooltip="Number of feeds currently being monitored."
            />
          </Card>
          <Card className="p-4">
            <Metric
              label="Grade A"
              value={stats?.grade_a ?? 0}
              tooltip="High-confidence recommendations worth implementing."
            />
          </Card>
          <Card className="p-4">
            <Metric
              label="Grade B"
              value={stats?.grade_b ?? 0}
              tooltip="Moderate-confidence recommendations worth considering."
            />
          </Card>
          <Card className="p-4">
            <Metric
              label="Total Recs"
              value={stats?.total_recommendations ?? 0}
              tooltip="Total recommendations generated across all time."
            />
          </Card>
        </div>
      )}

      {/* Filter tabs */}
      <Tabs
        tabs={STATUS_TABS}
        activeTab={statusFilter}
        onChange={(id) => setStatusFilter(id as StatusFilter)}
      />

      {/* Recommendation list */}
      {recsLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i} className="p-4">
              <Skeleton lines={4} />
            </Card>
          ))}
        </div>
      ) : recs.length === 0 ? (
        <EmptyState
          icon={Lightbulb}
          title={statusFilter === 'all' ? 'No recommendations yet' : `No ${statusFilter} recommendations`}
          description={
            statusFilter === 'all'
              ? 'Add feeds to start discovering recommendations.'
              : 'Try selecting a different filter.'
          }
          action={
            statusFilter === 'all'
              ? { label: 'Manage Feeds', onClick: () => setFeedManagerOpen(true) }
              : undefined
          }
        />
      ) : (
        <div className="space-y-3">
          {recs.map((rec: IntelRecommendation) => (
            <RecommendationCard
              key={rec.id}
              rec={rec}
              expanded={expandedId === rec.id}
              onToggle={() => setExpandedId(prev => prev === rec.id ? null : rec.id)}
              onStatusChange={handleStatusChange(rec.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
