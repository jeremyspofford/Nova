import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Globe, Plus, Rss, Users } from 'lucide-react'
import { getKnowledgeSources, getKnowledgeStats, getIntelStats, type KnowledgeSource } from '../api'
import { PageHeader } from '../components/layout/PageHeader'
import { Card, Metric, Tabs, Button, EmptyState, Skeleton } from '../components/ui'
import { SourceCard } from '../components/sources/SourceCard'
import { AddSourceModal } from '../components/sources/AddSourceModal'
import { CredentialManager } from '../components/sources/CredentialManager'
import { FeedStatusBar } from '../components/intel/FeedStatusBar'
import { FeedManagerModal } from '../components/intel/FeedManagerModal'

type SourceTab = 'personal' | 'feeds' | 'shared'

const SOURCE_TABS: { id: SourceTab; label: string; icon: typeof Globe }[] = [
  { id: 'personal', label: 'Personal', icon: Globe },
  { id: 'feeds', label: 'Feeds', icon: Rss },
  { id: 'shared', label: 'Shared', icon: Users },
]

const HELP_ENTRIES = [
  { term: 'Personal Sources', definition: 'Websites, GitHub profiles, and docs you want Nova to learn from. Crawled automatically and stored as engram memories.' },
  { term: 'Feeds', definition: 'RSS, Hacker News, Reddit, or GitHub sources that Nova monitors for new content and grades as recommendations.' },
  { term: 'Shared Sources', definition: 'Knowledge sources visible to all users. Admin-managed.' },
  { term: 'Credentials', definition: 'API tokens and keys used to authenticate with private sources (e.g., GitHub PATs for private repos).' },
  { term: 'Crawl', definition: 'Fetches the source URL, extracts content, and decomposes it into engram memories.' },
]

export function Sources() {
  const [activeTab, setActiveTab] = useState<SourceTab>('personal')
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [feedManagerOpen, setFeedManagerOpen] = useState(false)

  // Stats queries
  const { data: knowledgeStats, isLoading: knowledgeStatsLoading } = useQuery({
    queryKey: ['knowledge-stats'],
    queryFn: getKnowledgeStats,
    staleTime: 10_000,
  })

  const { data: intelStats, isLoading: intelStatsLoading } = useQuery({
    queryKey: ['intel-stats'],
    queryFn: getIntelStats,
    staleTime: 30_000,
  })

  const statsLoading = knowledgeStatsLoading || intelStatsLoading

  const totalSources = (knowledgeStats?.total_sources ?? 0) + (intelStats?.active_feeds ?? 0)
  const activeSources = (knowledgeStats?.sources_by_status?.active ?? 0) + (intelStats?.active_feeds ?? 0)
  const totalCredentials = knowledgeStats?.total_credentials ?? 0

  return (
    <div className="space-y-6">
      <PageHeader
        title="Sources"
        description="Knowledge sources and intelligence feeds powering Nova's memory"
        helpEntries={HELP_ENTRIES}
        actions={
          activeTab === 'feeds' ? (
            <Button
              variant="secondary"
              icon={<Rss size={14} />}
              onClick={() => setFeedManagerOpen(true)}
            >
              Manage Feeds
            </Button>
          ) : (
            <Button
              variant="secondary"
              icon={<Plus size={14} />}
              onClick={() => setAddModalOpen(true)}
            >
              Add Source
            </Button>
          )
        }
      />

      {/* Stats row */}
      {statsLoading ? (
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i} className="p-4">
              <Skeleton lines={2} />
            </Card>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
          <Card className="p-4">
            <Metric
              label="Total Sources"
              value={totalSources}
              icon={<Globe size={12} />}
              tooltip="Knowledge sources plus active intel feeds."
            />
          </Card>
          <Card className="p-4">
            <Metric
              label="Active"
              value={activeSources}
              tooltip="Sources and feeds currently being monitored."
            />
          </Card>
          <Card className="p-4">
            <Metric
              label="Credentials"
              value={totalCredentials}
              tooltip="Stored authentication tokens for private sources."
            />
          </Card>
        </div>
      )}

      {/* Tabs */}
      <Tabs
        tabs={SOURCE_TABS}
        activeTab={activeTab}
        onChange={(id) => setActiveTab(id as SourceTab)}
      />

      {/* Tab content */}
      {activeTab === 'personal' && (
        <PersonalTab onAddSource={() => setAddModalOpen(true)} />
      )}
      {activeTab === 'feeds' && (
        <FeedsTab onManageFeeds={() => setFeedManagerOpen(true)} />
      )}
      {activeTab === 'shared' && (
        <SharedTab onAddSource={() => setAddModalOpen(true)} />
      )}

      {/* Credentials section */}
      <CredentialManager />

      {/* Modals */}
      <AddSourceModal
        open={addModalOpen}
        onClose={() => setAddModalOpen(false)}
        scope={activeTab === 'shared' ? 'shared' : 'personal'}
      />
      <FeedManagerModal open={feedManagerOpen} onClose={() => setFeedManagerOpen(false)} />
    </div>
  )
}

// ── Tab components ─────────────────────────────────────────────────────────────

function PersonalTab({ onAddSource }: { onAddSource: () => void }) {
  const { data: sources = [], isLoading } = useQuery({
    queryKey: ['knowledge-sources', 'personal'],
    queryFn: () => getKnowledgeSources({ scope: 'personal' }),
    staleTime: 5_000,
  })

  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Card key={i} className="p-4">
            <Skeleton lines={3} />
          </Card>
        ))}
      </div>
    )
  }

  if (sources.length === 0) {
    return (
      <EmptyState
        icon={Globe}
        title="No personal sources yet"
        description="Add a website, GitHub profile, or documentation URL to start building Nova's knowledge."
        action={{ label: 'Add Source', onClick: onAddSource }}
      />
    )
  }

  return (
    <div className="space-y-3">
      {sources.map((source: KnowledgeSource) => (
        <SourceCard key={source.id} source={source} />
      ))}
    </div>
  )
}

function FeedsTab({ onManageFeeds }: { onManageFeeds: () => void }) {
  return (
    <div className="space-y-4">
      <FeedStatusBar onManageFeeds={onManageFeeds} />
    </div>
  )
}

function SharedTab({ onAddSource }: { onAddSource: () => void }) {
  const { data: sources = [], isLoading } = useQuery({
    queryKey: ['knowledge-sources', 'shared'],
    queryFn: () => getKnowledgeSources({ scope: 'shared' }),
    staleTime: 5_000,
  })

  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Card key={i} className="p-4">
            <Skeleton lines={3} />
          </Card>
        ))}
      </div>
    )
  }

  if (sources.length === 0) {
    return (
      <EmptyState
        icon={Users}
        title="No shared sources yet"
        description="Add sources visible to all users. Useful for team documentation and shared knowledge bases."
        action={{ label: 'Add Shared Source', onClick: onAddSource }}
      />
    )
  }

  return (
    <div className="space-y-3">
      {sources.map((source: KnowledgeSource) => (
        <SourceCard key={source.id} source={source} />
      ))}
    </div>
  )
}
