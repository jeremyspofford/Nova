import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { Copy, Check, Plus, Trash2 } from 'lucide-react'
import { fetchUsers, updateUser, deactivateUser, createInvite, fetchInvites, revokeInvite, type InviteCreateRequest } from '../api/users'
import { ROLE_HIERARCHY, ROLE_LABELS, ROLE_COLORS, canAssignRole, type Role } from '../lib/roles'
import { useAuth } from '../stores/auth-store'
import Card from '../components/Card'

type Tab = 'users' | 'invitations'

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

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <button onClick={copy} className="ml-1 text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300">
      {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
    </button>
  )
}

export function Users() {
  const [tab, setTab] = useState<Tab>('users')
  const { user: currentUser } = useAuth()
  const currentRole = (currentUser?.role ?? 'viewer') as Role

  return (
    <div className="px-4 py-6 sm:px-6 space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">Users</h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400 max-w-2xl">
          Manage users and invite new people to your Nova instance.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-6 border-b border-neutral-200 dark:border-neutral-800">
        {(['users', 'invitations'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`pb-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
              tab === t
                ? 'border-teal-500 text-teal-600 dark:text-teal-400'
                : 'border-transparent text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200'
            }`}
          >
            {t === 'users' ? 'Users' : 'Invitations'}
          </button>
        ))}
      </div>

      {tab === 'users' ? (
        <UsersTab currentRole={currentRole} currentUserId={currentUser?.id} />
      ) : (
        <InvitationsTab currentRole={currentRole} />
      )}
    </div>
  )
}

