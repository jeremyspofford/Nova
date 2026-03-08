import { useState } from 'react'
import { CircleUser, Check, AlertCircle } from 'lucide-react'
import { useAuth } from '../../stores/auth-store'
import { apiFetch } from '../../api'
import { Section } from './shared'

export function AccountSection() {
  const { user } = useAuth()

  const [displayName, setDisplayName] = useState(user?.display_name ?? '')
  const [profileSaving, setProfileSaving] = useState(false)
  const [profileMsg, setProfileMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [pwSaving, setPwSaving] = useState(false)
  const [pwMsg, setPwMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  if (!user) return null

  const profileDirty = displayName !== (user.display_name ?? '')

  const handleProfileSave = async () => {
    setProfileSaving(true)
    setProfileMsg(null)
    try {
      await apiFetch('/api/v1/auth/me', {
        method: 'PATCH',
        body: JSON.stringify({ display_name: displayName || null }),
      })
      setProfileMsg({ type: 'ok', text: 'Profile updated' })
      setTimeout(() => setProfileMsg(null), 3000)
    } catch (err) {
      setProfileMsg({ type: 'err', text: err instanceof Error ? err.message : 'Failed to update' })
    } finally {
      setProfileSaving(false)
    }
  }

  const handlePasswordChange = async () => {
    setPwMsg(null)
    if (newPassword.length < 8) {
      setPwMsg({ type: 'err', text: 'New password must be at least 8 characters' })
      return
    }
    if (newPassword !== confirmPassword) {
      setPwMsg({ type: 'err', text: 'Passwords do not match' })
      return
    }
    setPwSaving(true)
    try {
      await apiFetch('/api/v1/auth/password', {
        method: 'PATCH',
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      })
      setPwMsg({ type: 'ok', text: 'Password changed' })
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setTimeout(() => setPwMsg(null), 3000)
    } catch (err) {
      setPwMsg({ type: 'err', text: err instanceof Error ? err.message : 'Failed to change password' })
    } finally {
      setPwSaving(false)
    }
  }

  const inputClass =
    'w-full rounded-lg border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 ' +
    'placeholder:text-neutral-400 dark:placeholder:text-neutral-500 outline-none focus:border-accent-600 disabled:opacity-50 transition-colors'

  const isOAuthOnly = user.provider !== 'email'

  return (
    <Section
      icon={CircleUser}
      title="Account"
      description="Your profile and login credentials."
    >
      {/* Profile */}
      <div className="space-y-3">
        <div>
          <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Email</label>
          <input
            type="text"
            value={user.email}
            disabled
            className={`${inputClass} opacity-60 cursor-not-allowed`}
          />
        </div>

        <div>
          <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Display name</label>
          <input
            type="text"
            value={displayName}
            onChange={e => { setDisplayName(e.target.value); setProfileMsg(null) }}
            placeholder="Your name"
            className={inputClass}
          />
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleProfileSave}
            disabled={!profileDirty || profileSaving}
            className="rounded-md bg-accent-700 px-3 py-1.5 text-sm text-white hover:bg-accent-500 disabled:opacity-40"
          >
            {profileSaving ? 'Saving...' : 'Update profile'}
          </button>
          {profileMsg && (
            <span className={`flex items-center gap-1 text-xs ${profileMsg.type === 'ok' ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
              {profileMsg.type === 'ok' ? <Check size={12} /> : <AlertCircle size={12} />}
              {profileMsg.text}
            </span>
          )}
        </div>
      </div>

      {/* Password change — only for email-based accounts */}
      {!isOAuthOnly && (
        <>
          <div className="border-t border-neutral-200 dark:border-neutral-700 mt-4 pt-4">
            <h3 className="text-xs font-semibold text-neutral-700 dark:text-neutral-300 mb-3">Change password</h3>
            <div className="space-y-3 max-w-sm">
              <div>
                <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Current password</label>
                <input
                  type="password"
                  value={currentPassword}
                  onChange={e => { setCurrentPassword(e.target.value); setPwMsg(null) }}
                  className={inputClass}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">New password</label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={e => { setNewPassword(e.target.value); setPwMsg(null) }}
                  placeholder="At least 8 characters"
                  className={inputClass}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Confirm new password</label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={e => { setConfirmPassword(e.target.value); setPwMsg(null) }}
                  className={inputClass}
                />
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={handlePasswordChange}
                  disabled={!currentPassword || !newPassword || !confirmPassword || pwSaving}
                  className="rounded-md bg-accent-700 px-3 py-1.5 text-sm text-white hover:bg-accent-500 disabled:opacity-40"
                >
                  {pwSaving ? 'Changing...' : 'Change password'}
                </button>
                {pwMsg && (
                  <span className={`flex items-center gap-1 text-xs ${pwMsg.type === 'ok' ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                    {pwMsg.type === 'ok' ? <Check size={12} /> : <AlertCircle size={12} />}
                    {pwMsg.text}
                  </span>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </Section>
  )
}
