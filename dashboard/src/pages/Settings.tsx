import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Bot, Sliders, Cpu, Plug, Wrench, Palette } from 'lucide-react'
import { getPlatformConfig, updatePlatformConfig, type PlatformConfigEntry } from '../api'
import { Section, ConfigField, useConfigValue } from './settings/shared'
import { LLMRoutingSection } from './settings/LLMRoutingSection'
import { ProviderStatusSection } from './settings/ProviderStatusSection'
import { ContextBudgetSection } from './settings/ContextBudgetSection'
import { AdminSecretSection } from './settings/AdminSecretSection'
import { RemoteAccessSection } from './settings/RemoteAccessSection'
import { ChatIntegrationsSection } from './settings/ChatIntegrationsSection'
import { RecoverySection } from './settings/RecoverySection'
import { AppearanceSection } from './settings/AppearanceSection'
import { PipelineModelsSection } from './settings/PipelineModelsSection'
import { NotificationsSection } from './settings/NotificationsSection'
import { TrustedNetworksSection } from './settings/TrustedNetworksSection'
import { DeveloperResourcesSection } from './settings/DeveloperResourcesSection'
import { AccountSection } from './settings/AccountSection'
import { useAuth } from '../stores/auth-store'

// ── Category tabs ────────────────────────────────────────────────────────────

const CATEGORIES = [
  { key: 'general',     label: 'General',      icon: Sliders },
  { key: 'ai',          label: 'AI & Models',   icon: Cpu },
  { key: 'connections', label: 'Connections',    icon: Plug },
  { key: 'system',      label: 'System',         icon: Wrench },
  { key: 'appearance',  label: 'Appearance',     icon: Palette },
] as const

type CategoryKey = typeof CATEGORIES[number]['key']

const VALID_KEYS = new Set<string>(CATEGORIES.map(c => c.key))

function useActiveCategory(): [CategoryKey, (k: CategoryKey) => void] {
  const [active, setActive] = useState<CategoryKey>(() => {
    const hash = window.location.hash.replace('#', '')
    return VALID_KEYS.has(hash) ? hash as CategoryKey : 'general'
  })

  useEffect(() => {
    const onHash = () => {
      const h = window.location.hash.replace('#', '')
      setActive(VALID_KEYS.has(h) ? h as CategoryKey : 'general')
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const setCategory = (key: CategoryKey) => { window.location.hash = key }
  return [active, setCategory]
}

function CategoryTabs({ active, onChange }: { active: CategoryKey; onChange: (k: CategoryKey) => void }) {
  return (
    <div className="overflow-x-auto -mb-px">
      <div className="flex gap-1 min-w-max">
        {CATEGORIES.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => onChange(key)}
            className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
              active === key
                ? 'border-accent-600 text-accent-600 dark:border-accent-400 dark:text-accent-400'
                : 'border-transparent text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300 hover:border-neutral-300 dark:hover:border-neutral-600'
            }`}
          >
            <Icon size={15} />
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Settings page ────────────────────────────────────────────────────────────

export function Settings() {
  const qc = useQueryClient()
  const [activeCategory, setCategory] = useActiveCategory()
  const { isAuthenticated } = useAuth()

  const { data: entries = [], isLoading, error } = useQuery({
    queryKey: ['platform-config'],
    queryFn: getPlatformConfig,
    staleTime: 30_000,
  })

  const saveMutation = useMutation({
    mutationFn: ({ key, value }: { key: string; value: string }) =>
      updatePlatformConfig(key, value),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['platform-config'] })
      qc.invalidateQueries({ queryKey: ['nova-identity'] })
    },
  })

  const handleSave = (key: string, value: string) =>
    saveMutation.mutate({ key, value })

  const novaName    = useConfigValue(entries, 'nova.name', 'Nova')
  const novaPersona = useConfigValue(entries, 'nova.persona', '')
  const novaGreeting = useConfigValue(entries, 'nova.greeting', '')
  const retentionDays = useConfigValue(entries, 'task_history_retention_days', '')

  if (isLoading) return <div className="px-4 py-6 sm:px-6 text-sm text-neutral-500 dark:text-neutral-400">Loading…</div>
  if (error)     return <div className="px-4 py-6 sm:px-6 text-sm text-red-600 dark:text-red-400">{String(error)}</div>

  return (
    <div className="px-4 py-6 sm:px-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">Platform Settings</h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
          Runtime configuration for this Nova instance. Changes take effect immediately —
          no restart required.
        </p>
      </div>

      {/* Category tabs */}
      <div className="border-b border-neutral-200 dark:border-neutral-700">
        <CategoryTabs active={activeCategory} onChange={setCategory} />
      </div>

      {/* Tab content */}
      <div className="space-y-6">
        {activeCategory === 'general' && (
          <>
            {isAuthenticated && <AccountSection />}
            <Section icon={Bot} title="Nova Identity" description="How Nova presents itself. Changes appear in the next Chat session.">
              <ConfigField label="Name" configKey="nova.name" value={novaName} placeholder="Nova" description="Shown in the dashboard header and chat UI." onSave={handleSave} saving={saveMutation.isPending} />
              <ConfigField label="Greeting message" configKey="nova.greeting" value={novaGreeting} placeholder="Hello! I'm Nova…" description="The first message shown in the Chat page before the user types anything." onSave={handleSave} saving={saveMutation.isPending} />
              <ConfigField
                label="Persona / Soul"
                configKey="nova.persona"
                value={novaPersona}
                multiline
                placeholder={
                  'e.g.\n' +
                  'You are Nova, a focused engineering assistant. You are direct and precise — ' +
                  'you never pad responses with affirmations or filler phrases. You prefer ' +
                  'showing code over explaining it. When you are uncertain, you say so plainly. ' +
                  'You treat the user as a peer engineer, not a customer.'
                }
                description="Personality guidelines appended to every system prompt. Defines communication style, tone, and character. Distinct from the operational system prompt — this is the 'how you talk', not 'what you do'."
                onSave={handleSave}
                saving={saveMutation.isPending}
              />
            </Section>

            <Section icon={Sliders} title="Platform Defaults" description="Fallback values used when a task or agent has no explicit configuration.">
              <ConfigField label="Task history retention (days)" configKey="task_history_retention_days" value={retentionDays} placeholder="0 (keep forever)" description="Automatically delete completed/failed/cancelled tasks older than this many days. Set to 0 or leave blank to keep forever. Common values: 7, 30, 60, 90." onSave={handleSave} saving={saveMutation.isPending} />
            </Section>

            <AdminSecretSection />
          </>
        )}

        {activeCategory === 'ai' && (
          <>
            <LLMRoutingSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />
            <PipelineModelsSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />
            <ProviderStatusSection />
            <ContextBudgetSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />
          </>
        )}

        {activeCategory === 'connections' && (
          <>
            <RemoteAccessSection />
            <ChatIntegrationsSection />
          </>
        )}

        {activeCategory === 'system' && (
          <>
            <TrustedNetworksSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />
            <DeveloperResourcesSection />
            <NotificationsSection />
            <RecoverySection />
          </>
        )}

        {activeCategory === 'appearance' && (
          <AppearanceSection />
        )}
      </div>

      {saveMutation.isError && (
        <p className="text-sm text-red-600 dark:text-red-400">{String(saveMutation.error)}</p>
      )}
    </div>
  )
}
