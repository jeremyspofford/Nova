import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Cpu, Play, Square, RefreshCw, Wifi, AlertCircle, Lightbulb, CheckCircle2, ArrowRight, Eye, EyeOff } from "lucide-react";
import { Section, Button, Toggle, Badge, StatusDot, Card } from "../../components/ui";
import { ConfigField, useConfigValue, type ConfigSectionProps } from "./shared";
import { recoveryFetch, getEnvVars, patchEnv } from "../../api-recovery";
import { getRecommendation, type InferenceRecommendation } from "../../api-recovery";

interface HardwareInfo {
  gpus: Array<{ vendor: string; model: string; vram_gb: number; index: number }>;
  docker_gpu_runtime: string;
  cpu_cores: number;
  ram_gb: number;
  disk_free_gb: number;
  detected_at: string;
  recommended_backend: string;
}

interface BackendStatus {
  backend: string;
  state: string;
  container_status: unknown;
  error?: string;
  switch_progress?: { step: string; detail: string };
}

const BACKENDS = [
  { value: "vllm", label: "vLLM", description: "Production GPU inference (NVIDIA/AMD)" },
  { value: "sglang", label: "SGLang", description: "High-throughput GPU inference" },
  { value: "ollama", label: "Ollama", description: "Easy mode / CPU fallback" },
  { value: "custom", label: "Custom", description: "User-managed OpenAI-compatible server" },
  { value: "none", label: "None", description: "Cloud providers only" },
] as const;

const STATE_LABELS: Record<string, { label: string; status: 'success' | 'neutral' | 'warning' | 'danger' }> = {
  ready:    { label: "Running",      status: "success" },
  stopped:  { label: "Stopped",      status: "neutral" },
  starting: { label: "Starting...",  status: "warning" },
  draining: { label: "Draining...",  status: "warning" },
  error:    { label: "Error",        status: "danger" },
};

