import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { User, Brain, Heart, Pencil, X, Check, Loader2 } from 'lucide-react'
import { apiFetch } from '../api'

interface ProfileEntity {
  id: string
  name: string
  confidence: number
  importance: number
  learned_at: string | null
  last_seen: string | null
  source: string
}

interface ProfileFact {
  id: string
  content: string
  confidence: number
  learned_at: string | null
  source: string
}

interface UserProfileData {
  entities: ProfileEntity[]
  facts: ProfileFact[]
  preferences: ProfileFact[]
}

function ConfidenceBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 80 ? 'text-emerald-400' : pct >= 50 ? 'text-amber-400' : 'text-red-400'
  return <span className={`text-micro ${color}`}>{pct}%</span>
}

function ProfileItem({ item, onCorrect }: { item: ProfileFact; onCorrect: (id: string, content: string) => void }) {
  return (
    <div className="flex items-start justify-between gap-2 py-2 border-b border-border-subtle/30 last:border-0">
      <div className="flex-1 min-w-0">
        <p className="text-compact text-content-primary">{item.content}</p>
        <p className="text-micro text-content-tertiary mt-0.5">
          <ConfidenceBadge value={item.confidence} />
          {item.learned_at && (
            <span className="ml-2">{new Date(item.learned_at).toLocaleDateString()}</span>
          )}
        </p>
      </div>
      <button
        onClick={() => onCorrect(item.id, item.content)}
        className="shrink-0 p-1 rounded-xs text-content-tertiary hover:text-content-secondary hover:bg-surface-elevated transition-colors"
        title="Correct this"
      >
        <Pencil size={12} />
      </button>
    </div>
  )
}

function CorrectionModal({ engramId, currentContent, onClose, onSuccess }: { engramId: string; currentContent: string; onClose: () => void; onSuccess: () => void }) {
  const [text, setText] = useState(currentContent)
  const mutation = useMutation({
    mutationFn: () => apiFetch<{ corrected: number }>('/mem/api/v1/engrams/correct', {
      method: 'POST',
      body: JSON.stringify({ correction: text, engram_id: engramId }),
    }),
    onSuccess: () => { onSuccess(); onClose() },
  })

  const hasChanged = text.trim() !== currentContent.trim()

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-surface-card border border-border-subtle rounded-lg p-4 w-full max-w-md shadow-xl">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-body font-semibold text-content-primary">Correct this memory</h3>
          <button onClick={onClose} className="text-content-tertiary hover:text-content-secondary"><X size={16} /></button>
        </div>
        <p className="text-micro text-content-tertiary mb-2">Edit the text below or rewrite it. The old version will be superseded.</p>
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          className="w-full rounded-md border border-border-subtle bg-surface-elevated text-content-primary p-2 text-compact resize-none focus:outline-none focus:ring-1 focus:ring-accent-primary"
          rows={3}
          autoFocus
        />
        <div className="flex justify-end gap-2 mt-3">
          <button onClick={onClose} className="px-3 py-1.5 text-compact text-content-secondary hover:text-content-primary">Cancel</button>
          <button
            onClick={() => mutation.mutate()}
            disabled={!text.trim() || !hasChanged || mutation.isPending}
            className="px-3 py-1.5 text-compact bg-accent-primary text-white rounded-md hover:bg-accent-primary/90 disabled:opacity-50 flex items-center"
          >
            {mutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
            <span className="ml-1">Apply</span>
          </button>
        </div>
        {mutation.isError && (
          <p className="text-micro text-red-400 mt-2">Failed to apply correction</p>
        )}
      </div>
    </div>
  )
}

