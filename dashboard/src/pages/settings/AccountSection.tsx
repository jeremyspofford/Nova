import { useState } from 'react'
import { CircleUser, Check, AlertCircle } from 'lucide-react'
import { useAuth } from '../../stores/auth-store'
import { apiFetch } from '../../api'
import { Section, Button, Input } from '../../components/ui'

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

  const isOAuthOnly = user.provider === 'google'

  return (
    <Section
      icon={CircleUser}
      title="Account"
      description="Your profile and login credentials."
    >
      {/* Profile */}
      <div className="space-y-3">
        <Input
          label="Email"
          value={user.email}
          disabled
        />
        <Input
          label="Display name"
          value={displayName}
          onChange={e => { setDisplayName(e.target.value); setProfileMsg(null) }}
          placeholder="Your name"
        />

        <div className="flex items-center gap-3">
          <Button
            onClick={handleProfileSave}
            disabled={!profileDirty}
            loading={profileSaving}
            size="sm"
          >
            Update profile
          </Button>
          {profileMsg && (
            <span className={`flex items-center gap-1 text-caption ${profileMsg.type === 'ok' ? 'text-success' : 'text-danger'}`}>
              {profileMsg.type === 'ok' ? <Check size={12} /> : <AlertCircle size={12} />}
              {profileMsg.text}
            </span>
          )}
        </div>
      </div>

      {/* Password change -- only for email-based accounts */}
      {!isOAuthOnly && (
        <div className="border-t border-border-subtle mt-4 pt-4">
          <h3 className="text-caption font-semibold text-content-primary mb-3">Change password</h3>
          <div className="space-y-3 max-w-sm">
            <Input
              label="Current password"
              type="password"
              value={currentPassword}
              onChange={e => { setCurrentPassword(e.target.value); setPwMsg(null) }}
            />
            <Input
              label="New password"
              type="password"
              value={newPassword}
              onChange={e => { setNewPassword(e.target.value); setPwMsg(null) }}
              placeholder="At least 8 characters"
            />
            <Input
              label="Confirm new password"
              type="password"
              value={confirmPassword}
              onChange={e => { setConfirmPassword(e.target.value); setPwMsg(null) }}
            />

            <div className="flex items-center gap-3">
              <Button
                onClick={handlePasswordChange}
                disabled={!currentPassword || !newPassword || !confirmPassword}
                loading={pwSaving}
                size="sm"
              >
                Change password
              </Button>
              {pwMsg && (
                <span className={`flex items-center gap-1 text-caption ${pwMsg.type === 'ok' ? 'text-success' : 'text-danger'}`}>
                  {pwMsg.type === 'ok' ? <Check size={12} /> : <AlertCircle size={12} />}
                  {pwMsg.text}
                </span>
              )}
            </div>
          </div>
        </div>
      )}
    </Section>
  )
}