function UsersTab({ currentRole, currentUserId }: { currentRole: Role; currentUserId?: string }) {
  const qc = useQueryClient()
  const { data: users = [], isLoading, error } = useQuery({ queryKey: ['users'], queryFn: fetchUsers })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { role?: string } }) => updateUser(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  })

  const deactivateMutation = useMutation({
    mutationFn: deactivateUser,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  })

  const assignableRoles = ROLE_HIERARCHY.filter(r => canAssignRole(currentRole, r))

  if (isLoading) return <p className="text-sm text-neutral-500 dark:text-neutral-400">Loading...</p>
  if (error) return <p className="text-sm text-red-400">{String(error)}</p>

  return (
    <Card className="overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-200 dark:border-neutral-800 text-xs text-neutral-500 dark:text-neutral-400">
              <th className="px-3 sm:px-4 py-3 text-left font-medium">Name</th>
              <th className="px-3 sm:px-4 py-3 text-left font-medium">Role</th>
              <th className="hidden sm:table-cell px-4 py-3 text-left font-medium">Status</th>
              <th className="hidden md:table-cell px-4 py-3 text-left font-medium">Last Updated</th>
              <th className="px-3 sm:px-4 py-3 text-left font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map(u => {
              const role = u.role as Role
              const isOwner = role === 'owner'
              return (
                <tr
                  key={u.id}
                  className={`border-b border-neutral-200/50 dark:border-neutral-800/50 hover:bg-neutral-100/30 dark:hover:bg-neutral-800/30 ${
                    isOwner ? 'border-l-2 border-l-amber-400' : ''
                  }`}
                >
                  <td className="px-3 sm:px-4 py-3">
                    <div className="font-medium text-neutral-900 dark:text-neutral-100">
                      {u.display_name || 'Unnamed'}
                    </div>
                    <div className="text-xs text-neutral-500 dark:text-neutral-400">{u.email}</div>
                  </td>
                  <td className="px-3 sm:px-4 py-3">
                    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${ROLE_COLORS[role] || ''}`}>
                      {ROLE_LABELS[role] || role}
                    </span>
                  </td>
                  <td className="hidden sm:table-cell px-4 py-3 text-neutral-500 dark:text-neutral-400 text-xs capitalize">
                    {u.status}
                  </td>
                  <td className="hidden md:table-cell px-4 py-3 text-neutral-500 dark:text-neutral-400 text-xs">
                    {formatDistanceToNow(new Date(u.updated_at), { addSuffix: true })}
                  </td>
                  <td className="px-3 sm:px-4 py-3">
                    <div className="flex items-center gap-2">
                      {/* Role dropdown */}
                      <select
                        value={role}
                        onChange={e => {
                          const newRole = e.target.value
                          if (newRole !== role) {
                            updateMutation.mutate({ id: u.id, data: { role: newRole } })
                          }
                        }}
                        disabled={isOwner || u.id === currentUserId}
                        className="rounded-md border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-xs px-2 py-1 text-neutral-700 dark:text-neutral-300 disabled:opacity-40"
                      >
                        {assignableRoles.map(r => (
                          <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                        ))}
                        {/* Show current role even if not assignable */}
                        {!assignableRoles.includes(role) && (
                          <option value={role}>{ROLE_LABELS[role] || role}</option>
                        )}
                      </select>

                      {/* Deactivate button */}
                      {!isOwner && u.id !== currentUserId && (
                        <button
                          onClick={() => {
                            if (confirm(`Deactivate user "${u.display_name || u.email}"?`))
                              deactivateMutation.mutate(u.id)
                          }}
                          className="text-red-400 hover:text-red-300 text-xs"
                        >
                          Deactivate
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
            {users.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-sm text-neutral-500 dark:text-neutral-400">
                  No users found
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function InvitationsTab({ currentRole }: { currentRole: Role }) {
  const qc = useQueryClient()
  const { data: invites = [], isLoading, error } = useQuery({ queryKey: ['invites'], queryFn: fetchInvites })

  const [showForm, setShowForm] = useState(false)
  const [inviteRole, setInviteRole] = useState<Role>('member')
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteExpiry, setInviteExpiry] = useState(72)
  const [accountExpiry, setAccountExpiry] = useState(168)
  const [newInviteLink, setNewInviteLink] = useState<string | null>(null)

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
    onSuccess: () => qc.invalidateQueries({ queryKey: ['invites'] }),
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
        <div className="rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/30 p-4">
          <p className="text-sm font-medium text-emerald-700 dark:text-emerald-400 mb-1">
            Invite created -- share this link
          </p>
          <div className="flex items-center gap-2 font-mono text-sm text-emerald-800 dark:text-emerald-300 break-all">
            {newInviteLink}
            <CopyButton text={newInviteLink} />
          </div>
          <button onClick={() => setNewInviteLink(null)} className="mt-2 text-xs text-emerald-600 dark:text-emerald-400 hover:text-emerald-800 dark:hover:text-emerald-300">
            Dismiss
          </button>
        </div>
      )}

      {/* Create invite button / form */}
      {!showForm ? (
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-1.5 rounded-lg bg-teal-600 hover:bg-teal-700 text-white text-sm px-3 py-1.5"
        >
          <Plus size={14} /> Create Invite
        </button>
      ) : (
        <Card className="p-4 space-y-3">
          <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">New Invitation</p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-neutral-600 dark:text-neutral-300 mb-1">Role</label>
              <select
                value={inviteRole}
                onChange={e => setInviteRole(e.target.value as Role)}
                className="w-full rounded-md border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-sm px-3 py-1.5 text-neutral-700 dark:text-neutral-300"
              >
                {assignableRoles.map(r => (
                  <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-neutral-600 dark:text-neutral-300 mb-1">Email (optional)</label>
              <input
                type="email"
                value={inviteEmail}
                onChange={e => setInviteEmail(e.target.value)}
                placeholder="user@example.com"
                className="w-full rounded-md border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-sm px-3 py-1.5 text-neutral-700 dark:text-neutral-300 placeholder:text-neutral-400"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-neutral-600 dark:text-neutral-300 mb-1">Invite link expiry</label>
              <select
                value={inviteExpiry}
                onChange={e => setInviteExpiry(Number(e.target.value))}
                className="w-full rounded-md border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-sm px-3 py-1.5 text-neutral-700 dark:text-neutral-300"
              >
                {INVITE_EXPIRY_OPTIONS.map(o => (
                  <option key={o.hours} value={o.hours}>{o.label}</option>
                ))}
              </select>
            </div>

            {inviteRole === 'guest' && (
              <div>
                <label className="block text-xs font-medium text-neutral-600 dark:text-neutral-300 mb-1">Account expiry</label>
                <select
                  value={accountExpiry}
                  onChange={e => setAccountExpiry(Number(e.target.value))}
                  className="w-full rounded-md border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-sm px-3 py-1.5 text-neutral-700 dark:text-neutral-300"
                >
                  {ACCOUNT_EXPIRY_OPTIONS.map(o => (
                    <option key={o.hours} value={o.hours}>{o.label}</option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={handleGenerate}
              disabled={createMutation.isPending}
              className="flex items-center gap-1.5 rounded-lg bg-teal-600 hover:bg-teal-700 text-white text-sm px-3 py-1.5 disabled:opacity-40"
            >
              Generate
            </button>
            <button
              onClick={() => setShowForm(false)}
              className="text-sm text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200 px-3 py-1.5"
            >
              Cancel
            </button>
          </div>
          {createMutation.isError && (
            <p className="text-xs text-red-600 dark:text-red-400">{String(createMutation.error)}</p>
          )}
        </Card>
      )}

      {/* Invites table */}
      {isLoading && <p className="text-sm text-neutral-500 dark:text-neutral-400">Loading...</p>}
      {error && <p className="text-sm text-red-400">{String(error)}</p>}

      {!isLoading && (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-200 dark:border-neutral-800 text-xs text-neutral-500 dark:text-neutral-400">
                  <th className="px-3 sm:px-4 py-3 text-left font-medium">Role</th>
                  <th className="hidden sm:table-cell px-4 py-3 text-left font-medium">Email</th>
                  <th className="px-3 sm:px-4 py-3 text-left font-medium">Expires</th>
                  <th className="hidden md:table-cell px-4 py-3 text-left font-medium">Created</th>
                  <th className="px-3 sm:px-4 py-3 text-left font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {invites.map(inv => {
                  const role = inv.role as Role
                  return (
                    <tr key={inv.id} className="border-b border-neutral-200/50 dark:border-neutral-800/50 hover:bg-neutral-100/30 dark:hover:bg-neutral-800/30">
                      <td className="px-3 sm:px-4 py-3">
                        <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${ROLE_COLORS[role] || ''}`}>
                          {ROLE_LABELS[role] || role}
                        </span>
                      </td>
                      <td className="hidden sm:table-cell px-4 py-3 text-neutral-500 dark:text-neutral-400 text-xs">
                        {inv.email || '--'}
                      </td>
                      <td className="px-3 sm:px-4 py-3 text-neutral-500 dark:text-neutral-400 text-xs">
                        {inv.expires_at
                          ? formatDistanceToNow(new Date(inv.expires_at), { addSuffix: true })
                          : 'Never'}
                      </td>
                      <td className="hidden md:table-cell px-4 py-3 text-neutral-500 dark:text-neutral-400 text-xs">
                        {formatDistanceToNow(new Date(inv.created_at), { addSuffix: true })}
                      </td>
                      <td className="px-3 sm:px-4 py-3">
                        <button
                          onClick={() => {
                            if (confirm('Revoke this invite?'))
                              revokeMutation.mutate(inv.id)
                          }}
                          className="text-red-400 hover:text-red-300 transition-colors"
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  )
                })}
                {invites.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-sm text-neutral-500 dark:text-neutral-400">
                      No pending invitations
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
