import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Pencil, Check, X } from 'lucide-react'
import { getIntelFeeds, createIntelFeed, updateIntelFeed, deleteIntelFeed, type IntelFeed } from '../../api'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Toggle } from '../ui/Toggle'
import { ConfirmDialog } from '../ui/ConfirmDialog'

interface Props {
  open: boolean
  onClose: () => void
}

const FEED_TYPES = [
  { value: 'rss', label: 'RSS' },
  { value: 'reddit_json', label: 'Reddit JSON' },
  { value: 'page', label: 'Web Page' },
  { value: 'github_trending', label: 'GitHub Trending' },
  { value: 'github_releases', label: 'GitHub Releases' },
]

const FEED_TYPE_COLORS: Record<string, string> = {
  rss: 'bg-blue-900/30 text-blue-400',
  reddit_json: 'bg-orange-900/30 text-orange-400',
  page: 'bg-stone-700/40 text-stone-300',
  github_trending: 'bg-purple-900/30 text-purple-400',
  github_releases: 'bg-teal-900/30 text-teal-400',
}

function formatInterval(seconds: number): string {
  const hours = seconds / 3600
  if (hours >= 1) return `${hours % 1 === 0 ? hours : hours.toFixed(1)}h`
  return `${Math.round(seconds / 60)}m`
}

function formatRelativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDays = Math.floor(diffHr / 24)
  return `${diffDays}d ago`
}

