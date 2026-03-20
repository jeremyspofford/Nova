import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Bot, Sliders, Cpu, Plug, Wrench, Palette,
  CircleUser, Shield, Radio as RadioIcon, Globe, MessageSquare,
  FileCode, Layers, Gauge, Activity,
} from 'lucide-react'
import { getPlatformConfig, updatePlatformConfig, type PlatformConfigEntry } from '../api'
import { PageHeader } from '../components/layout/PageHeader'
import { Section } from '../components/ui'
import { ConfigField, useConfigValue } from './settings/shared'
import { LLMRoutingSection } from './settings/LLMRoutingSection'
import { ProviderStatusSection } from './settings/ProviderStatusSection'
import { ContextBudgetSection } from './settings/ContextBudgetSection'
import { RemoteAccessSection } from './settings/RemoteAccessSection'
import { ChatIntegrationsSection } from './settings/ChatIntegrationsSection'
import { RecoverySection } from './settings/RecoverySection'
import { AppearanceSection } from './settings/AppearanceSection'
import { PipelineModelsSection } from './settings/PipelineModelsSection'
import { NotificationsSection } from './settings/NotificationsSection'
import { TrustedNetworksSection } from './settings/TrustedNetworksSection'
import { DeveloperResourcesSection } from './settings/DeveloperResourcesSection'
import { AccountSection } from './settings/AccountSection'
import { GuestAccessSection } from './settings/GuestAccessSection'
import { LocalInferenceSection } from './settings/LocalInferenceSection'
import { ToolPermissionsSection } from './settings/ToolPermissionsSection'
import { useAuth } from '../stores/auth-store'
import { Skeleton } from '../components/ui'

// ── Sidebar navigation structure ─────────────────────────────────────────────

interface NavItem {
  id: string
  label: string
  icon: React.ElementType
}

interface NavGroup {
  label: string
  items: NavItem[]
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: 'General',
    items: [
      { id: 'identity', label: 'Nova Identity', icon: Bot },
      { id: 'account', label: 'Account', icon: CircleUser },
      { id: 'trusted-networks', label: 'Trusted Networks', icon: Shield },
      { id: 'guest-access', label: 'Guest Access', icon: Shield },
    ],
  },
  {
    label: 'AI & Models',
    items: [
      { id: 'local-inference', label: 'Local Inference', icon: Cpu },
      { id: 'llm-routing', label: 'LLM Routing', icon: RadioIcon },
      { id: 'provider-status', label: 'Provider Status', icon: Activity },
      { id: 'context-budgets', label: 'Context Budgets', icon: Gauge },
      { id: 'pipeline-models', label: 'Pipeline Models', icon: Layers },
    ],
  },
  {
    label: 'Capabilities',
    items: [
      { id: 'tool-permissions', label: 'Tool Permissions', icon: Wrench },
    ],
  },
  {
    label: 'Connections',
    items: [
      { id: 'remote-access', label: 'Remote Access', icon: Globe },
      { id: 'chat-integrations', label: 'Chat Integrations', icon: MessageSquare },
    ],
  },
  {
    label: 'System',
    items: [
      { id: 'developer-resources', label: 'Developer Resources', icon: FileCode },
      { id: 'notifications', label: 'Notifications', icon: RadioIcon },
      { id: 'recovery', label: 'Recovery & Services', icon: Shield },
    ],
  },
  {
    label: 'Appearance',
    items: [
      { id: 'appearance', label: 'Theme & Colors', icon: Palette },
    ],
  },
]

const ALL_SECTION_IDS = NAV_GROUPS.flatMap(g => g.items.map(i => i.id))

// ── Active section tracking via IntersectionObserver ─────────────────────────

function useActiveSection() {
  const [active, setActive] = useState(() => {
    const hash = window.location.hash.replace('#', '')
    return ALL_SECTION_IDS.includes(hash) ? hash : ALL_SECTION_IDS[0]
  })

  const observerRef = useRef<IntersectionObserver | null>(null)

  useEffect(() => {
    const onHash = () => {
      const h = window.location.hash.replace('#', '')
      if (ALL_SECTION_IDS.includes(h)) {
        setActive(h)
        const el = document.getElementById(h)
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    }
    window.addEventListener('hashchange', onHash)

    // Scroll to initial hash
    if (window.location.hash) {
      setTimeout(onHash, 100)
    }

    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const setupObserver = useCallback((container: HTMLDivElement | null) => {
    if (observerRef.current) {
      observerRef.current.disconnect()
    }
    if (!container) return

    observerRef.current = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && entry.intersectionRatio > 0.2) {
            const id = entry.target.id
            if (ALL_SECTION_IDS.includes(id)) {
              setActive(id)
              // Update hash silently without triggering scroll
              history.replaceState(null, '', `#${id}`)
            }
          }
        }
      },
      {
        root: null,
        rootMargin: '-80px 0px -60% 0px',
        threshold: 0.2,
      },
    )

    ALL_SECTION_IDS.forEach(id => {
      const el = document.getElementById(id)
      if (el) observerRef.current!.observe(el)
    })

    return () => observerRef.current?.disconnect()
  }, [])

  return { active, setActive, setupObserver }
}

// ── Sidebar nav component ────────────────────────────────────────────────────

