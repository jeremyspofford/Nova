import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, KeyRound } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import {
  getKnowledgeCredentials,
  createKnowledgeCredential,
  deleteKnowledgeCredential,
  type KnowledgeCredential,
} from '../../api'
import { Card } from '../ui/Card'
import { Button } from '../ui/Button'
import { ConfirmDialog } from '../ui/ConfirmDialog'

function healthColor(cred: KnowledgeCredential): string {
  if (!cred.last_validated_at) return 'bg-neutral-500'
  const hoursSince = (Date.now() - new Date(cred.last_validated_at).getTime()) / 3_600_000
  if (hoursSince <= 24) return 'bg-emerald-500 shadow-[0_0_4px_rgb(16_185_129/0.6)]'
  return 'bg-amber-500 shadow-[0_0_4px_rgb(245_158_11/0.5)]'
}

function healthLabel(cred: KnowledgeCredential): string {
  if (!cred.last_validated_at) return 'Never validated'
  const hoursSince = (Date.now() - new Date(cred.last_validated_at).getTime()) / 3_600_000
  if (hoursSince <= 24) return 'Validated'
  return 'Stale'
}

export function CredentialManager() {
  const qc = useQueryClient()
  const [showAddForm, setShowAddForm] = useState(false)
  const [label, setLabel] = useState('')
  const [token, setToken] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeCredential | null>(null)

  const { data: credentials = [], isLoading } = useQuery({
    queryKey: ['knowledge-credentials'],
    queryFn: getKnowledgeCredentials,
    staleTime: 10_000,
  })

  const createMutation = useMutation({
    mutationFn: () =>
      createKnowledgeCredential({ label: label.trim(), credential_data: token }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['knowledge-credentials'] })
      qc.invalidateQueries({ queryKey: ['knowledge-stats'] })
      resetForm()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteKnowledgeCredential(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['knowledge-credentials'] })
      qc.invalidateQueries({ queryKey: ['knowledge-stats'] })
      setDeleteTarget(null)
    },
  })

  const resetForm = () => {
    setLabel('')
    setToken('')
    setShowAddForm(false)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (label.trim() && token.trim()) createMutation.mutate()
  }

  return (
    <>
      <Card className="p-4">
        <div className="flex items-center justify-between mb-3">
          <span className="text-caption font-semibold text-content-primary uppercase tracking-wide flex items-center gap-1.5">
            <KeyRound size={14} className="text-content-tertiary" />
            Credentials
          </span>
          {!showAddForm && (
            <Button
              variant="ghost"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => setShowAddForm(true)}
            >
              Add
            </Button>
          )}
        </div>

        {/* Add credential form */}
        {showAddForm && (
          <form onSubmit={handleSubmit} className="mb-4 p-3 rounded-sm bg-surface-elevated border border-border-subtle space-y-3">
            <div>
              <label className="mb-1 block text-caption font-medium text-content-secondary">Label</label>
              <input
                value={label}
                onChange={e => setLabel(e.target.value)}
                placeholder="e.g., GitHub PAT"
                className="h-9 w-full rounded-sm border border-border bg-surface-input px-3 text-compact text-content-primary placeholder:text-content-tertiary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40"
                autoFocus
              />
            </div>
            <div>
              <label className="mb-1 block text-caption font-medium text-content-secondary">Token / Credential</label>
              <input
                type="password"
                value={token}
                onChange={e => setToken(e.target.value)}
                placeholder="ghp_xxxx or API key"
                className="h-9 w-full rounded-sm border border-border bg-surface-input px-3 text-compact text-content-primary placeholder:text-content-tertiary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40"
              />
            </div>
            {createMutation.isError && (
              <p className="text-caption text-danger">Failed: {String(createMutation.error)}</p>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" type="button" onClick={resetForm}>Cancel</Button>
              <Button size="sm" type="submit" disabled={!label.trim() || !token.trim()} loading={createMutation.isPending}>
                Save
              </Button>
            </div>
          </form>
        )}

        {/* Credential list */}
        {isLoading ? (
          <p className="text-caption text-content-tertiary">Loading credentials...</p>
        ) : credentials.length === 0 && !showAddForm ? (
          <p className="text-caption text-content-tertiary">No credentials stored. Add one to authenticate with private sources.</p>
        ) : (
          <div className="space-y-1">
            {credentials.map((cred: KnowledgeCredential) => (
              <div
                key={cred.id}
                className="flex items-center gap-3 py-2 group"
              >
                <span
                  className={`inline-block h-2 w-2 rounded-full shrink-0 ${healthColor(cred)}`}
                  title={healthLabel(cred)}
                />
                <span className="text-compact text-content-primary font-medium truncate flex-1">
                  {cred.label}
                </span>
                <span className="text-micro text-content-tertiary">
                  {cred.provider}
                </span>
                <span className="text-micro text-content-tertiary">
                  {formatDistanceToNow(new Date(cred.created_at), { addSuffix: true })}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Trash2 size={12} />}
                  onClick={() => setDeleteTarget(cred)}
                  title="Delete credential"
                  className="opacity-0 group-hover:opacity-100 transition-opacity"
                />
              </div>
            ))}
          </div>
        )}
      </Card>

      {deleteTarget && (
        <ConfirmDialog
          open={!!deleteTarget}
          onClose={() => setDeleteTarget(null)}
          title="Delete Credential"
          description={`Delete "${deleteTarget.label}"? Sources using this credential will lose access.`}
          confirmLabel="Delete"
          onConfirm={() => deleteMutation.mutate(deleteTarget.id)}
          destructive
        />
      )}
    </>
  )
}
