import { useState, useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createKnowledgeSource, getKnowledgeCredentials } from '../../api'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'

interface Props {
  open: boolean
  onClose: () => void
  scope: string
}

interface DetectedType {
  source_type: string
  label: string
  note?: string
}

function detectPlatform(url: string): DetectedType {
  try {
    const u = new URL(url)
    const host = u.hostname.toLowerCase()

    if (host === 'github.com' || host === 'www.github.com') {
      return { source_type: 'github_profile', label: 'GitHub' }
    }
    if (host === 'gitlab.com' || host === 'www.gitlab.com') {
      return { source_type: 'gitlab_profile', label: 'GitLab' }
    }
    if (host === 'twitter.com' || host === 'x.com' || host === 'www.twitter.com' || host === 'www.x.com') {
      return {
        source_type: 'twitter',
        label: 'Twitter',
        note: 'Social media extractors coming soon -- will use general crawler',
      }
    }
    if (host === 'linkedin.com' || host === 'www.linkedin.com') {
      return {
        source_type: 'web_crawl',
        label: 'Web Crawl',
        note: 'LinkedIn may be restricted -- manual paste available as fallback',
      }
    }
    return { source_type: 'web_crawl', label: 'Web Crawl' }
  } catch {
    return { source_type: 'web_crawl', label: 'Web Crawl' }
  }
}

function hostnameFromUrl(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

const TYPE_BADGE_COLORS: Record<string, string> = {
  github_profile: 'bg-purple-900/30 text-purple-400',
  gitlab_profile: 'bg-orange-900/30 text-orange-400',
  twitter: 'bg-sky-900/30 text-sky-400',
  web_crawl: 'bg-blue-900/30 text-blue-400',
}

export function AddSourceModal({ open, onClose, scope }: Props) {
  const qc = useQueryClient()
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [credentialId, setCredentialId] = useState<string>('')

  const { data: credentials = [] } = useQuery({
    queryKey: ['knowledge-credentials'],
    queryFn: getKnowledgeCredentials,
    enabled: open,
  })

  const detected = useMemo(() => detectPlatform(url), [url])
  const autoName = hostnameFromUrl(url)

  const createMutation = useMutation({
    mutationFn: () =>
      createKnowledgeSource({
        name: name.trim() || autoName || 'Untitled',
        url,
        source_type: detected.source_type,
        scope,
        credential_id: credentialId || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['knowledge-sources'] })
      qc.invalidateQueries({ queryKey: ['knowledge-stats'] })
      resetAndClose()
    },
  })

  const resetAndClose = () => {
    setUrl('')
    setName('')
    setCredentialId('')
    onClose()
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (url.trim()) createMutation.mutate()
  }

  return (
    <Modal open={open} onClose={resetAndClose} size="md" title="Add Source">
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* URL */}
        <div>
          <label className="mb-1 block text-caption font-medium text-content-secondary">URL</label>
          <input
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://github.com/user, https://docs.example.com, ..."
            className="h-9 w-full rounded-sm border border-border bg-surface-input px-3 text-compact text-content-primary placeholder:text-content-tertiary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40"
            autoFocus
          />
        </div>

        {/* Detected type badge */}
        {url.trim() && (
          <div className="flex items-center gap-2">
            <span className="text-caption text-content-tertiary">Detected:</span>
            <span className={`inline-flex px-1.5 py-0.5 rounded text-micro font-medium ${TYPE_BADGE_COLORS[detected.source_type] ?? 'bg-neutral-700 text-neutral-300'}`}>
              {detected.label}
            </span>
            {detected.note && (
              <span className="text-micro text-amber-400">{detected.note}</span>
            )}
          </div>
        )}

        {/* Name */}
        <div>
          <label className="mb-1 block text-caption font-medium text-content-secondary">
            Name <span className="text-content-tertiary font-normal">(optional -- auto-populated from URL)</span>
          </label>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder={autoName || 'Leave blank to auto-detect'}
            className="h-9 w-full rounded-sm border border-border bg-surface-input px-3 text-compact text-content-primary placeholder:text-content-tertiary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40"
          />
        </div>

        {/* Credential selector */}
        <div>
          <label className="mb-1 block text-caption font-medium text-content-secondary">
            Credential <span className="text-content-tertiary font-normal">(optional)</span>
          </label>
          <select
            value={credentialId}
            onChange={e => setCredentialId(e.target.value)}
            className="h-9 w-full rounded-sm border border-border bg-surface-input px-3 text-compact text-content-primary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40"
          >
            <option value="">None</option>
            {credentials.map(c => (
              <option key={c.id} value={c.id}>{c.label} ({c.provider})</option>
            ))}
          </select>
        </div>

        {createMutation.isError && (
          <p className="text-caption text-danger">
            Failed to create source: {String(createMutation.error)}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" type="button" onClick={resetAndClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={!url.trim()} loading={createMutation.isPending}>
            Add Source
          </Button>
        </div>
      </form>
    </Modal>
  )
}
