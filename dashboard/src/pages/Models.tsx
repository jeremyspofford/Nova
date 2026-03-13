import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  discoverModels,
  getOllamaPulled,
  getOllamaStatus,
  pullOllamaModel,
  deleteOllamaModel,
  getProviderStatus,
} from '../api'
import type { ProviderModelList, OllamaPulledModel, OllamaStatus, ProviderStatus } from '../api'
import Card from '../components/Card'
import { RECOMMENDED_OLLAMA_MODELS, CLOUD_PROVIDER_ORDER } from '../constants'
import {
  RefreshCw, Trash2, Download, Check, HardDrive, Cloud, Loader2,
  AlertTriangle, ExternalLink, Server, X, Info, Play,
} from 'lucide-react'
import { formatBytes } from '../lib/format'
import { recoveryFetch } from '../api-recovery'
import {
  getBackendStatus, searchModels, switchModel, getRecommendedModels, getGPUStats,
  type BackendStatus, type ModelSearchResult, type RecommendedModel,
} from '../api-recovery'

// ── Helpers ──────────────────────────────────────────────────────────────────

const TYPE_BADGE: Record<string, { label: string; className: string }> = {
  local:        { label: 'Local',        className: 'bg-teal-100 dark:bg-teal-900/30 text-teal-700 dark:text-teal-400' },
  subscription: { label: 'Subscription', className: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400' },
  free:         { label: 'Free Tier',    className: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400' },
  paid:         { label: 'Paid API',     className: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400' },
}

const ONBOARDING_DISMISSED_KEY = 'nova_onboarding_dismissed'

// ── Main Component ───────────────────────────────────────────────────────────

export function Models() {
  const qc = useQueryClient()
  const [pullInput, setPullInput] = useState('')
  const [pullingModels, setPullingModels] = useState<Set<string>>(new Set())
  const [deletingModels, setDeletingModels] = useState<Set<string>>(new Set())
  const [categoryFilter, setCategoryFilter] = useState<string>('all')
  const [sizeFilter, setSizeFilter] = useState<number>(0) // 0 = show all
  const [onboardingDismissed, setOnboardingDismissed] = useState(
    () => localStorage.getItem(ONBOARDING_DISMISSED_KEY) === 'true'
  )

  // Queries
  const catalog = useQuery({
    queryKey: ['model-catalog'],
    queryFn: () => discoverModels(),
    staleTime: 60_000,
  })

  const pulled = useQuery({
    queryKey: ['ollama-pulled'],
    queryFn: () => getOllamaPulled().catch(() => [] as OllamaPulledModel[]),
    staleTime: 30_000,
  })

  const ollamaStatus = useQuery({
    queryKey: ['ollama-status'],
    queryFn: getOllamaStatus,
    staleTime: 15_000,
  })

  const providers = useQuery({
    queryKey: ['provider-status'],
    queryFn: getProviderStatus,
    staleTime: 30_000,
  })

  const backendStatus = useQuery({
    queryKey: ['inference-backend-status'],
    queryFn: getBackendStatus,
    staleTime: 5_000,
  })

  const recommended = useQuery({
    queryKey: ['recommended-models', backendStatus.data?.backend],
    queryFn: () => getRecommendedModels(backendStatus.data?.backend ?? undefined),
    enabled: !!backendStatus.data?.backend,
    staleTime: 60_000,
  })

  const gpuStats = useQuery({
    queryKey: ['gpu-stats'],
    queryFn: getGPUStats,
    refetchInterval: 10_000,
    enabled: (backendStatus.data?.backend ?? 'ollama') !== 'none',
  })

  const activeBackend = backendStatus.data?.backend ?? 'ollama'
  const backendState = backendStatus.data?.state ?? 'stopped'
  const isSwitching = backendState === 'switching'

  // Mutations
  const pullMutation = useMutation({
    mutationFn: pullOllamaModel,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ollama-pulled'] })
      qc.invalidateQueries({ queryKey: ['model-catalog'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteOllamaModel,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ollama-pulled'] })
      qc.invalidateQueries({ queryKey: ['model-catalog'] })
    },
  })

  const startOllama = useMutation({
    mutationFn: () =>
      recoveryFetch('/api/v1/recovery/inference/backend/ollama/start', { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ollama-pulled'] })
      qc.invalidateQueries({ queryKey: ['ollama-status'] })
      qc.invalidateQueries({ queryKey: ['model-catalog'] })
      qc.invalidateQueries({ queryKey: ['inference-backend-status'] })
    },
  })

  const [modelSearchQuery, setModelSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<ModelSearchResult[]>([])
  const [searching, setSearching] = useState(false)

  const switchModelMutation = useMutation({
    mutationFn: ({ backend, model }: { backend: string; model: string }) =>
      switchModel(backend, model),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['inference-backend-status'] })
      qc.invalidateQueries({ queryKey: ['model-catalog'] })
    },
  })

  const handleModelSearch = async () => {
    if (!modelSearchQuery.trim()) return
    setSearching(true)
    try {
      const results = await searchModels(modelSearchQuery, activeBackend)
      setSearchResults(results)
    } catch {
      setSearchResults([])
    } finally {
      setSearching(false)
    }
  }

  const handleSwitchModel = (model: string) => {
    if (!confirm(`Switch to ${model}? This restarts ${activeBackend} (~30-120s). Cloud providers remain available.`)) return
    switchModelMutation.mutate({ backend: activeBackend, model })
  }

  // Poll faster during model switch
  useEffect(() => {
    if (!isSwitching) return
    const interval = setInterval(() => {
      qc.invalidateQueries({ queryKey: ['inference-backend-status'] })
    }, 2000)
    return () => clearInterval(interval)
  }, [isSwitching, qc])

  // Handlers
  const handlePull = async (name: string) => {
    if (!name.trim()) return
    setPullingModels(s => new Set(s).add(name))
    try {
      await pullMutation.mutateAsync(name)
    } finally {
      setPullingModels(s => { const n = new Set(s); n.delete(name); return n })
    }
    setPullInput('')
  }

  const handleDelete = async (name: string) => {
    setDeletingModels(s => new Set(s).add(name))
    try {
      await deleteMutation.mutateAsync(name)
    } finally {
      setDeletingModels(s => { const n = new Set(s); n.delete(name); return n })
    }
  }

  const handleRefresh = () => {
    qc.invalidateQueries({ queryKey: ['model-catalog'] })
    qc.invalidateQueries({ queryKey: ['ollama-pulled'] })
    qc.invalidateQueries({ queryKey: ['ollama-status'] })
    qc.invalidateQueries({ queryKey: ['provider-status'] })
    // Force refresh by calling with refresh=true
    qc.fetchQuery({ queryKey: ['model-catalog'], queryFn: () => discoverModels(true) })
  }

  const dismissOnboarding = () => {
    localStorage.setItem(ONBOARDING_DISMISSED_KEY, 'true')
    setOnboardingDismissed(true)
  }

  // Derived state
  const pulledNames = new Set((pulled.data ?? []).map(m => m.name))
  const totalAvailable = (catalog.data ?? []).reduce((n, p) => n + (p.available ? p.models.length : 0), 0)
  const ollamaHealthy = ollamaStatus.data?.healthy ?? false
  const gpuAvailable = ollamaStatus.data?.gpu_available ?? false
  const hasCloudProvider = (providers.data ?? []).some(p => p.slug !== 'ollama' && p.available)
  const isStarterModel = (ollamaStatus.data?.routing_strategy ?? '').includes('local') && pulledNames.size <= 2
  const showOnboarding = !onboardingDismissed && !gpuAvailable && !hasCloudProvider && isStarterModel

  // Cloud providers from catalog (excluding ollama)
  const cloudProviders = (catalog.data ?? []).filter(p => p.slug !== 'ollama')
  const sortedCloud = CLOUD_PROVIDER_ORDER
    .map(slug => cloudProviders.find(p => p.slug === slug))
    .filter((p): p is ProviderModelList => !!p)
  // Add any providers not in the hardcoded order
  const remainingCloud = cloudProviders.filter(p => !CLOUD_PROVIDER_ORDER.includes(p.slug))
  const allCloud = [...sortedCloud, ...remainingCloud]

  return (
    <div className="px-4 py-6 sm:px-6 space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-3">
          <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">Models</h1>
          {totalAvailable > 0 && (
            <span className="text-sm text-neutral-500 dark:text-neutral-400">
              {totalAvailable} available
            </span>
          )}
        </div>
        <button
          onClick={handleRefresh}
          className="flex items-center gap-1.5 rounded-lg border border-neutral-300 dark:border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${catalog.isFetching ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Onboarding Banner */}
      {showOnboarding && <OnboardingBanner onDismiss={dismissOnboarding} />}

      {/* Section A: Local Models */}
      {activeBackend === 'ollama' && (
      <section className="space-y-4">
        <div className="flex items-center gap-3">
          <HardDrive className="h-5 w-5 text-teal-600 dark:text-teal-400" />
          <h2 className="text-base font-semibold text-neutral-900 dark:text-neutral-100">Local Models</h2>
          <OllamaStatusBadge status={ollamaStatus.data} />
        </div>

        {/* Pulled models table */}
        <Card className="overflow-hidden">
          <div className="px-4 py-3 border-b border-neutral-200 dark:border-neutral-800 flex items-center justify-between">
            <h3 className="text-sm font-medium text-neutral-700 dark:text-neutral-300">Pulled Models</h3>
            {pulled.data && (
              <span className="text-xs text-neutral-500 dark:text-neutral-400">{pulled.data.length} model(s)</span>
            )}
          </div>

          {pulled.isLoading && (
            <div className="px-4 py-6 text-sm text-neutral-500 dark:text-neutral-400 text-center">Loading…</div>
          )}
          {!pulled.isLoading && pulled.data && pulled.data.length === 0 && !ollamaHealthy && (
            <div className="px-4 py-4 flex items-center justify-between">
              <div className="text-sm text-amber-600 dark:text-amber-400 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                Ollama is not running.
              </div>
              <button
                onClick={() => startOllama.mutate()}
                disabled={startOllama.isPending}
                className="flex items-center gap-1.5 rounded-lg bg-teal-600 dark:bg-teal-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-teal-700 dark:hover:bg-teal-600 disabled:opacity-50 transition-colors"
              >
                {startOllama.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Play className="h-3.5 w-3.5" />
                )}
                Start Ollama
              </button>
            </div>
          )}
          {!pulled.isLoading && pulled.data && pulled.data.length === 0 && ollamaHealthy && (
            <div className="px-4 py-6 text-sm text-neutral-500 dark:text-neutral-400 text-center">
              No models pulled yet. Pull a model below to get started.
            </div>
          )}
          {pulled.data && pulled.data.length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-neutral-500 dark:text-neutral-400 border-b border-neutral-100 dark:border-neutral-800">
                  <th className="text-left px-4 py-2 font-medium">Model</th>
                  <th className="hidden sm:table-cell text-left px-4 py-2 font-medium">Parameters</th>
                  <th className="hidden sm:table-cell text-left px-4 py-2 font-medium">Quant</th>
                  <th className="text-right px-4 py-2 font-medium">Size</th>
                  <th className="w-10" />
                </tr>
              </thead>
              <tbody>
                {pulled.data.map(m => (
                  <PulledModelRow
                    key={m.name}
                    model={m}
                    deleting={deletingModels.has(m.name)}
                    onDelete={() => handleDelete(m.name)}
                  />
                ))}
              </tbody>
            </table>
          )}
        </Card>

        {/* Pull new model */}
        <Card className="p-4 space-y-4">
          <h3 className="text-sm font-medium text-neutral-700 dark:text-neutral-300">Pull New Model</h3>

          {/* Manual input */}
          <div className="flex gap-2">
            <input
              type="text"
              value={pullInput}
              onChange={e => setPullInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handlePull(pullInput)}
              placeholder="Model name (e.g. llama3.1:8b)"
              className="flex-1 rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 placeholder-neutral-400 dark:placeholder-neutral-500 focus:outline-none focus:ring-2 focus:ring-teal-500/50"
            />
            <button
              onClick={() => handlePull(pullInput)}
              disabled={!pullInput.trim() || pullingModels.has(pullInput)}
              className="flex items-center gap-1.5 rounded-lg bg-teal-600 dark:bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 dark:hover:bg-teal-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {pullingModels.has(pullInput) ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              Pull
            </button>
          </div>

          {/* Recommended models grid */}
          <div>
            <div className="space-y-2 mb-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 flex-wrap">
                  <p className="text-xs text-neutral-500 dark:text-neutral-400">Recommended models</p>
                  <div className="flex gap-1 flex-wrap">
                    {['all', 'general', 'reasoning', 'code', 'vision', 'embedding'].map(cat => (
                      <button
                        key={cat}
                        onClick={() => setCategoryFilter(cat)}
                        className={`rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors ${
                          categoryFilter === cat
                            ? 'bg-teal-100 dark:bg-teal-900/40 text-teal-700 dark:text-teal-400'
                            : 'bg-neutral-100 dark:bg-neutral-800 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-700'
                        }`}
                      >
                        {cat === 'all' ? 'All' : cat.charAt(0).toUpperCase() + cat.slice(1)}
                      </button>
                    ))}
                  </div>
                </div>
                <a
                  href="https://ollama.com/library"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-[11px] text-teal-600 dark:text-teal-400 hover:underline flex-shrink-0"
                >
                  Browse all models <ExternalLink className="h-3 w-3" />
                </a>
              </div>
              <div className="flex items-center gap-2">
                <HardDrive className="h-3 w-3 text-neutral-400" />
                <span className="text-[10px] text-neutral-500 dark:text-neutral-400">Max size:</span>
                <div className="flex gap-1">
                  {[
                    { label: 'All', value: 0 },
                    { label: '≤ 5 GB', value: 5 },
                    { label: '≤ 10 GB', value: 10 },
                    { label: '≤ 24 GB', value: 24 },
                    { label: '≤ 48 GB', value: 48 },
                    { label: '≤ 64 GB', value: 64 },
                    { label: '≤ 96 GB', value: 96 },
                  ].map(opt => (
                    <button
                      key={opt.value}
                      onClick={() => setSizeFilter(opt.value)}
                      className={`rounded-full px-2 py-0.5 text-[10px] font-medium font-mono transition-colors ${
                        sizeFilter === opt.value
                          ? 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400'
                          : 'bg-neutral-100 dark:bg-neutral-800 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-700'
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
              {RECOMMENDED_OLLAMA_MODELS
                .filter(rec => categoryFilter === 'all' || rec.category === categoryFilter)
                .filter(rec => sizeFilter === 0 || rec.sizeGB <= sizeFilter)
                .map(rec => {
                const isPulled = pulledNames.has(rec.name)
                const isPulling = pullingModels.has(rec.name)
                const isDeleting = deletingModels.has(rec.name)
                return (
                  <div
                    key={rec.name}
                    className={`relative rounded-lg border px-3 py-2.5 text-xs transition-colors ${
                      isPulled
                        ? 'border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20'
                        : isPulling
                        ? 'border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20'
                        : 'border-neutral-200 dark:border-neutral-700'
                    }`}
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono font-medium text-neutral-900 dark:text-neutral-100">
                        {rec.name}
                      </span>
                      {rec.required && (
                        <span className="rounded bg-amber-100 dark:bg-amber-900/40 px-1 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-400">
                          required
                        </span>
                      )}
                      {isPulled && <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400 ml-auto" />}
                      {isPulling && <Loader2 className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400 ml-auto animate-spin" />}
                    </div>
                    <p className="mt-1 text-neutral-500 dark:text-neutral-400 leading-tight">{rec.description}</p>
                    <div className="mt-2 flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        <span className="inline-block rounded-full bg-neutral-100 dark:bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-500 dark:text-neutral-400">
                          {rec.category}
                        </span>
                        <span className={`inline-block rounded-full px-1.5 py-0.5 text-[10px] font-mono ${
                          rec.sizeGB <= 2
                            ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400'
                            : rec.sizeGB <= 5
                            ? 'bg-teal-100 dark:bg-teal-900/30 text-teal-600 dark:text-teal-400'
                            : rec.sizeGB <= 10
                            ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400'
                            : 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400'
                        }`}>
                          {rec.sizeGB < 1 ? `${Math.round(rec.sizeGB * 1000)} MB` : `${rec.sizeGB} GB`}
                        </span>
                      </div>
                      {isPulled ? (
                        <button
                          onClick={() => handleDelete(rec.name)}
                          disabled={isDeleting || rec.required}
                          title={rec.required ? 'Required by Nova' : 'Delete model'}
                          className="flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          {isDeleting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
                          Delete
                        </button>
                      ) : (
                        <button
                          onClick={() => handlePull(rec.name)}
                          disabled={isPulling}
                          className="flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium text-teal-600 dark:text-teal-400 hover:bg-teal-50 dark:hover:bg-teal-900/20 transition-colors disabled:opacity-50"
                        >
                          {isPulling ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
                          Pull
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </Card>
      </section>
      )}

      {/* Section A: Local Models (vLLM/SGLang) */}
      {(activeBackend === 'vllm' || activeBackend === 'sglang') && (
      <section className="space-y-4">
        <div className="flex items-center gap-3">
          <HardDrive className="h-5 w-5 text-teal-600 dark:text-teal-400" />
          <h2 className="text-base font-semibold text-neutral-900 dark:text-neutral-100">Local Models</h2>
          <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${
            backendState === 'running'
              ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
              : backendState === 'switching'
              ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400'
              : 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400'
          }`}>
            <span className={`h-1.5 w-1.5 rounded-full ${
              backendState === 'running' ? 'bg-emerald-500'
                : backendState === 'switching' ? 'bg-amber-500 animate-pulse'
                : 'bg-red-500'
            }`} />
            {activeBackend.toUpperCase()} — {backendState}
          </span>
        </div>

        {/* Active model status */}
        <Card className="overflow-hidden">
          <div className="px-4 py-3 border-b border-neutral-200 dark:border-neutral-800 flex items-center justify-between">
            <h3 className="text-sm font-medium text-neutral-700 dark:text-neutral-300">Active Model</h3>
            <span className="text-xs font-mono text-neutral-500 dark:text-neutral-400">
              {backendStatus.data?.container_status?.status ?? 'unknown'}
            </span>
          </div>
          {isSwitching && backendStatus.data?.switch_progress && (
            <div className="px-4 py-3 bg-amber-50 dark:bg-amber-900/10 border-b border-amber-200 dark:border-amber-800">
              <div className="flex items-center gap-2 text-sm text-amber-700 dark:text-amber-400">
                <Loader2 className="h-4 w-4 animate-spin flex-shrink-0" />
                <span className="font-medium">{backendStatus.data.switch_progress.step}</span>
              </div>
              <p className="mt-1 text-xs text-amber-600 dark:text-amber-500 ml-6">
                {backendStatus.data.switch_progress.detail}
              </p>
            </div>
          )}
          {switchModelMutation.isError && (
            <div className="px-4 py-3 bg-red-50 dark:bg-red-900/10 border-b border-red-200 dark:border-red-800">
              <div className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400">
                <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                <span>Switch failed: {(switchModelMutation.error as Error)?.message ?? 'Unknown error'}</span>
              </div>
            </div>
          )}
        </Card>

        {/* GPU Stats */}
        {gpuStats.data && (
          <div className="grid grid-cols-3 gap-3">
            <Card className="p-3 text-center">
              <p className="text-xs text-neutral-500 dark:text-neutral-400">GPU Utilization</p>
              <p className="mt-1 text-lg font-semibold text-neutral-900 dark:text-neutral-100">{gpuStats.data.gpu_utilization_pct}%</p>
            </Card>
            <Card className="p-3 text-center">
              <p className="text-xs text-neutral-500 dark:text-neutral-400">VRAM</p>
              <p className="mt-1 text-lg font-semibold text-neutral-900 dark:text-neutral-100">{gpuStats.data.vram_used_gb} / {gpuStats.data.vram_total_gb} GB</p>
            </Card>
            <Card className="p-3 text-center">
              <p className="text-xs text-neutral-500 dark:text-neutral-400">Temperature</p>
              <p className="mt-1 text-lg font-semibold text-neutral-900 dark:text-neutral-100">{gpuStats.data.temperature_c}&deg;C</p>
            </Card>
          </div>
        )}

        {/* Search HuggingFace models */}
        <Card className="p-4 space-y-4">
          <h3 className="text-sm font-medium text-neutral-700 dark:text-neutral-300">Search HuggingFace Models</h3>
          <div className="flex gap-2">
            <input
              type="text"
              value={modelSearchQuery}
              onChange={e => setModelSearchQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleModelSearch()}
              placeholder="Search models (e.g. llama 8b, mistral, qwen)"
              className="flex-1 rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 placeholder-neutral-400 dark:placeholder-neutral-500 focus:outline-none focus:ring-2 focus:ring-teal-500/50"
            />
            <button
              onClick={handleModelSearch}
              disabled={!modelSearchQuery.trim() || searching}
              className="flex items-center gap-1.5 rounded-lg bg-teal-600 dark:bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 dark:hover:bg-teal-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {searching ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ExternalLink className="h-4 w-4" />
              )}
              Search
            </button>
          </div>

          {/* Search results */}
          {searchResults.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs text-neutral-500 dark:text-neutral-400">{searchResults.length} result(s)</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {searchResults.map(result => (
                  <div
                    key={result.id}
                    className="rounded-lg border border-neutral-200 dark:border-neutral-700 px-3 py-2.5 text-xs"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <span className="font-mono font-medium text-neutral-900 dark:text-neutral-100 break-all">
                          {result.id}
                        </span>
                        {result.quantized && (
                          <span className="ml-1.5 rounded bg-teal-100 dark:bg-teal-900/40 px-1 py-0.5 text-[10px] font-medium text-teal-700 dark:text-teal-400">
                            quantized
                          </span>
                        )}
                      </div>
                    </div>
                    {result.description && (
                      <p className="mt-1 text-neutral-500 dark:text-neutral-400 leading-tight line-clamp-2">
                        {result.description}
                      </p>
                    )}
                    <div className="mt-2 flex items-center justify-between">
                      <div className="flex items-center gap-2 text-neutral-400 dark:text-neutral-500">
                        <span className="text-[10px]">{result.downloads.toLocaleString()} downloads</span>
                        {result.vram_estimate_gb != null && (
                          <span className="text-[10px] font-mono">~{result.vram_estimate_gb} GB VRAM</span>
                        )}
                      </div>
                      <button
                        onClick={() => handleSwitchModel(result.id)}
                        disabled={isSwitching || switchModelMutation.isPending}
                        className="flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium text-teal-600 dark:text-teal-400 hover:bg-teal-50 dark:hover:bg-teal-900/20 transition-colors disabled:opacity-50"
                      >
                        {switchModelMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
                        Load
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>

        {/* Recommended models */}
        {recommended.data && recommended.data.length > 0 && (
          <Card className="p-4 space-y-3">
            <h3 className="text-sm font-medium text-neutral-700 dark:text-neutral-300">Recommended Models</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
              {recommended.data.map(rec => (
                <div
                  key={rec.id}
                  className="rounded-lg border border-neutral-200 dark:border-neutral-700 px-3 py-2.5 text-xs"
                >
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono font-medium text-neutral-900 dark:text-neutral-100">
                      {rec.name}
                    </span>
                  </div>
                  <p className="mt-1 text-neutral-500 dark:text-neutral-400 leading-tight">{rec.description}</p>
                  <div className="mt-2 flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <span className="inline-block rounded-full bg-neutral-100 dark:bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-500 dark:text-neutral-400">
                        {rec.category}
                      </span>
                      <span className="inline-block rounded-full bg-amber-100 dark:bg-amber-900/30 px-1.5 py-0.5 text-[10px] font-mono text-amber-600 dark:text-amber-400">
                        {rec.min_vram_gb} GB+
                      </span>
                    </div>
                    <button
                      onClick={() => handleSwitchModel(rec.id)}
                      disabled={isSwitching || switchModelMutation.isPending}
                      className="flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium text-teal-600 dark:text-teal-400 hover:bg-teal-50 dark:hover:bg-teal-900/20 transition-colors disabled:opacity-50"
                    >
                      {switchModelMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
                      Load
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}
      </section>
      )}

      {/* Section A: No backend configured */}
      {activeBackend === 'none' && (
      <section className="space-y-4">
        <div className="flex items-center gap-3">
          <HardDrive className="h-5 w-5 text-neutral-400 dark:text-neutral-500" />
          <h2 className="text-base font-semibold text-neutral-900 dark:text-neutral-100">Local Models</h2>
        </div>
        <Card className="p-6 text-center space-y-3">
          <Server className="h-8 w-8 text-neutral-300 dark:text-neutral-600 mx-auto" />
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            No local inference backend is configured.
          </p>
          <a
            href="/settings"
            className="inline-flex items-center gap-1.5 rounded-lg bg-teal-600 dark:bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 dark:hover:bg-teal-600 transition-colors"
          >
            Configure in Settings <ExternalLink className="h-4 w-4" />
          </a>
        </Card>
      </section>
      )}

      {/* Section B: Cloud Providers */}
      <section className="space-y-4">
        <div className="flex items-center gap-3">
          <Cloud className="h-5 w-5 text-blue-600 dark:text-blue-400" />
          <h2 className="text-base font-semibold text-neutral-900 dark:text-neutral-100">Cloud Providers</h2>
        </div>

        {catalog.isLoading && (
          <p className="text-sm text-neutral-500 dark:text-neutral-400">Discovering providers…</p>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {allCloud.map(provider => (
            <ProviderCard key={provider.slug} provider={provider} />
          ))}
        </div>
      </section>
    </div>
  )
}

// ── Sub-components ───────────────────────────────────────────────────────────

function OnboardingBanner({ onDismiss }: { onDismiss: () => void }) {
  return (
    <Card className="relative border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-4">
      <button
        onClick={onDismiss}
        className="absolute top-3 right-3 text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300"
      >
        <X className="h-4 w-4" />
      </button>
      <div className="flex gap-3">
        <Info className="h-5 w-5 text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
        <div className="space-y-2 text-sm">
          <p className="font-medium text-neutral-900 dark:text-neutral-100">
            Nova is running on CPU with a small starter model — responses may be slower than usual.
          </p>
          <p className="text-neutral-600 dark:text-neutral-400">To speed things up:</p>
          <ul className="space-y-1 text-neutral-600 dark:text-neutral-400">
            <li className="flex items-start gap-2">
              <Server className="h-4 w-4 text-teal-600 dark:text-teal-400 flex-shrink-0 mt-0.5" />
              <span><strong>Connect a GPU</strong> — Point to a remote Ollama instance with GPU in Settings → LLM Routing</span>
            </li>
            <li className="flex items-start gap-2">
              <Cloud className="h-4 w-4 text-blue-600 dark:text-blue-400 flex-shrink-0 mt-0.5" />
              <span><strong>Use a cloud provider</strong> — Configure an API key in Settings → Providers (Groq's free tier is a great start)</span>
            </li>
          </ul>
          <button
            onClick={onDismiss}
            className="mt-1 rounded-lg bg-amber-600 dark:bg-amber-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700 dark:hover:bg-amber-600 transition-colors"
          >
            Got it
          </button>
        </div>
      </div>
    </Card>
  )
}

function OllamaStatusBadge({ status }: { status: OllamaStatus | undefined }) {
  if (!status) return null
  const healthy = status.healthy
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${
      healthy
        ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
        : 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400'
    }`}>
      <span className={`h-1.5 w-1.5 rounded-full ${healthy ? 'bg-emerald-500' : 'bg-red-500'}`} />
      {healthy ? 'Connected' : 'Unreachable'}
      <span className="text-neutral-400 dark:text-neutral-500 font-normal ml-1">{status.base_url}</span>
    </span>
  )
}

const REQUIRED_MODELS = new Set(RECOMMENDED_OLLAMA_MODELS.filter(m => m.required).map(m => m.name))

function isRequiredModel(name: string): boolean {
  if (REQUIRED_MODELS.has(name)) return true
  // Also match tagged variants like "nomic-embed-text:latest"
  const base = name.split(':')[0]
  return REQUIRED_MODELS.has(base)
}

function PulledModelRow({
  model,
  deleting,
  onDelete,
}: {
  model: OllamaPulledModel
  deleting: boolean
  onDelete: () => void
}) {
  const required = isRequiredModel(model.name)
  return (
    <tr className="border-b border-neutral-100 dark:border-neutral-800 last:border-0 hover:bg-neutral-50 dark:hover:bg-neutral-800/50">
      <td className="px-4 py-2.5 font-mono text-neutral-900 dark:text-neutral-100">
        {model.name}
        {required && (
          <span className="ml-2 rounded bg-amber-100 dark:bg-amber-900/40 px-1 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-400">
            required
          </span>
        )}
      </td>
      <td className="hidden sm:table-cell px-4 py-2.5 text-neutral-500 dark:text-neutral-400">{model.parameter_size || '—'}</td>
      <td className="hidden sm:table-cell px-4 py-2.5 text-neutral-500 dark:text-neutral-400">{model.quantization_level || '—'}</td>
      <td className="px-4 py-2.5 text-right text-neutral-500 dark:text-neutral-400">{formatBytes(model.size)}</td>
      <td className="px-2 py-2.5">
        <button
          onClick={onDelete}
          disabled={deleting || required}
          className="p-1 rounded text-neutral-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          title={required ? 'Required by Nova' : 'Delete model'}
        >
          {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
        </button>
      </td>
    </tr>
  )
}

function ProviderCard({ provider }: { provider: ProviderModelList }) {
  const badge = TYPE_BADGE[provider.type] ?? TYPE_BADGE.free
  const configured = provider.available

  return (
    <Card className={`p-4 ${!configured ? 'opacity-70' : ''}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">{provider.name}</h3>
          <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${badge.className}`}>
            {badge.label}
          </span>
        </div>
        <span className={`h-2 w-2 rounded-full ${configured ? 'bg-emerald-500' : 'bg-neutral-300 dark:bg-neutral-600'}`} />
      </div>

      {configured ? (
        <div className="space-y-1.5">
          {provider.models.length > 0 ? (
            <ul className="space-y-1">
              {provider.models.map(m => (
                <li
                  key={m.id}
                  className="flex items-center gap-1.5 font-mono text-xs text-neutral-600 dark:text-neutral-400 truncate"
                  title={m.id}
                >
                  {m.registered && (
                    <Check className="h-3 w-3 text-emerald-500 flex-shrink-0" />
                  )}
                  {m.id}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-neutral-500 dark:text-neutral-400 italic">
              Connected — models loaded from provider config
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-neutral-500 dark:text-neutral-400">Not configured. To enable:</p>
          <ul className="space-y-1">
            {provider.auth_methods.map((method, i) => (
              <li key={i} className="flex items-start gap-1.5 text-xs text-neutral-500 dark:text-neutral-400">
                <span className="text-neutral-300 dark:text-neutral-600 mt-0.5">•</span>
                <code className="text-[11px] text-neutral-600 dark:text-neutral-400">{method}</code>
              </li>
            ))}
          </ul>
          <a
            href="/settings"
            className="inline-flex items-center gap-1 text-xs text-teal-600 dark:text-teal-400 hover:underline"
          >
            Configure in Settings <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      )}
    </Card>
  )
}