function OnboardingWizard({ onComplete }: { onComplete: () => void }) {
  const [name, setName] = useState('')
  const [role, setRole] = useState('')
  const [interests, setInterests] = useState('')
  const [location, setLocation] = useState('')

  const mutation = useMutation({
    mutationFn: () => {
      const facts = [
        name.trim() && { attribute: 'name', value: name.trim() },
        role.trim() && { attribute: 'role', value: role.trim() },
        interests.trim() && { attribute: 'interests', value: interests.trim() },
        location.trim() && { attribute: 'location', value: location.trim() },
      ].filter(Boolean)

      return apiFetch('/mem/api/v1/engrams/user-profile/bootstrap', {
        method: 'POST',
        body: JSON.stringify({ facts }),
      })
    },
    onSuccess: onComplete,
  })

  const hasAny = name.trim() || role.trim() || interests.trim() || location.trim()

  return (
    <div className="bg-surface-card border border-border-subtle rounded-lg p-6">
      <div className="text-center mb-6">
        <User size={32} className="mx-auto mb-3 text-teal-400" />
        <h2 className="text-body font-semibold text-content-primary">Welcome! Tell Nova about yourself</h2>
        <p className="text-compact text-content-secondary mt-1">
          This helps Nova personalize responses. All fields are optional.
        </p>
      </div>

      <div className="space-y-4 max-w-md mx-auto">
        <div>
          <label className="block text-compact font-medium text-content-secondary mb-1">Name</label>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="What should Nova call you?"
            className="w-full rounded-md border border-border-subtle bg-surface-elevated text-content-primary p-2 text-compact focus:outline-none focus:ring-1 focus:ring-accent-primary"
          />
        </div>
        <div>
          <label className="block text-compact font-medium text-content-secondary mb-1">Role</label>
          <input
            value={role}
            onChange={e => setRole(e.target.value)}
            placeholder="What do you do?"
            className="w-full rounded-md border border-border-subtle bg-surface-elevated text-content-primary p-2 text-compact focus:outline-none focus:ring-1 focus:ring-accent-primary"
          />
        </div>
        <div>
          <label className="block text-compact font-medium text-content-secondary mb-1">Interests</label>
          <input
            value={interests}
            onChange={e => setInterests(e.target.value)}
            placeholder="What topics do you care about?"
            className="w-full rounded-md border border-border-subtle bg-surface-elevated text-content-primary p-2 text-compact focus:outline-none focus:ring-1 focus:ring-accent-primary"
          />
        </div>
        <div>
          <label className="block text-compact font-medium text-content-secondary mb-1">Location</label>
          <input
            value={location}
            onChange={e => setLocation(e.target.value)}
            placeholder="Where are you based?"
            className="w-full rounded-md border border-border-subtle bg-surface-elevated text-content-primary p-2 text-compact focus:outline-none focus:ring-1 focus:ring-accent-primary"
          />
        </div>
      </div>

      <div className="flex justify-center mt-6">
        <button
          onClick={() => mutation.mutate()}
          disabled={!hasAny || mutation.isPending}
          className="px-6 py-2 bg-accent-primary text-white rounded-md hover:bg-accent-primary/90 disabled:opacity-50 text-compact font-medium"
        >
          {mutation.isPending ? (
            <span className="flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Saving...</span>
          ) : (
            'Get started'
          )}
        </button>
      </div>

      {mutation.isError && (
        <p className="text-center text-micro text-red-400 mt-3">Failed to save profile. Try again.</p>
      )}
    </div>
  )
}

export function UserProfile() {
  const queryClient = useQueryClient()
  const [correcting, setCorrecting] = useState<{ id: string; content: string } | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['user-profile'],
    queryFn: () => apiFetch<UserProfileData>('/mem/api/v1/engrams/user-profile'),
    staleTime: 10_000,
  })

  if (isLoading) return (
    <div className="flex items-center justify-center h-64 text-content-tertiary">
      <Loader2 className="animate-spin mr-2" size={16} /> Loading profile...
    </div>
  )

  if (error) return (
    <div className="flex items-center justify-center h-64 text-red-400">
      Failed to load profile
    </div>
  )

  const profile = data!
  const isEmpty = !profile.entities.length && !profile.facts.length && !profile.preferences.length

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-heading-lg text-content-primary">What Nova Knows About You</h1>
        <p className="text-compact text-content-secondary mt-1">
          These are facts, entities, and preferences learned from your conversations.
        </p>
      </div>

      {isEmpty ? (
        <OnboardingWizard onComplete={() => queryClient.invalidateQueries({ queryKey: ['user-profile'] })} />
      ) : (
        <>
          {profile.entities.length > 0 && (
            <section>
              <h2 className="flex items-center gap-2 text-body font-semibold text-content-primary mb-2">
                <Brain size={16} className="text-teal-400" /> Entities ({profile.entities.length})
              </h2>
              <div className="bg-surface-card border border-border-subtle rounded-lg px-3">
                {profile.entities.map(e => (
                  <ProfileItem key={e.id} item={{ id: e.id, content: e.name, confidence: e.confidence, learned_at: e.learned_at, source: e.source }} onCorrect={(id, content) => setCorrecting({ id, content })} />
                ))}
              </div>
            </section>
          )}

          {profile.facts.length > 0 && (
            <section>
              <h2 className="flex items-center gap-2 text-body font-semibold text-content-primary mb-2">
                <User size={16} className="text-blue-400" /> Facts ({profile.facts.length})
              </h2>
              <div className="bg-surface-card border border-border-subtle rounded-lg px-3">
                {profile.facts.map(f => (
                  <ProfileItem key={f.id} item={f} onCorrect={(id, content) => setCorrecting({ id, content })} />
                ))}
              </div>
            </section>
          )}

          {profile.preferences.length > 0 && (
            <section>
              <h2 className="flex items-center gap-2 text-body font-semibold text-content-primary mb-2">
                <Heart size={16} className="text-emerald-400" /> Preferences ({profile.preferences.length})
              </h2>
              <div className="bg-surface-card border border-border-subtle rounded-lg px-3">
                {profile.preferences.map(p => (
                  <ProfileItem key={p.id} item={p} onCorrect={(id, content) => setCorrecting({ id, content })} />
                ))}
              </div>
            </section>
          )}
        </>
      )}

      {correcting && (
        <CorrectionModal
          engramId={correcting.id}
          currentContent={correcting.content}
          onClose={() => setCorrecting(null)}
          onSuccess={() => queryClient.invalidateQueries({ queryKey: ['user-profile'] })}
        />
      )}
    </div>
  )
}
