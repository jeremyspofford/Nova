import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ChevronDown, ChevronRight, Copy, Check } from 'lucide-react'
import { Modal } from '../ui/Modal'
import { getEngramDetail } from '../../api'
import type { EngramDetail } from '../../types'

const TYPE_COLORS: Record<string, string> = {
  fact: 'bg-blue-500/20 text-blue-400',
  episode: 'bg-purple-500/20 text-purple-400',
  concept: 'bg-teal-500/20 text-teal-400',
  procedure: 'bg-amber-500/20 text-amber-400',
  preference: 'bg-rose-500/20 text-rose-400',
  topic: 'bg-emerald-500/20 text-emerald-400',
}

function TypeBadge({ type }: { type: string }) {
  const colors = TYPE_COLORS[type] ?? 'bg-neutral-500/20 text-neutral-400'
  return (
    <span className={`text-micro font-semibold uppercase px-2 py-0.5 rounded-full ${colors}`}>
      {type}
    </span>
  )
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-compact text-content-tertiary w-24 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 bg-border-subtle rounded-full overflow-hidden">
        <div
          className="h-full bg-accent rounded-full transition-all"
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </div>
      <span className="text-mono-sm font-mono text-content-secondary w-12 text-right">
        {value.toFixed(2)}
      </span>
    </div>
  )
}

function CopyableId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    navigator.clipboard.writeText(id)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button
      onClick={handleCopy}
      className="inline-flex items-center gap-1.5 text-mono-sm font-mono text-content-tertiary
                 hover:text-content-secondary transition-colors"
      title="Copy full ID"
    >
      {id}
      {copied ? <Check size={12} className="text-success" /> : <Copy size={12} />}
    </button>
  )
}

interface Props {
  engramId: string | null
  onClose: () => void
}

export function EngramDetailModal({ engramId, onClose }: Props) {
  const [metaOpen, setMetaOpen] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['engram-detail', engramId],
    queryFn: () => getEngramDetail(engramId!),
    enabled: !!engramId,
    staleTime: 30_000,
    retry: 1,
  })

  if (!engramId) return null

  const title = data
    ? `${data.type.charAt(0).toUpperCase() + data.type.slice(1)}: ${data.content.slice(0, 50)}${data.content.length > 50 ? '...' : ''}`
    : 'Loading...'

  return (
    <Modal open={!!engramId} onClose={onClose} size="md" title={title}>
      {isLoading && (
        <div className="space-y-3 animate-pulse">
          <div className="h-4 bg-border-subtle rounded w-1/4" />
          <div className="h-20 bg-border-subtle rounded" />
          <div className="h-4 bg-border-subtle rounded w-1/2" />
        </div>
      )}

      {error && (
        <div className="text-danger text-compact">
          Failed to load engram details. It may have been pruned or merged.
        </div>
      )}

      {data && (
        <div className="space-y-4">
          {/* Type badge + source */}
          <div className="flex items-center gap-3 flex-wrap">
            <TypeBadge type={data.type} />
            <span className="text-compact text-content-tertiary">
              via {data.source_type.replace(/_/g, ' ')}
            </span>
            {data.superseded && (
              <span className="text-micro font-semibold uppercase px-2 py-0.5 rounded-full
                             bg-warning/20 text-warning">
                Superseded
              </span>
            )}
          </div>

          {/* Full content */}
          <div className="text-body text-content-primary whitespace-pre-wrap leading-relaxed">
            {data.content}
          </div>

          {/* Timestamp + ID */}
          <div className="flex items-center justify-between text-content-tertiary border-t border-border-subtle pt-3">
            <span className="text-compact">
              {data.created_at
                ? new Date(data.created_at).toLocaleString()
                : 'Unknown date'}
            </span>
            <CopyableId id={data.id} />
          </div>

          {/* Collapsible metadata */}
          <div className="border-t border-border-subtle pt-3">
            <button
              onClick={() => setMetaOpen(m => !m)}
              className="flex items-center gap-1.5 text-compact text-content-tertiary
                         hover:text-content-secondary transition-colors w-full text-left"
            >
              {metaOpen
                ? <ChevronDown size={14} />
                : <ChevronRight size={14} />
              }
              <span className="font-medium">Metadata</span>
            </button>
            {metaOpen && (
              <div className="mt-3 space-y-2.5">
                <ScoreBar label="Activation" value={data.activation} />
                <ScoreBar label="Importance" value={data.importance} />
                <ScoreBar label="Confidence" value={data.confidence} />
                <div className="flex items-center gap-3">
                  <span className="text-compact text-content-tertiary w-24 shrink-0">
                    Access count
                  </span>
                  <span className="text-mono-sm font-mono text-content-secondary">
                    {data.access_count}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  )
}