function HuggingFaceTokenField() {
  const queryClient = useQueryClient();
  const { data: envVars } = useQuery({
    queryKey: ["env-vars"],
    queryFn: getEnvVars,
    staleTime: 30_000,
  });

  const currentToken = envVars?.HF_TOKEN ?? "";
  const [draft, setDraft] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showToken, setShowToken] = useState(false);

  useEffect(() => {
    setDraft(currentToken);
    setDirty(false);
  }, [currentToken]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await patchEnv({ HF_TOKEN: draft });
      queryClient.invalidateQueries({ queryKey: ["env-vars"] });
      setDirty(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mt-4 pt-4 border-t border-border-subtle space-y-1.5">
      <div className="flex items-center justify-between">
        <label className="text-caption font-medium text-content-secondary">HuggingFace Token</label>
        {dirty && (
          <Button size="sm" onClick={handleSave} loading={saving}>Save</Button>
        )}
      </div>
      {!currentToken && (
        <div className="rounded-sm bg-surface-elevated p-2.5 text-caption text-content-tertiary space-y-1.5">
          <p>
            <span className="font-medium text-content-secondary">Not required for the default model.</span>{" "}
            Only needed if you switch to a gated model (Llama, Gemma, etc.).
          </p>
          <p>To use a gated model:</p>
          <ol className="list-decimal list-inside space-y-0.5 ml-1">
            <li>Accept the model&apos;s license on its <span className="text-content-secondary">HuggingFace page</span></li>
            <li>Create a token at{" "}
              <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                huggingface.co/settings/tokens
              </a>
            </li>
            <li>Paste it below and restart the backend</li>
          </ol>
        </div>
      )}
      <div className="relative">
        <input
          type={showToken ? "text" : "password"}
          value={draft}
          onChange={e => { setDraft(e.target.value); setDirty(e.target.value !== currentToken) }}
          placeholder="hf_..."
          className="h-9 w-full rounded-sm border border-border bg-surface-input px-3 pr-8 text-compact text-content-primary placeholder:text-content-tertiary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40 transition-colors font-mono"
        />
        <button
          type="button"
          onClick={() => setShowToken(!showToken)}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-content-tertiary hover:text-content-primary transition-colors"
        >
          {showToken ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </div>
      {currentToken && (
        <p className="text-caption text-content-tertiary">
          Token set. Requires container restart after changes.
        </p>
      )}
    </div>
  );
}

export function LocalInferenceSection({ entries, onSave, saving, inline }: ConfigSectionProps & { inline?: boolean }) {
  const queryClient = useQueryClient();
  const [selectedBackend, setSelectedBackend] = useState<string>("");
  const [showRemote, setShowRemote] = useState(false);

  const configBackend = useConfigValue(entries, "inference.backend", "ollama");
  const remoteUrl = useConfigValue(entries, "inference.url", "");
  const wolMac = useConfigValue(entries, "llm.wol_mac", "");
  const customUrl = useConfigValue(entries, "inference.custom_url", "");
  const customAuth = useConfigValue(entries, "inference.custom_auth_header", "");
  const [testingConnection, setTestingConnection] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  // Track backend switching for confirmation banner
  const [switchInfo, setSwitchInfo] = useState<{ from: string; to: string } | null>(null);
  const [switchConfirmed, setSwitchConfirmed] = useState(false);
  const confirmTimerRef = useRef<ReturnType<typeof setTimeout>>();

  const { data: recommendation } = useQuery<InferenceRecommendation>({
    queryKey: ["inference-recommendation"],
    queryFn: getRecommendation,
    staleTime: 60_000,
    retry: 1,
  });

  const { data: hardware } = useQuery<HardwareInfo>({
    queryKey: ["inference-hardware"],
    queryFn: () => recoveryFetch<HardwareInfo>("/api/v1/recovery/inference/hardware"),
    staleTime: 60_000,
    retry: 1,
  });

  const { data: status, refetch: refetchStatus } = useQuery<BackendStatus>({
    queryKey: ["inference-backend-status"],
    queryFn: () => recoveryFetch<BackendStatus>("/api/v1/recovery/inference/backend"),
    staleTime: 5_000,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return state === "starting" || state === "draining" ? 2_000 : 10_000;
    },
    retry: 1,
  });

  const startBackend = useMutation({
    mutationFn: (backend: string) =>
      recoveryFetch(`/api/v1/recovery/inference/backend/${backend}/start`, { method: "POST" }),
    onMutate: (backend) => {
      queryClient.setQueryData<BackendStatus>(["inference-backend-status"], (old) =>
        old ? { ...old, backend, state: "starting" } : { backend, state: "starting", container_status: null },
      );
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["inference-backend-status"] });
    },
  });

  const stopBackend = useMutation({
    mutationFn: () =>
      recoveryFetch("/api/v1/recovery/inference/backend/stop", { method: "POST" }),
    onMutate: () => {
      queryClient.setQueryData<BackendStatus>(["inference-backend-status"], (old) =>
        old ? { ...old, state: "draining" } : undefined,
      );
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["inference-backend-status"] });
    },
  });

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (configBackend && !selectedBackend) {
      setSelectedBackend(configBackend);
    }
  }, [configBackend]);

  // Detect when a backend switch completes (state becomes "ready" while we're tracking a switch)
  useEffect(() => {
    if (switchInfo && status?.state === "ready" && status.backend === switchInfo.to) {
      setSwitchConfirmed(true);
      // Auto-dismiss after 8 seconds
      confirmTimerRef.current = setTimeout(() => {
        setSwitchConfirmed(false);
        setSwitchInfo(null);
      }, 8_000);
    }
    return () => { if (confirmTimerRef.current) clearTimeout(confirmTimerRef.current); };
  }, [switchInfo, status?.state, status?.backend]);

  const currentState = status?.state || "stopped";
  const stateInfo = STATE_LABELS[currentState] || STATE_LABELS.stopped;
  const isTransitioning = currentState === "starting" || currentState === "draining";
  const hasGpu = hardware?.gpus && hardware.gpus.length > 0;
  const primaryGpu = hardware?.gpus?.[0];

  /** Switch backend: save config + start the new backend (recovery controller stops the old one) */
  const handleSwitchBackend = (backend: string) => {
    const currentBackend = status?.backend || configBackend;
    if (backend === currentBackend && currentState === "ready") return; // already active

    setSelectedBackend(backend);
    onSave("inference.backend", backend);

    // Clear any previous confirmation
    setSwitchConfirmed(false);
    if (confirmTimerRef.current) clearTimeout(confirmTimerRef.current);

    if (backend === "none" || backend === "custom") {
      // No container to start — just save config
      setSwitchInfo(null);
      return;
    }

    // Track the switch — only show "switching" banner when actually changing backends
    if (currentBackend && currentBackend !== backend) {
      setSwitchInfo({ from: currentBackend, to: backend });
    } else {
      setSwitchInfo(null); // restarting same backend, no switch banner needed
    }
    startBackend.mutate(backend);
  };

  const content = (
    <>
      {/* Recommendation Banner */}
      {recommendation && status && recommendation.backend !== status.backend && status.backend !== "none" && (
        <div className="mb-4 p-3 bg-warning-dim border border-amber-200 dark:border-amber-800 rounded-sm text-compact flex items-start gap-2">
          <Lightbulb className="w-4 h-4 text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
          <div>
            <span className="font-medium text-amber-800 dark:text-amber-300">Recommendation:</span>{" "}
            <span className="text-amber-700 dark:text-amber-400">{recommendation.reason}</span>
            <span className="text-amber-600 dark:text-amber-500 ml-1">
              Consider switching to <strong>{recommendation.backend}</strong>
              {recommendation.model && <> with <code className="text-caption">{recommendation.model}</code></>}.
            </span>
          </div>
        </div>
      )}

      {/* Hardware Info */}
      {hardware && (
        <Card variant="default" className="p-3 mb-4">
          {hasGpu ? (
            <div className="flex items-center gap-2 text-compact">
              <Badge color="success" size="sm">GPU Detected</Badge>
              <span className="text-content-secondary">
                {primaryGpu?.model} ({primaryGpu?.vram_gb}GB VRAM)
                {hardware.gpus.length > 1 && ` + ${hardware.gpus.length - 1} more`}
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-compact text-content-tertiary">
              <AlertCircle className="w-4 h-4" />
              <span>No GPU detected. Ollama (CPU) or cloud providers recommended.</span>
            </div>
          )}
          {hardware.recommended_backend && (
            <div className="mt-1 text-caption text-content-tertiary">
              Recommended: <span className="text-accent">{hardware.recommended_backend}</span>
            </div>
          )}
        </Card>
      )}

      {/* Switch Confirmation Banner */}
      {switchConfirmed && switchInfo && (
        <div className="mb-4 p-3 bg-success/10 border border-emerald-300 dark:border-emerald-700 rounded-sm text-compact flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-success flex-shrink-0" />
          <span className="text-emerald-800 dark:text-emerald-300">
            Switched from <strong>{BACKENDS.find(b => b.value === switchInfo.from)?.label || switchInfo.from}</strong>
            <ArrowRight className="w-3 h-3 inline mx-1" />
            <strong>{BACKENDS.find(b => b.value === switchInfo.to)?.label || switchInfo.to}</strong>
            {" "}&mdash; backend is running.
          </span>
          <button
            className="ml-auto text-emerald-600 dark:text-emerald-400 hover:text-emerald-800 dark:hover:text-emerald-200 text-caption"
            onClick={() => { setSwitchConfirmed(false); setSwitchInfo(null); }}
          >
            Dismiss
          </button>
        </div>
      )}

      {/* In-progress Switch Banner */}
      {switchInfo && !switchConfirmed && isTransitioning && (
        <div className="mb-4 p-3 bg-surface-elevated border border-border-subtle rounded-sm text-compact flex items-center gap-2">
          <RefreshCw className="w-4 h-4 text-accent animate-spin flex-shrink-0" />
          <span className="text-content-secondary">
            Switching from <strong>{BACKENDS.find(b => b.value === switchInfo.from)?.label || switchInfo.from}</strong>
            {" "}to <strong>{BACKENDS.find(b => b.value === switchInfo.to)?.label || switchInfo.to}</strong>...
          </span>
        </div>
      )}

      {/* Backend Selector */}
      <div className="space-y-3">
        <label className="block text-compact font-medium text-content-secondary">Backend</label>
        <div className="flex flex-wrap gap-2">
          {BACKENDS.map((b) => (
            <Button
              key={b.value}
              variant={(status?.backend || configBackend) === b.value ? 'primary' : 'secondary'}
              size="sm"
              onClick={() => handleSwitchBackend(b.value)}
              disabled={isTransitioning}
            >
              {b.label}
            </Button>
          ))}
        </div>
      </div>

      {/* Status */}
      {status && status.backend !== "none" && (
        <Card variant="default" className="mt-4 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <StatusDot status={stateInfo.status} pulse={isTransitioning} />
              <span className="text-compact font-medium text-content-primary">{stateInfo.label}</span>
              <Badge color="neutral" size="sm">{status.backend}</Badge>
            </div>
            <div className="flex gap-2">
              {currentState === "ready" ? (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => stopBackend.mutate()}
                  loading={stopBackend.isPending}
                  icon={<Square size={14} />}
                />
              ) : currentState === "stopped" || currentState === "error" ? (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => startBackend.mutate(status.backend)}
                  loading={startBackend.isPending}
                  icon={<Play size={14} />}
                />
              ) : null}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => refetchStatus()}
                icon={<RefreshCw size={14} />}
              />
            </div>
          </div>
          {currentState === "error" && status.error && (
            <div className="rounded-sm bg-danger-dim p-2 text-caption text-danger">
              {status.error}
            </div>
          )}
        </Card>
      )}

      {/* Custom Backend Config */}
      {(status?.backend || configBackend) === "custom" && (
        <div className="mt-4 space-y-3">
          <ConfigField
            label="Server URL"
            configKey="inference.custom_url"
            value={customUrl}
            onSave={onSave}
            saving={saving}
            placeholder="http://192.168.1.50:8000"
            description="URL of your OpenAI-compatible inference server"
          />
          <ConfigField
            label="Auth Header"
            configKey="inference.custom_auth_header"
            value={customAuth}
            onSave={onSave}
            saving={saving}
            placeholder="Bearer sk-..."
            description="Optional Authorization header value"
          />
          <Button
            size="sm"
            onClick={async () => {
              if (!customUrl) return;
              setTestingConnection(true);
              setTestResult(null);
              try {
                const headers: Record<string, string> = {};
                if (customAuth) headers["Authorization"] = customAuth;
                const r = await fetch(customUrl.replace(/\/$/, "") + "/health", {
                  headers,
                  signal: AbortSignal.timeout(5000),
                });
                setTestResult(r.ok
                  ? { ok: true, message: `Connected (HTTP ${r.status})` }
                  : { ok: false, message: `Server returned HTTP ${r.status}` });
              } catch (e) {
                setTestResult({ ok: false, message: e instanceof Error ? e.message : "Connection failed" });
              } finally {
                setTestingConnection(false);
              }
            }}
            disabled={!customUrl}
            loading={testingConnection}
          >
            Test Connection
          </Button>
          {testResult && (
            <p className={`text-compact ${testResult.ok ? "text-success" : "text-danger"}`}>
              {testResult.message}
            </p>
          )}
        </div>
      )}

      {/* HuggingFace Token — needed for vLLM/SGLang to download gated models */}
      {["vllm", "sglang"].includes((status?.backend || configBackend).replace(/"/g, '')) && (
        <HuggingFaceTokenField />
      )}

      {/* Remote Backend Toggle */}
      <div className="mt-4 pt-4 border-t border-border-subtle">
        <div className="flex items-center gap-2 text-compact text-content-tertiary">
          <Toggle
            checked={showRemote}
            onChange={setShowRemote}
            size="sm"
          />
          <Wifi className="w-4 h-4" />
          <span>Use remote inference server</span>
        </div>

        {showRemote && (
          <div className="mt-3 space-y-3">
            <ConfigField
              label="Remote URL"
              configKey="inference.url"
              value={remoteUrl}
              onSave={onSave}
              saving={saving}
              placeholder="http://192.168.1.50:8000"
              description="URL of remote vLLM/Ollama/SGLang server"
            />
            <ConfigField
              label="WoL MAC Address"
              configKey="llm.wol_mac"
              value={wolMac}
              onSave={onSave}
              saving={saving}
              placeholder="aa:bb:cc:dd:ee:ff"
              description="Send Wake-on-LAN to start remote GPU machine"
            />
          </div>
        )}
      </div>

      {/* No GPU + No Remote guidance */}
      {!hasGpu && !showRemote && status?.backend !== "ollama" && (
        <div className="mt-3 p-3 bg-surface-elevated rounded-sm text-compact text-content-tertiary">
          No GPU detected and no remote server configured. Consider using Ollama (CPU) or configure cloud providers below.
        </div>
      )}
    </>
  );

  if (inline) return content;

  return (
    <Section id="local-inference" icon={Cpu} title="Local Inference" description="Manage your local AI inference backend">
      {content}
    </Section>
  );
}
