import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { Plus, Key, Trash2 } from 'lucide-react'
import { getKeys, createKey, revokeKey } from '../api'
import { PageHeader } from '../components/layout/PageHeader'
import {
  Button, Input, Label, Badge, CopyableId, Card,
  Modal, Table, ConfirmDialog, EmptyState,
} from '../components/ui'
import type { TableColumn } from '../components/ui'
import type { ApiKey } from '../types'

export function Keys() {
  const qc = useQueryClient()
  const { data: keys = [], isLoading } = useQuery({ queryKey: ['keys'], queryFn: getKeys })

  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState('')
  const [rpm, setRpm] = useState(60)
  const [newKey, setNewKey] = useState<string | null>(null)

  const [revokeTarget, setRevokeTarget] = useState<ApiKey | null>(null)

  const createMutation = useMutation({
    mutationFn: () => createKey(name.trim(), rpm),
    onSuccess: data => {
      setNewKey(data.raw_key)
      setName('')
      setRpm(60)
      setCreateOpen(false)
      qc.invalidateQueries({ queryKey: ['keys'] })
    },
  })

  const revokeMutation = useMutation({
    mutationFn: revokeKey,
    onSuccess: () => {
      setRevokeTarget(null)
      qc.invalidateQueries({ queryKey: ['keys'] })
    },
  })

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const columns: TableColumn<any>[] = [
    {
      key: 'name',
      header: 'Name',
      render: (row) => (
        <span className="font-medium text-content-primary">{row.name}</span>
      ),
    },
    {
      key: 'key_prefix',
      header: 'Prefix',
      render: (row) => <CopyableId id={row.key_prefix + '...'} truncate={20} />,
    },
    {
      key: 'rate_limit_rpm',
      header: 'Rate Limit',
      render: (row) => <Badge color="neutral">{row.rate_limit_rpm}/min</Badge>,
    },
    {
      key: 'created_at',
      header: 'Created',
      render: (row) => (
        <span className="text-caption text-content-secondary">
          {formatDistanceToNow(new Date(row.created_at), { addSuffix: true })}
        </span>
      ),
    },
    {
      key: 'last_used_at',
      header: 'Last Used',
      render: (row) => (
        <span className="text-caption text-content-secondary">
          {row.last_used_at
            ? formatDistanceToNow(new Date(row.last_used_at), { addSuffix: true })
            : 'Never'}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '',
      width: '48px',
      render: (row) => (
        <Button
          variant="ghost"
          size="sm"
          icon={<Trash2 size={14} />}
          onClick={(e) => {
            e.stopPropagation()
            setRevokeTarget(row)
          }}
          className="text-content-tertiary hover:text-danger"
        />
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="API Keys"
        description="Keys let external clients call Nova's OpenAI-compatible API. Each key has its own rate limit and usage tracking."
        actions={
          <Button icon={<Plus size={14} />} onClick={() => setCreateOpen(true)}>
            Create Key
          </Button>
        }
      />

      {/* New key banner */}
      {newKey && (
        <Card className="border-success/30 bg-success-dim p-4">
          <p className="text-compact font-medium text-content-primary mb-2">
            Key created -- copy it now, it will not be shown again
          </p>
          <div className="flex items-center gap-2">
            <CopyableId id={newKey} truncate={999} />
          </div>
          <button
            onClick={() => setNewKey(null)}
            className="mt-2 text-caption text-content-tertiary hover:text-content-secondary transition-colors"
          >
            Dismiss
          </button>
        </Card>
      )}

      {/* Keys table */}
      {isLoading ? (
        <Card className="p-8">
          <p className="text-compact text-content-tertiary text-center">Loading...</p>
        </Card>
      ) : keys.length === 0 ? (
        <Card className="py-8">
          <EmptyState
            icon={Key}
            title="No API keys yet"
            description="Create an API key to let external tools and IDE plugins connect to Nova."
            action={{ label: 'Create Key', onClick: () => setCreateOpen(true) }}
          />
        </Card>
      ) : (
        <Table
          columns={columns as TableColumn<Record<string, unknown>>[]}
          data={keys as unknown as Record<string, unknown>[]}
          emptyMessage="No API keys"
        />
      )}

      {/* Create key modal */}
      <Modal
        open={createOpen}
        onClose={() => { setCreateOpen(false); createMutation.reset() }}
        title="Create API Key"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => createMutation.mutate()}
              disabled={!name.trim()}
              loading={createMutation.isPending}
            >
              Create
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <Label>Name</Label>
            <Input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g. continue-dev"
            />
          </div>
          <div>
            <Label>Rate limit (requests/min)</Label>
            <Input
              type="number"
              value={rpm}
              onChange={e => setRpm(Number(e.target.value))}
              min={1}
              max={9999}
            />
          </div>
          {createMutation.isError && (
            <p className="text-caption text-danger">{String(createMutation.error)}</p>
          )}
        </div>
      </Modal>

      {/* Revoke confirmation */}
      <ConfirmDialog
        open={!!revokeTarget}
        onClose={() => setRevokeTarget(null)}
        title="Revoke API Key"
        description={`Are you sure you want to revoke "${revokeTarget?.name}"? Any clients using this key will immediately lose access.`}
        confirmLabel="Revoke"
        onConfirm={() => revokeTarget && revokeMutation.mutate(revokeTarget.id)}
        destructive
      />
    </div>
  )
}
