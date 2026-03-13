import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Cpu, Play, Square, RefreshCw, Wifi, AlertCircle, Lightbulb } from "lucide-react";
import { Section, ConfigField, useConfigValue, type ConfigSectionProps } from "./shared";
import { recoveryFetch } from "../../api-recovery";
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
}

const BACKENDS = [
  { value: "vllm", label: "vLLM", description: "Production GPU inference (NVIDIA/AMD)" },
  { value: "sglang", label: "SGLang", description: "High-throughput GPU inference" },
  { value: "ollama", label: "Ollama", description: "Easy mode / CPU fallback" },
  { value: "custom", label: "Custom", description: "User-managed OpenAI-compatible server" },
  { value: "none", label: "None", description: "Cloud providers only" },
] as const;

const STATE_LABELS: Record<string, { label: string; color: string }> = {
  ready: { label: "Running", color: "text-emerald-400" },
  stopped: { label: "Stopped", color: "text-neutral-500 dark:text-neutral-500" },
  starting: { label: "Starting...", color: "text-amber-400" },
  draining: { label: "Draining...", color: "text-amber-400" },
  error: { label: "Error", color: "text-red-400" },
};

export function LocalInferenceSection({ entries, onSave, saving }: ConfigSectionProps) {
  const queryClient = useQueryClient();
  const [selectedBackend, setSelectedBackend] = useState<string>("");
  const [showRemote, setShowRemote] = useState(false);

  // All hooks at top level (Rules of Hooks)
  const configBackend = useConfigValue(entries, "inference.backend", "ollama");
  const remoteUrl = useConfigValue(entries, "inference.url", "");
  const wolMac = useConfigValue(entries, "llm.wol_mac", "");
  const customUrl = useConfigValue(entries, "inference.custom_url", "");
  const customAuth = useConfigValue(entries, "inference.custom_auth_header", "");
  const [testingConnection, setTestingConnection] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);

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
      // Optimistic update: immediately show "Starting..." so user gets instant feedback
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

  // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally only sync on first load
  useEffect(() => {
    if (configBackend && !selectedBackend) {
      setSelectedBackend(configBackend);
    }
  }, [configBackend]);

  const currentState = status?.state || "stopped";
  const stateInfo = STATE_LABELS[currentState] || STATE_LABELS.stopped;
  const isTransitioning = currentState === "starting" || currentState === "draining";
  const hasGpu = hardware?.gpus && hardware.gpus.length > 0;
  const primaryGpu = hardware?.gpus?.[0];

  return (
    <Section id="local-inference" icon={Cpu} title="Local Inference" description="Manage your local AI inference backend">
      {/* Recommendation Banner */}
      {recommendation && status && recommendation.backend !== status.backend && status.backend !== "none" && (
        <div className="mb-4 p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg text-sm flex items-start gap-2">
          <Lightbulb className="w-4 h-4 text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
          <div>
            <span className="font-medium text-amber-800 dark:text-amber-300">Recommendation:</span>{" "}
            <span className="text-amber-700 dark:text-amber-400">{recommendation.reason}</span>
            <span className="text-amber-600 dark:text-amber-500 ml-1">
              Consider switching to <strong>{recommendation.backend}</strong>
              {recommendation.model && <> with <code className="text-xs">{recommendation.model}</code></>}.
            </span>
          </div>
        </div>
      )}

      {/* Hardware Info */}
      {hardware && (
        <div className="mb-4 p-3 bg-neutral-50 dark:bg-neutral-800/50 rounded-lg text-sm">
          {hasGpu ? (
            <div className="flex items-center gap-2">
              <span className="text-emerald-600 dark:text-emerald-400">GPU Detected:</span>
              <span className="text-neutral-700 dark:text-neutral-300">
                {primaryGpu?.model} ({primaryGpu?.vram_gb}GB VRAM)
                {hardware.gpus.length > 1 && ` + ${hardware.gpus.length - 1} more`}
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-neutral-500 dark:text-neutral-400">
              <AlertCircle className="w-4 h-4" />
              <span>No GPU detected. Ollama (CPU) or cloud providers recommended.</span>
            </div>
          )}
          {hardware.recommended_backend && (
            <div className="mt-1 text-neutral-500">
              Recommended: <span className="text-accent-600 dark:text-accent-400">{hardware.recommended_backend}</span>
            </div>
          )}
        </div>
      )}

      {/* Backend Selector */}
      <div className="space-y-3">
        <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300">Backend</label>
        <div className="flex gap-2">
          {BACKENDS.map((b) => (
            <button
              key={b.value}
              onClick={() => {
                setSelectedBackend(b.value);
                onSave("inference.backend", b.value);
              }}
              disabled={isTransitioning}
              className={`px-4 py-2 rounded-lg text-sm transition-colors ${
                (status?.backend || configBackend) === b.value
                  ? "bg-accent-600 text-white"
                  : "bg-neutral-100 dark:bg-neutral-700 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-600"
              } ${isTransitioning ? "opacity-50 cursor-not-allowed" : ""}`}
            >
              {b.label}
            </button>
          ))}
        </div>
      </div>

      {/* Status */}
      {status && status.backend !== "none" && (
        <div className="mt-4 p-3 bg-neutral-50 dark:bg-neutral-800/50 rounded-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className={`text-sm font-medium ${stateInfo.color}`}>{stateInfo.label}</span>
              <span className="text-xs text-neutral-500">{status.backend}</span>
            </div>
            <div className="flex gap-2">
              {currentState === "ready" ? (
                <button
                  onClick={() => stopBackend.mutate()}
                  disabled={stopBackend.isPending}
                  className="p-1.5 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700 text-neutral-500 dark:text-neutral-400"
                  title="Stop backend"
                >
                  <Square className="w-4 h-4" />
                </button>
              ) : currentState === "stopped" || currentState === "error" ? (
                <button
                  onClick={() => startBackend.mutate(status.backend)}
                  disabled={startBackend.isPending}
                  className="p-1.5 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700 text-neutral-500 dark:text-neutral-400"
                  title="Start backend"
                >
                  <Play className="w-4 h-4" />
                </button>
              ) : null}
              <button
                onClick={() => refetchStatus()}
                className="p-1.5 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700 text-neutral-500 dark:text-neutral-400"
                title="Refresh status"
              >
                <RefreshCw className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
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
          <button
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
            disabled={!customUrl || testingConnection}
            className="px-3 py-1.5 text-sm rounded-lg bg-accent-600 text-white hover:bg-accent-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {testingConnection ? "Testing..." : "Test Connection"}
          </button>
          {testResult && (
            <p className={`text-sm ${testResult.ok ? "text-emerald-500" : "text-red-400"}`}>
              {testResult.message}
            </p>
          )}
        </div>
      )}

      {/* Remote Backend Toggle */}
      <div className="mt-4 pt-4 border-t border-neutral-200 dark:border-neutral-700/50">
        <label className="flex items-center gap-2 text-sm text-neutral-500 dark:text-neutral-400 cursor-pointer">
          <input
            type="checkbox"
            checked={showRemote}
            onChange={(e) => setShowRemote(e.target.checked)}
            className="rounded bg-neutral-100 dark:bg-neutral-700 border-neutral-300 dark:border-neutral-600"
          />
          <Wifi className="w-4 h-4" />
          Use remote inference server
        </label>

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
        <div className="mt-3 p-3 bg-neutral-50 dark:bg-neutral-800/30 rounded text-sm text-neutral-500">
          No GPU detected and no remote server configured. Consider using Ollama (CPU) or configure cloud providers below.
        </div>
      )}
    </Section>
  );
}
