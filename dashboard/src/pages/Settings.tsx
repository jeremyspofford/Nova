import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Bot, Sliders, Radio, Activity, Gauge, ShieldCheck, Globe, Shield, Palette, FileCode, MessageSquare } from 'lucide-react'
import { getPlatformConfig, updatePlatformConfig, type PlatformConfigEntry } from '../api'
import { Section, ConfigField, useConfigValue } from './settings/shared'
import { LLMRoutingSection } from './settings/LLMRoutingSection'
import { ProviderStatusSection } from './settings/ProviderStatusSection'
import { ContextBudgetSection } from './settings/ContextBudgetSection'
import { AdminSecretSection } from './settings/AdminSecretSection'
import { RemoteAccessSection } from './settings/RemoteAccessSection'
import { ChatIntegrationsSection } from './settings/ChatIntegrationsSection'
import { RecoverySection, SystemStatusSection } from './settings/RecoverySection'
import { AppearanceSection } from './settings/AppearanceSection'
import { NotificationsSection } from './settings/NotificationsSection'
import { DeveloperResourcesSection } from './settings/DeveloperResourcesSection'

// ── Sidebar nav items ─────────────────────────────────────────────────────────

const NAV_ITEMS = [
  { id: 'identity',          label: 'Identity',          icon: Bot },
  { id: 'platform-defaults', label: 'Platform Defaults', icon: Sliders },
  { id: 'llm-routing',       label: 'LLM Routing',       icon: Radio },
  { id: 'providers',         label: 'Provider Status',    icon: Activity },
  { id: 'context-budgets',   label: 'Context Budgets',    icon: Gauge },
  { id: 'admin-secret',      label: 'Admin Secret',       icon: ShieldCheck },
  { id: 'remote-access',     label: 'Remote Access',      icon: Globe },
  { id: 'chat-integrations', label: 'Chat Integrations',  icon: MessageSquare },
  { id: 'recovery',          label: 'Recovery & Services', icon: Shield },
  { id: 'system-status',     label: 'System Status',      icon: Activity },
  { id: 'appearance',        label: 'Appearance',         icon: Palette },
  { id: 'notifications',     label: 'Notifications',      icon: Radio },
  { id: 'developer',         label: 'Developer',          icon: FileCode },
]

function SettingsNav({ activeId }: { activeId: string }) {
  const scrollTo = (id: string) => {
    document.getElementById(`section-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <nav className="space-y-0.5">
      {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          onClick={() => scrollTo(id)}
          className={`w-full flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors text-left ${
            activeId === id
              ? 'bg-accent-700/10 text-accent-700 dark:bg-accent-400/10 dark:text-accent-400'
              : 'text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-800'
          }`}
        >
          <Icon size={13} className="shrink-0" />
          <span className="truncate">{label}</span>
        </button>
      ))}
    </nav>
  )
}

// ── Intersection observer for active section tracking ─────────────────────────

function useActiveSection() {
  const [activeId, setActiveId] = useState(NAV_ITEMS[0].id)
  const observerRef = useRef<IntersectionObserver | null>(null)

  useEffect(() => {
    observerRef.current = new IntersectionObserver(
      (entries) => {
        // Find the topmost visible section
        const visible = entries
          .filter(e => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible.length > 0) {
          const id = visible[0].target.id.replace('section-', '')
          setActiveId(id)
        }
      },
      { rootMargin: '-80px 0px -60% 0px', threshold: 0 },
    )

    const sections = document.querySelectorAll('[id^="section-"]')
    sections.forEach(s => observerRef.current?.observe(s))

    return () => observerRef.current?.disconnect()
  }, [])

  return activeId
}

// ── Settings page ─────────────────────────────────────────────────────────────

export function Settings() {
  const qc = useQueryClient()
  const activeId = useActiveSection()

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
    <div className="px-4 py-6 sm:px-6 flex gap-6">
      {/* Sidebar nav — hidden on small screens */}
      <aside className="hidden lg:block w-48 shrink-0">
        <div className="sticky top-6">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-neutral-400 dark:text-neutral-500 mb-2 px-2.5">Settings</p>
          <SettingsNav activeId={activeId} />
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 min-w-0 space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">Platform Settings</h1>
          <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
            Runtime configuration for this Nova instance. Changes take effect immediately —
            no restart required.
          </p>
        </div>

        {/* ── Nova Identity ─────────────────────────────────────────────────── */}
        <Section icon={Bot} title="Nova Identity" description="How Nova presents itself. Changes appear in the next Chat session." id="section-identity">
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

        {/* ── Platform Defaults ─────────────────────────────────────────────── */}
        <Section icon={Sliders} title="Platform Defaults" description="Fallback values used when a task or agent has no explicit configuration." id="section-platform-defaults">
          <ConfigField label="Task history retention (days)" configKey="task_history_retention_days" value={retentionDays} placeholder="0 (keep forever)" description="Automatically delete completed/failed/cancelled tasks older than this many days. Set to 0 or leave blank to keep forever. Common values: 7, 30, 60, 90." onSave={handleSave} saving={saveMutation.isPending} />
        </Section>

        <div id="section-llm-routing"><LLMRoutingSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} /></div>
        <div id="section-providers"><ProviderStatusSection /></div>
        <div id="section-context-budgets"><ContextBudgetSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} /></div>
        <div id="section-admin-secret"><AdminSecretSection /></div>
        <div id="section-remote-access"><RemoteAccessSection /></div>
        <div id="section-chat-integrations"><ChatIntegrationsSection /></div>
        <div id="section-recovery"><RecoverySection /></div>
        <div id="section-system-status"><SystemStatusSection /></div>
        <div id="section-appearance"><AppearanceSection /></div>
        <div id="section-notifications"><NotificationsSection /></div>
        <div id="section-developer"><DeveloperResourcesSection /></div>

        {saveMutation.isError && (
          <p className="text-sm text-red-600 dark:text-red-400">{String(saveMutation.error)}</p>
        )}
      </div>
    </div>
  )
}
