import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Bot, Wrench, Palette, Users, Bug, Database, Lock,
  CircleUser, Shield, Radio as RadioIcon, Globe, MessageSquare,
  FileCode, Layers, Gauge, Activity, RotateCcw, HeartPulse, Bell,
} from 'lucide-react'
import { getPlatformConfig, updatePlatformConfig, type PlatformConfigEntry } from '../api'
import { PageHeader } from '../components/layout/PageHeader'
import { Section, Button, ConfirmDialog, Toast } from '../components/ui'
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
import { ToolPermissionsSection } from './settings/ToolPermissionsSection'
import { DebugSection } from './settings/DebugSection'
import { UsersSection } from './settings/UsersSection'
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
      { id: 'appearance', label: 'Appearance', icon: Palette },
      { id: 'account', label: 'Account', icon: CircleUser },
    ],
  },
  {
    label: 'Security',
    items: [
      { id: 'users', label: 'Users', icon: Users },
      { id: 'trusted-networks', label: 'Trusted Networks', icon: Lock },
      { id: 'guest-access', label: 'Guest Access', icon: Shield },
    ],
  },
  {
    label: 'AI & Pipeline',
    items: [
      { id: 'llm-routing', label: 'LLM Routing', icon: RadioIcon },
      { id: 'provider-status', label: 'Provider Status', icon: Activity },
      { id: 'pipeline-models', label: 'Pipeline Models', icon: Layers },
      { id: 'context-budgets', label: 'Context Budgets', icon: Gauge },
      { id: 'tool-permissions', label: 'Tool Permissions', icon: Wrench },
    ],
  },
  {
    label: 'Connections',
    items: [
      { id: 'remote-access', label: 'Remote Access', icon: Globe },
      { id: 'chat-integrations', label: 'Chat Integrations', icon: MessageSquare },
      { id: 'notifications', label: 'Notifications', icon: Bell },
    ],
  },
  {
    label: 'System',
    items: [
      { id: 'setup-wizard', label: 'Setup Wizard', icon: RotateCcw },
      { id: 'developer-tools', label: 'Developer Tools', icon: FileCode },
      { id: 'debug', label: 'Debug', icon: Bug },
      { id: 'data', label: 'Data', icon: Database },
      { id: 'recovery', label: 'Recovery', icon: HeartPulse },
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

// ── Setup Wizard re-run ──────────────────────────────────────────────────────

function SetupWizardSection({ onSave }: { onSave: (key: string, value: string) => void }) {
  const [launching, setLaunching] = useState(false)

  return (
    <Section
      icon={RotateCcw}
      title="Setup Wizard"
      description="Re-run the guided setup to change your inference engine, model selection, or other initial configuration."
    >
      <div className="flex items-center gap-4">
        <Button
          variant="outline"
          size="sm"
          loading={launching}
          onClick={() => {
            setLaunching(true)
            onSave('onboarding.completed', 'false')
            // Brief delay so the config write lands before navigation
            setTimeout(() => {
              window.location.href = '/onboarding'
            }, 300)
          }}
        >
          Re-run Setup Wizard
        </Button>
        <span className="text-caption text-content-tertiary">
          Opens the onboarding flow to reconfigure hardware detection, engine, and model.
        </span>
      </div>
    </Section>
  )
}

// ── Data management ─────────────────────────────────────────────────────────

function DataManagementSection() {
  const qc = useQueryClient()
  const [confirmTarget, setConfirmTarget] = useState<'friction' | 'tasks' | null>(null)
  const [toast, setToast] = useState<{ variant: 'success' | 'error'; message: string } | null>(null)

  const clearFriction = useMutation({
    mutationFn: async () => {
      const { bulkDeleteFrictionEntries } = await import('../api')
      return bulkDeleteFrictionEntries()
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['friction'] })
      qc.invalidateQueries({ queryKey: ['friction-stats'] })
      setConfirmTarget(null)
      setToast({ variant: 'success', message: `Cleared ${data.deleted} friction entries` })
    },
    onError: (e) => { setConfirmTarget(null); setToast({ variant: 'error', message: String(e) }) },
  })

  const clearTasks = useMutation({
    mutationFn: async () => {
      const { bulkDeletePipelineTasks } = await import('../api')
      return bulkDeletePipelineTasks()
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['pipeline-tasks'] })
      setConfirmTarget(null)
      setToast({ variant: 'success', message: `Cleared ${data.deleted} pipeline tasks` })
    },
    onError: (e) => { setConfirmTarget(null); setToast({ variant: 'error', message: String(e) }) },
  })

  return (
    <Section icon={Database} title="Data" description="Clear accumulated data. Active/queued tasks are never deleted.">
      <div className="space-y-3">
        <div className="flex items-center justify-between py-2">
          <div>
            <p className="text-compact text-content-primary">Friction Logs</p>
            <p className="text-caption text-content-tertiary">Delete all friction log entries and screenshots.</p>
          </div>
          <Button variant="danger" size="sm" onClick={() => setConfirmTarget('friction')}>Clear All</Button>
        </div>
        <div className="flex items-center justify-between py-2">
          <div>
            <p className="text-compact text-content-primary">Pipeline Task History</p>
            <p className="text-caption text-content-tertiary">Delete all completed, failed, and cancelled tasks.</p>
          </div>
          <Button variant="danger" size="sm" onClick={() => setConfirmTarget('tasks')}>Clear All</Button>
        </div>
      </div>

      <ConfirmDialog
        open={confirmTarget === 'friction'}
        title="Clear all friction logs?"
        description="This will permanently delete all friction log entries and their screenshots."
        confirmLabel="Clear All"
        destructive
        onConfirm={() => clearFriction.mutate()}
        onClose={() => setConfirmTarget(null)}
      />
      <ConfirmDialog
        open={confirmTarget === 'tasks'}
        title="Clear pipeline task history?"
        description="This will permanently delete all completed, failed, and cancelled pipeline tasks. Active and queued tasks will not be affected."
        confirmLabel="Clear All"
        destructive
        onConfirm={() => clearTasks.mutate()}
        onClose={() => setConfirmTarget(null)}
      />
      {toast && (
        <Toast variant={toast.variant} message={toast.message} onDismiss={() => setToast(null)} />
      )}
    </Section>
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
        <div ref={setContentRef} className="flex-1 min-w-0 space-y-6 [&>div]:scroll-mt-24">

          {/* ── General ──────────────────────────────────────────────── */}

          <div id="identity">
            <Section icon={Bot} title="Nova Identity" description="How Nova presents itself. Changes appear in the next Chat session.">
              <ConfigField label="Name" configKey="nova.name" value={novaName} placeholder="Nova" description="Shown in the dashboard header and chat UI." onSave={handleSave} saving={saveMutation.isPending} />
              <ConfigField label="Greeting message" configKey="nova.greeting" value={novaGreeting} multiline rows={3} placeholder="Hello! I'm Nova..." description="The first message shown in the Chat page before the user types anything." onSave={handleSave} saving={saveMutation.isPending} />
              <ConfigField
                label="Persona / Soul"
                configKey="nova.persona"
                value={novaPersona}
                multiline
                rows={20}
                placeholder={
                  'e.g.\n' +
                  'You are a peer, not a servant. Your purpose is to provide the best possible ' +
                  'guidance, not the most comfortable answer. When the user\'s approach is flawed, ' +
                  'say so directly and explain why. Assume competence. Never patronize.'
                }
                description="Personality guidelines appended to every system prompt. Defines communication style, tone, and character."
                onSave={handleSave}
                saving={saveMutation.isPending}
              />
            </Section>
          </div>

          <div id="appearance">
            <AppearanceSection />
          </div>

          {isAuthenticated && (
            <div id="account">
              <AccountSection />
            </div>
          )}

          {/* ── Security ──────────────────────────────────────────────── */}

          <div id="users">
            <UsersSection />
          </div>

          <div id="trusted-networks">
            <TrustedNetworksSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />
          </div>

          <div id="guest-access">
            <GuestAccessSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />
          </div>

          {/* ── AI & Pipeline ─────────────────────────────────────────── */}

          <div id="llm-routing">
            <LLMRoutingSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />
          </div>

          <div id="provider-status">
            <ProviderStatusSection />
          </div>

          <div id="pipeline-models">
            <PipelineModelsSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />
          </div>

          <div id="context-budgets">
            <ContextBudgetSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />
          </div>

          <div id="tool-permissions">
            <ToolPermissionsSection />
          </div>

          {/* ── Connections ──────────────────────────────────────────── */}

          <div id="remote-access">
            <RemoteAccessSection />
          </div>

          <div id="chat-integrations">
            <ChatIntegrationsSection />
          </div>

          <div id="notifications">
            <NotificationsSection />
          </div>

          {/* ── System ───────────────────────────────────────────────── */}

          <div id="setup-wizard">
            <SetupWizardSection onSave={handleSave} />
          </div>

          <div id="developer-tools">
            <DeveloperResourcesSection />
          </div>

          <div id="debug">
            <DebugSection />
          </div>

          <div id="data">
            <DataManagementSection />
          </div>

          <div id="recovery">
            <RecoverySection />
          </div>

        </div>
      </div>

      {saveMutation.isError && (
        <p className="mt-4 text-compact text-danger">{String(saveMutation.error)}</p>
      )}
    </div>
  )
}