export function FeedManagerModal({ open, onClose }: Props) {
  const qc = useQueryClient()
  const [showAddForm, setShowAddForm] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<IntelFeed | null>(null)

  // Edit state — which feed is being edited inline
  const [editId, setEditId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editCategory, setEditCategory] = useState('')
  const [editInterval, setEditInterval] = useState('')

  // Add form state
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [feedType, setFeedType] = useState('rss')
  const [category, setCategory] = useState('')
  const [intervalHours, setIntervalHours] = useState('12')

  const { data: feeds = [], isLoading } = useQuery({
    queryKey: ['intel-feeds'],
    queryFn: getIntelFeeds,
    enabled: open,
  })

  const createMutation = useMutation({
    mutationFn: () =>
      createIntelFeed({
        name,
        url,
        feed_type: feedType,
        category: category || undefined,
        check_interval_seconds: Number(intervalHours) * 3600,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['intel-feeds'] })
      qc.invalidateQueries({ queryKey: ['intel-stats'] })
      resetForm()
    },
  })

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      updateIntelFeed(id, { enabled }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['intel-feeds'] })
      qc.invalidateQueries({ queryKey: ['intel-stats'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteIntelFeed(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['intel-feeds'] })
      qc.invalidateQueries({ queryKey: ['intel-stats'] })
      setDeleteTarget(null)
    },
  })

  const editMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<IntelFeed> }) =>
      updateIntelFeed(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['intel-feeds'] })
      qc.invalidateQueries({ queryKey: ['intel-stats'] })
      setEditId(null)
    },
  })

  const startEdit = (feed: IntelFeed) => {
    setEditId(feed.id)
    setEditName(feed.name)
    setEditCategory(feed.category ?? '')
    setEditInterval(String(feed.check_interval_seconds / 3600))
  }

  const saveEdit = (feedId: string) => {
    editMutation.mutate({
      id: feedId,
      data: {
        name: editName,
        category: editCategory || undefined,
        check_interval_seconds: Number(editInterval) * 3600,
      },
    })
  }

  const cancelEdit = () => setEditId(null)

  const resetForm = () => {
    setName('')
    setUrl('')
    setFeedType('rss')
    setCategory('')
    setIntervalHours('12')
    setShowAddForm(false)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (name.trim() && url.trim()) createMutation.mutate()
  }

  return (
    <>
      <Modal open={open} onClose={onClose} size="xl" title="Manage Feeds">
        {/* Add feed toggle */}
        {!showAddForm ? (
          <div className="mb-4">
            <Button
              variant="secondary"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => setShowAddForm(true)}
            >
              Add Feed
            </Button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="mb-4 p-3 rounded-sm bg-surface-elevated border border-border-subtle space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-caption font-medium text-content-secondary">Name</label>
                <input
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="Feed name"
                  className="h-9 w-full rounded-sm border border-border bg-surface-input px-3 text-compact text-content-primary placeholder:text-content-tertiary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40"
                  autoFocus
                />
              </div>
              <div>
                <label className="mb-1 block text-caption font-medium text-content-secondary">URL</label>
                <input
                  value={url}
                  onChange={e => setUrl(e.target.value)}
                  placeholder="https://..."
                  className="h-9 w-full rounded-sm border border-border bg-surface-input px-3 text-compact text-content-primary placeholder:text-content-tertiary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40"
                />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="mb-1 block text-caption font-medium text-content-secondary">Type</label>
                <select
                  value={feedType}
                  onChange={e => setFeedType(e.target.value)}
                  className="h-9 w-full rounded-sm border border-border bg-surface-input px-3 text-compact text-content-primary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40 appearance-none"
                >
                  {FEED_TYPES.map(t => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-caption font-medium text-content-secondary">Category</label>
                <input
                  value={category}
                  onChange={e => setCategory(e.target.value)}
                  placeholder="Optional"
                  className="h-9 w-full rounded-sm border border-border bg-surface-input px-3 text-compact text-content-primary placeholder:text-content-tertiary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40"
                />
              </div>
              <div>
                <label className="mb-1 block text-caption font-medium text-content-secondary">Interval (hours)</label>
                <input
                  type="number"
                  value={intervalHours}
                  onChange={e => setIntervalHours(e.target.value)}
                  min="1"
                  step="1"
                  className="h-9 w-full rounded-sm border border-border bg-surface-input px-3 text-compact text-content-primary placeholder:text-content-tertiary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40"
                />
              </div>
            </div>
            <div className="flex gap-2 justify-end">
              <Button variant="ghost" size="sm" type="button" onClick={resetForm}>
                Cancel
              </Button>
              <Button
                size="sm"
                type="submit"
                disabled={!name.trim() || !url.trim()}
                loading={createMutation.isPending}
              >
                Add Feed
              </Button>
            </div>
            {createMutation.isError && (
              <p className="text-caption text-danger">Failed to create feed: {String(createMutation.error)}</p>
            )}
          </form>
        )}

        {/* Feed table */}
        {isLoading ? (
          <p className="text-caption text-content-tertiary">Loading feeds...</p>
        ) : feeds.length === 0 ? (
          <p className="text-caption text-content-tertiary">No feeds configured. Add one to start scanning.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-caption">
              <thead>
                <tr className="border-b border-border-subtle text-content-tertiary text-left">
                  <th className="py-2 pr-3 font-medium">Name</th>
                  <th className="py-2 pr-3 font-medium">URL</th>
                  <th className="py-2 pr-3 font-medium">Type</th>
                  <th className="py-2 pr-3 font-medium">Category</th>
                  <th className="py-2 pr-3 font-medium">Interval</th>
                  <th className="py-2 pr-3 font-medium">Last Checked</th>
                  <th className="py-2 pr-3 font-medium">Enabled</th>
                  <th className="py-2 font-medium w-10"></th>
                </tr>
              </thead>
              <tbody>
                {feeds.map((feed: IntelFeed) => {
                  const isEditing = editId === feed.id
                  return (
                    <tr key={feed.id} className="border-b border-border-subtle/50 hover:bg-surface-elevated/50 transition-colors">
                      <td className="py-2.5 pr-3 text-content-primary font-medium max-w-[200px]">
                        {isEditing ? (
                          <input
                            value={editName}
                            onChange={e => setEditName(e.target.value)}
                            className="h-7 w-full rounded-sm border border-border bg-surface-input px-2 text-caption text-content-primary outline-none focus:border-border-focus"
                            autoFocus
                          />
                        ) : (
                          <span className="truncate block" title={feed.name}>{feed.name}</span>
                        )}
                      </td>
                      <td className="py-2.5 pr-3 max-w-[220px]">
                        <a
                          href={feed.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-caption text-accent hover:text-accent-hover truncate block"
                          title={feed.url}
                        >
                          {feed.url.replace(/^https?:\/\/(www\.|old\.)?/, '').replace(/\/$/, '')}
                        </a>
                      </td>
                      <td className="py-2.5 pr-3">
                        <span className={`inline-flex px-1.5 py-0.5 rounded text-micro font-medium ${FEED_TYPE_COLORS[feed.feed_type] ?? 'bg-neutral-700 text-neutral-300'}`}>
                          {feed.feed_type}
                        </span>
                      </td>
                      <td className="py-2.5 pr-3">
                        {isEditing ? (
                          <input
                            value={editCategory}
                            onChange={e => setEditCategory(e.target.value)}
                            placeholder="category"
                            className="h-7 w-full rounded-sm border border-border bg-surface-input px-2 text-caption text-content-primary outline-none focus:border-border-focus"
                          />
                        ) : (
                          <span className="text-content-secondary">{feed.category ?? '--'}</span>
                        )}
                      </td>
                      <td className="py-2.5 pr-3">
                        {isEditing ? (
                          <input
                            type="number"
                            value={editInterval}
                            onChange={e => setEditInterval(e.target.value)}
                            min="1"
                            step="1"
                            className="h-7 w-16 rounded-sm border border-border bg-surface-input px-2 text-caption text-content-primary font-mono outline-none focus:border-border-focus"
                          />
                        ) : (
                          <span className="text-content-secondary font-mono">{formatInterval(feed.check_interval_seconds)}</span>
                        )}
                      </td>
                      <td className="py-2.5 pr-3 text-content-tertiary">
                        {feed.last_checked_at ? formatRelativeTime(feed.last_checked_at) : 'never'}
                      </td>
                      <td className="py-2.5 pr-3">
                        <Toggle
                          size="sm"
                          checked={feed.enabled}
                          onChange={() => toggleMutation.mutate({ id: feed.id, enabled: !feed.enabled })}
                        />
                      </td>
                      <td className="py-2.5">
                        {isEditing ? (
                          <div className="flex gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              icon={<Check size={12} />}
                              onClick={() => saveEdit(feed.id)}
                              title="Save"
                              loading={editMutation.isPending}
                            />
                            <Button
                              variant="ghost"
                              size="sm"
                              icon={<X size={12} />}
                              onClick={cancelEdit}
                              title="Cancel"
                            />
                          </div>
                        ) : (
                          <div className="flex gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              icon={<Pencil size={12} />}
                              onClick={() => startEdit(feed)}
                              title="Edit feed"
                            />
                            <Button
                              variant="ghost"
                              size="sm"
                              icon={<Trash2 size={12} />}
                              onClick={() => setDeleteTarget(feed)}
                              title="Delete feed"
                            />
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Modal>

      {deleteTarget && (
        <ConfirmDialog
          open={!!deleteTarget}
          onClose={() => setDeleteTarget(null)}
          title="Delete Feed"
          description={`Delete "${deleteTarget.name}"? This will not remove previously discovered content.`}
          confirmLabel="Delete"
          onConfirm={() => deleteMutation.mutate(deleteTarget.id)}
          destructive
        />
      )}
    </>
  )
}
