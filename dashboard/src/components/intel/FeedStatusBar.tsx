import { useQuery } from '@tanstack/react-query'
import { ExternalLink, AlertCircle, CheckCircle2, Clock } from 'lucide-react'
import { getIntelFeeds, type IntelFeed } from '../../api'
import { Card } from '../ui/Card'

const TYPE_LABELS: Record<string, string> = {
  rss: 'RSS',
  reddit_json: 'Reddit',
  page: 'Page',
  github_trending: 'GitHub Trending',
  github_releases: 'GitHub Releases',
}

const TYPE_COLORS: Record<string, string> = {
  rss: 'text-blue-400',
  reddit_json: 'text-orange-400',
  page: 'text-stone-400',
  github_trending: 'text-purple-400',
  github_releases: 'text-teal-400',
}

function formatRelative(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDays = Math.floor(diffHr / 24)
  return `${diffDays}d ago`
}

function feedStatus(feed: IntelFeed): 'ok' | 'error' | 'pending' {
  if (!feed.last_checked_at) return 'pending'
  if (feed.error_count > 0) return 'error'
  return 'ok'
}

function StatusIcon({ status }: { status: 'ok' | 'error' | 'pending' }) {
  if (status === 'ok') return <CheckCircle2 size={12} className="text-success flex-shrink-0" />
  if (status === 'error') return <AlertCircle size={12} className="text-danger flex-shrink-0" />
  return <Clock size={12} className="text-content-tertiary flex-shrink-0" />
}

/** Human-readable URL for the feed source — strips protocol, long paths. */
function displayUrl(url: string): string {
  try {
    const u = new URL(url)
    const host = u.hostname.replace(/^(www|old)\./, '')
    const path = u.pathname.replace(/\/$/, '')
    if (path.length > 30) return host + path.slice(0, 28) + '...'
    return host + path
  } catch {
    return url
  }
}

interface Props {
  onManageFeeds: () => void
}

export function FeedStatusBar({ onManageFeeds }: Props) {
  const { data: feeds = [], isLoading } = useQuery({
    queryKey: ['intel-feeds'],
    queryFn: getIntelFeeds,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  if (isLoading) return null

  const enabledFeeds = feeds.filter((f: IntelFeed) => f.enabled)
  const okCount = enabledFeeds.filter((f: IntelFeed) => feedStatus(f) === 'ok').length
  const errCount = enabledFeeds.filter((f: IntelFeed) => feedStatus(f) === 'error').length
  const pendingCount = enabledFeeds.filter((f: IntelFeed) => feedStatus(f) === 'pending').length

  // Group feeds by category
  const categories = new Map<string, IntelFeed[]>()
  for (const feed of enabledFeeds) {
    const cat = feed.category ?? 'other'
    if (!categories.has(cat)) categories.set(cat, [])
    categories.get(cat)!.push(feed)
  }

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-caption font-semibold text-content-primary uppercase tracking-wide">
            Feed Status
          </span>
          <div className="flex items-center gap-3 text-micro text-content-tertiary">
            {okCount > 0 && (
              <span className="flex items-center gap-1">
                <CheckCircle2 size={10} className="text-success" /> {okCount} ok
              </span>
            )}
            {errCount > 0 && (
              <span className="flex items-center gap-1">
                <AlertCircle size={10} className="text-danger" /> {errCount} failing
              </span>
            )}
            {pendingCount > 0 && (
              <span className="flex items-center gap-1">
                <Clock size={10} /> {pendingCount} pending
              </span>
            )}
          </div>
        </div>
        <button
          onClick={onManageFeeds}
          className="text-micro text-accent hover:text-accent-hover transition-colors"
        >
          Manage
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-x-6 gap-y-1">
        {[...categories.entries()].map(([cat, catFeeds]) => (
          <div key={cat}>
            <div className="text-micro text-content-tertiary uppercase tracking-wide mb-1 mt-2 first:mt-0">
              {cat}
            </div>
            {catFeeds.map(feed => {
              const st = feedStatus(feed)
              return (
                <div
                  key={feed.id}
                  className="flex items-center gap-2 py-1 group"
                >
                  <StatusIcon status={st} />
                  <span className={`text-caption truncate flex-1 ${
                    st === 'error' ? 'text-danger' : 'text-content-secondary'
                  }`}>
                    {feed.name}
                  </span>
                  {feed.last_checked_at && (
                    <span className="text-micro text-content-tertiary whitespace-nowrap">
                      {formatRelative(feed.last_checked_at)}
                    </span>
                  )}
                  {st === 'error' && feed.error_count > 1 && (
                    <span className="text-micro text-danger whitespace-nowrap">
                      x{feed.error_count}
                    </span>
                  )}
                  <a
                    href={feed.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="opacity-0 group-hover:opacity-100 text-content-tertiary hover:text-accent transition-all"
                    title={displayUrl(feed.url)}
                  >
                    <ExternalLink size={10} />
                  </a>
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </Card>
  )
}
