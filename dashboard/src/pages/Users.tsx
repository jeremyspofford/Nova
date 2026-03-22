import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { Plus, Trash2, Users as UsersIcon } from 'lucide-react'
import { fetchUsers, updateUser, deactivateUser, createInvite, fetchInvites, revokeInvite, type InviteCreateRequest } from '../api/users'
import { ROLE_HIERARCHY, ROLE_LABELS, canAssignRole, type Role } from '../lib/roles'
import type { SemanticColor } from '../lib/design-tokens'
import { useAuth } from '../stores/auth-store'
import { PageHeader } from '../components/layout/PageHeader'
import {
  Card, Button, Input, Select, Badge, Avatar, Tabs,
  Modal, CopyableId, ConfirmDialog, EmptyState,
} from '../components/ui'

type Tab = 'users' | 'invitations'

const ROLE_BADGE_COLORS: Record<Role, SemanticColor> = {
  owner: 'warning',
  admin: 'info',
  member: 'success',
  viewer: 'accent',
  guest: 'neutral',
}

const INVITE_EXPIRY_OPTIONS = [
  { label: '24 hours', hours: 24 },
  { label: '72 hours', hours: 72 },
  { label: '7 days', hours: 168 },
  { label: '30 days', hours: 720 },
  { label: 'Never', hours: 0 },
]

const ACCOUNT_EXPIRY_OPTIONS = [
  { label: '1 day', hours: 24 },
  { label: '7 days', hours: 168 },
  { label: '30 days', hours: 720 },
  { label: 'Never', hours: 0 },
]

export function Users() {
  const [tab, setTab] = useState<Tab>('users')
  const { user: currentUser } = useAuth()
  const currentRole = (currentUser?.role ?? 'viewer') as Role

  return (
    <div className="space-y-6">
      <PageHeader
        title="Users"
        description="Manage users and invite new people to your Nova instance."
      />

      <Tabs
        tabs={[
          { id: 'users', label: 'Users' },
          { id: 'invitations', label: 'Invitations' },
        ]}
        activeTab={tab}
        onChange={(id) => setTab(id as Tab)}
      />

      {tab === 'users' ? (
        <UsersTab currentRole={currentRole} currentUserId={currentUser?.id} />
      ) : (
        <InvitationsTab currentRole={currentRole} />
      )}
    </div>
  )
}