function SettingsSidebar({ active, isAuthenticated }: { active: string; isAuthenticated: boolean }) {
  return (
    <nav className="w-48 shrink-0 hidden lg:block sticky top-20 self-start max-h-[calc(100vh-6rem)] overflow-y-auto">
      <div className="space-y-5">
        {NAV_GROUPS.map(group => {
          const items = group.items.filter(item => {
            // Hide account if not authenticated
            if (item.id === 'account' && !isAuthenticated) return false
            return true
          })
          if (items.length === 0) return null

          return (
            <div key={group.label}>
              <p className="text-micro font-semibold uppercase tracking-wider text-content-tertiary mb-2 px-2">
                {group.label}
              </p>
              <div className="space-y-0.5">
                {items.map(item => {
                  const Icon = item.icon
                  const isActive = active === item.id
                  return (
                    <a
                      key={item.id}
                      href={`#${item.id}`}
                      className={`flex items-center gap-2 rounded-sm px-2 py-1.5 text-caption font-medium transition-colors ${
                        isActive
                          ? 'bg-surface-elevated text-accent'
                          : 'text-content-secondary hover:text-content-primary hover:bg-surface-card-hover'
                      }`}
                    >
                      <Icon size={14} className="shrink-0" />
                      {item.label}
                    </a>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </nav>
  )
}

// ── Settings page ────────────────────────────────────────────────────────────

export function Settings() {
  const qc = useQueryClient()
  const { active, setupObserver } = useActiveSection()
  const { isAuthenticated } = useAuth()
  const contentRef = useRef<HTMLDivElement | null>(null)

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

  // Setup observer when content mounts
  const setContentRef = useCallback((el: HTMLDivElement | null) => {
    contentRef.current = el
    setupObserver(el)
  }, [setupObserver])

  if (isLoading) return (
    <div className="px-4 py-6 sm:px-6 space-y-6">
      <PageHeader title="Platform Settings" description="Loading configuration..." />
      <Skeleton lines={8} />
    </div>
  )

  if (error) return (
    <div className="px-4 py-6 sm:px-6">
      <PageHeader title="Platform Settings" />
      <p className="text-compact text-danger">{String(error)}</p>
    </div>
  )

  return (
    <div className="px-4 py-6 sm:px-6">
      <PageHeader
        title="Platform Settings"
        description="Runtime configuration for this Nova instance. Changes take effect immediately."
      />

      <div className="flex gap-8">
        {/* Sidebar */}
        <SettingsSidebar active={active} isAuthenticated={isAuthenticated} />

        {/* Content */}
        <div ref={setContentRef} className="flex-1 min-w-0 space-y-6">

          {/* ── General ──────────────────────────────────────────────── */}

          <div id="identity">
            <Section icon={Bot} title="Nova Identity" description="How Nova presents itself. Changes appear in the next Chat session.">
              <ConfigField label="Name" configKey="nova.name" value={novaName} placeholder="Nova" description="Shown in the dashboard header and chat UI." onSave={handleSave} saving={saveMutation.isPending} />
              <ConfigField label="Greeting message" configKey="nova.greeting" value={novaGreeting} placeholder="Hello! I'm Nova..." description="The first message shown in the Chat page before the user types anything." onSave={handleSave} saving={saveMutation.isPending} />
              <ConfigField
                label="Persona / Soul"
                configKey="nova.persona"
                value={novaPersona}
                multiline
                placeholder={
                  'e.g.\n' +
                  'You are Nova, a focused engineering assistant. You are direct and precise -- ' +
                  'you never pad responses with affirmations or filler phrases. You prefer ' +
                  'showing code over explaining it. When you are uncertain, you say so plainly. ' +
                  'You treat the user as a peer engineer, not a customer.'
                }
                description="Personality guidelines appended to every system prompt. Defines communication style, tone, and character."
                onSave={handleSave}
                saving={saveMutation.isPending}
              />
            </Section>
          </div>

          {isAuthenticated && (
            <div id="account">
              <AccountSection />
            </div>
          )}

          <div id="trusted-networks">
            <TrustedNetworksSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />
          </div>

          <div id="guest-access">
            <GuestAccessSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />
          </div>

          {/* ── AI & Models ──────────────────────────────────────────── */}

          <div id="local-inference">
            <LocalInferenceSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />
          </div>

          <div id="llm-routing">
            <LLMRoutingSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />
          </div>

          <div id="tool-permissions">
            <ToolPermissionsSection />
          </div>

          <div id="provider-status">
            <ProviderStatusSection />
          </div>

          <div id="context-budgets">
            <ContextBudgetSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />
          </div>

          <div id="pipeline-models">
            <PipelineModelsSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />
          </div>

          {/* ── Connections ──────────────────────────────────────────── */}

          <div id="remote-access">
            <RemoteAccessSection />
          </div>

          <div id="chat-integrations">
            <ChatIntegrationsSection />
          </div>

          {/* ── System ───────────────────────────────────────────────── */}

          <div id="developer-resources">
            <DeveloperResourcesSection />
          </div>

          <div id="notifications">
            <NotificationsSection />
          </div>

          <div id="recovery">
            <RecoverySection />
          </div>

          {/* ── Appearance ───────────────────────────────────────────── */}

          <div id="appearance">
            <AppearanceSection />
          </div>

        </div>
      </div>

      {saveMutation.isError && (
        <p className="mt-4 text-compact text-danger">{String(saveMutation.error)}</p>
      )}
    </div>
  )
}