export function UsersTab({ currentRole, currentUserId }: { currentRole: Role; currentUserId?: string }) {
  const qc = useQueryClient()
  const { data: users = [], isLoading, error } = useQuery({ queryKey: ['users'], queryFn: fetchUsers })
  const [deactivateTarget, setDeactivateTarget] = useState<{ id: string; name: string } | null>(null)

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { role?: string } }) => updateUser(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  })

  const deactivateMutation = useMutation({
    mutationFn: deactivateUser,
    onSuccess: () => {
      setDeactivateTarget(null)
      qc.invalidateQueries({ queryKey: ['users'] })
    },
  })

  const assignableRoles = ROLE_HIERARCHY.filter(r => canAssignRole(currentRole, r))

  if (isLoading) return <Card className="p-8"><p className="text-compact text-content-tertiary text-center">Loading...</p></Card>
  if (error) return <Card className="p-4"><p className="text-compact text-danger">{String(error)}</p></Card>

  if (users.length === 0) {
    return (
      <Card className="py-8">
        <EmptyState
          icon={UsersIcon}
          title="No users found"
          description="Users will appear here once they register or are invited."
        />
      </Card>
    )
  }

  return (
    <>
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-compact">
            <thead>
              <tr className="bg-surface-elevated">
                <th className="px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">User</th>
                <th className="px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">Role</th>
                <th className="hidden sm:table-cell px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">Status</th>
                <th className="hidden md:table-cell px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">Last Updated</th>
                <th className="px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle">
              {users.map(u => {
                const role = u.role as Role
                const isOwner = role === 'owner'
                return (
                  <tr key={u.id} className="hover:bg-surface-card-hover transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <Avatar name={u.display_name || u.email} src={u.avatar_url ?? undefined} />
                        <div>
                          <p className="font-medium text-content-primary">{u.display_name || 'Unnamed'}</p>
                          <p className="text-caption text-content-tertiary">{u.email}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Badge color={ROLE_BADGE_COLORS[role] ?? 'neutral'}>
                        {ROLE_LABELS[role] || role}
                      </Badge>
                    </td>
                    <td className="hidden sm:table-cell px-4 py-3 text-content-secondary text-caption capitalize">
                      {u.status}
                    </td>
                    <td className="hidden md:table-cell px-4 py-3 text-content-tertiary text-caption">
                      {formatDistanceToNow(new Date(u.updated_at), { addSuffix: true })}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <Select
                          value={role}
                          onChange={e => {
                            const newRole = e.target.value
                            if (newRole !== role) {
                              updateMutation.mutate({ id: u.id, data: { role: newRole } })
                            }
                          }}
                          disabled={isOwner || u.id === currentUserId}
                          className="text-caption w-24"
                        >
                          {assignableRoles.map(r => (
                            <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                          ))}
                          {!assignableRoles.includes(role) && (
                            <option value={role}>{ROLE_LABELS[role] || role}</option>
                          )}
                        </Select>

                        {!isOwner && u.id !== currentUserId && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-danger"
                            onClick={() => setDeactivateTarget({ id: u.id, name: u.display_name || u.email })}
                          >
                            Deactivate
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <ConfirmDialog
        open={!!deactivateTarget}
        onClose={() => setDeactivateTarget(null)}
        title="Deactivate User"
        description={`Are you sure you want to deactivate "${deactivateTarget?.name}"? They will lose access to this Nova instance.`}
        confirmLabel="Deactivate"
        onConfirm={() => deactivateTarget && deactivateMutation.mutate(deactivateTarget.id)}
        destructive
      />
    </>
  )
}

export function InvitationsTab({ currentRole }: { currentRole: Role }) {
  const qc = useQueryClient()
  const { data: invites = [], isLoading, error } = useQuery({ queryKey: ['invites'], queryFn: fetchInvites })

  const [showForm, setShowForm] = useState(false)
  const [inviteRole, setInviteRole] = useState<Role>('member')
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteExpiry, setInviteExpiry] = useState(72)
  const [accountExpiry, setAccountExpiry] = useState(168)
  const [newInviteLink, setNewInviteLink] = useState<string | null>(null)
  const [revokeTarget, setRevokeTarget] = useState<{ id: string } | null>(null)

  const assignableRoles = ROLE_HIERARCHY.filter(r => canAssignRole(currentRole, r))

  const createMutation = useMutation({
    mutationFn: (data: InviteCreateRequest) => createInvite(data),
    onSuccess: (invite) => {
      const link = `${window.location.origin}/invite/${invite.code}`
      setNewInviteLink(link)
      setInviteEmail('')
      setShowForm(false)
      qc.invalidateQueries({ queryKey: ['invites'] })
    },
  })

  const revokeMutation = useMutation({
    mutationFn: revokeInvite,
    onSuccess: () => {
      setRevokeTarget(null)
      qc.invalidateQueries({ queryKey: ['invites'] })
    },
  })

  const handleGenerate = () => {
    const data: InviteCreateRequest = {
      role: inviteRole,
      ...(inviteEmail.trim() && { email: inviteEmail.trim() }),
      ...(inviteExpiry > 0 && { expires_in_hours: inviteExpiry }),
      ...(inviteRole === 'guest' && accountExpiry > 0 && { account_expires_in_hours: accountExpiry }),
    }
    createMutation.mutate(data)
  }

  return (
    <div className="space-y-4">
      {/* New invite link revealed */}
      {newInviteLink && (
        <Card className="border-success/30 bg-success-dim p-4">
          <p className="text-compact font-medium text-content-primary mb-2">
            Invite created -- share this link
          </p>
          <CopyableId id={newInviteLink} truncate={999} />
          <button
            onClick={() => setNewInviteLink(null)}
            className="mt-2 text-caption text-content-tertiary hover:text-content-secondary transition-colors"
          >
            Dismiss
          </button>
        </Card>
      )}

      <Button
        icon={<Plus size={14} />}
        onClick={() => setShowForm(true)}
      >
        Create Invite
      </Button>

      {/* Create invite modal */}
      <Modal
        open={showForm}
        onClose={() => { setShowForm(false); createMutation.reset() }}
        title="New Invitation"
        size="md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setShowForm(false)}>Cancel</Button>
            <Button
              onClick={handleGenerate}
              disabled={createMutation.isPending}
              loading={createMutation.isPending}
            >
              Generate
            </Button>
          </>
        }
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-caption font-medium text-content-secondary mb-1">Role</label>
            <Select
              value={inviteRole}
              onChange={e => setInviteRole(e.target.value as Role)}
            >
              {assignableRoles.map(r => (
                <option key={r} value={r}>{ROLE_LABELS[r]}</option>
              ))}
            </Select>
          </div>

          <div>
            <label className="block text-caption font-medium text-content-secondary mb-1">Email (optional)</label>
            <Input
              type="email"
              value={inviteEmail}
              onChange={e => setInviteEmail(e.target.value)}
              placeholder="user@example.com"
            />
          </div>

          <div>
            <label className="block text-caption font-medium text-content-secondary mb-1">Invite link expiry</label>
            <Select
              value={inviteExpiry}
              onChange={e => setInviteExpiry(Number(e.target.value))}
            >
              {INVITE_EXPIRY_OPTIONS.map(o => (
                <option key={o.hours} value={o.hours}>{o.label}</option>
              ))}
            </Select>
          </div>

          {inviteRole === 'guest' && (
            <div>
              <label className="block text-caption font-medium text-content-secondary mb-1">Account expiry</label>
              <Select
                value={accountExpiry}
                onChange={e => setAccountExpiry(Number(e.target.value))}
              >
                {ACCOUNT_EXPIRY_OPTIONS.map(o => (
                  <option key={o.hours} value={o.hours}>{o.label}</option>
                ))}
              </Select>
            </div>
          )}
        </div>
        {createMutation.isError && (
          <p className="mt-3 text-caption text-danger">{String(createMutation.error)}</p>
        )}
      </Modal>

      {/* Invites table */}
      {isLoading && <Card className="p-8"><p className="text-compact text-content-tertiary text-center">Loading...</p></Card>}
      {error && <Card className="p-4"><p className="text-compact text-danger">{String(error)}</p></Card>}

      {!isLoading && (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-compact">
              <thead>
                <tr className="bg-surface-elevated">
                  <th className="px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">Role</th>
                  <th className="hidden sm:table-cell px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">Email</th>
                  <th className="px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">Expires</th>
                  <th className="hidden md:table-cell px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">Created</th>
                  <th className="px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {invites.map(inv => {
                  const role = inv.role as Role
                  return (
                    <tr key={inv.id} className="hover:bg-surface-card-hover transition-colors">
                      <td className="px-4 py-3">
                        <Badge color={ROLE_BADGE_COLORS[role] ?? 'neutral'}>
                          {ROLE_LABELS[role] || role}
                        </Badge>
                      </td>
                      <td className="hidden sm:table-cell px-4 py-3 text-content-tertiary text-caption">
                        {inv.email || '--'}
                      </td>
                      <td className="px-4 py-3 text-content-secondary text-caption">
                        {inv.expires_at
                          ? formatDistanceToNow(new Date(inv.expires_at), { addSuffix: true })
                          : 'Never'}
                      </td>
                      <td className="hidden md:table-cell px-4 py-3 text-content-tertiary text-caption">
                        {formatDistanceToNow(new Date(inv.created_at), { addSuffix: true })}
                      </td>
                      <td className="px-4 py-3">
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Trash2 size={14} />}
                          onClick={() => setRevokeTarget({ id: inv.id })}
                          className="text-content-tertiary hover:text-danger"
                        />
                      </td>
                    </tr>
                  )
                })}
                {invites.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-12 text-center text-content-tertiary text-compact">
                      No pending invitations
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <ConfirmDialog
        open={!!revokeTarget}
        onClose={() => setRevokeTarget(null)}
        title="Revoke Invitation"
        description="Are you sure you want to revoke this invitation? The invite link will stop working immediately."
        confirmLabel="Revoke"
        onConfirm={() => revokeTarget && revokeMutation.mutate(revokeTarget.id)}
        destructive
      />
    </div>
  )
}
