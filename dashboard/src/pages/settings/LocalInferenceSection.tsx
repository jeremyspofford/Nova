import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Cpu, Play, Square, RefreshCw, Wifi, AlertCircle, Lightbulb } from "lucide-react";
import { Section, Button, Toggle, Badge, StatusDot, Card } from "../../components/ui";
import { ConfigField, useConfigValue, type ConfigSectionProps } from "./shared";
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

const STATE_LABELS: Record<string, { label: string; status: 'success' | 'neutral' | 'warning' | 'danger' }> = {
  ready:    { label: "Running",      status: "success" },
  stopped:  { label: "Stopped",      status: "neutral" },
  starting: { label: "Starting...",  status: "warning" },
  draining: { label: "Draining...",  status: "warning" },
  error:    { label: "Error",        status: "danger" },
};

export function LocalInferenceSection({ entries, onSave, saving }: ConfigSectionProps) {
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

  const currentState = status?.state || "stopped";
  const stateInfo = STATE_LABELS[currentState] || STATE_LABELS.stopped;
  const isTransitioning = currentState === "starting" || currentState === "draining";
  const hasGpu = hardware?.gpus && hardware.gpus.length > 0;
  const primaryGpu = hardware?.gpus?.[0];

  return (
    <Section id="local-inference" icon={Cpu} title="Local Inference" description="Manage your local AI inference backend">
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

      {/* Backend Selector */}
      <div className="space-y-3">
        <label className="block text-compact font-medium text-content-secondary">Backend</label>
        <div className="flex flex-wrap gap-2">
          {BACKENDS.map((b) => (
            <Button
              key={b.value}
              variant={(status?.backend || configBackend) === b.value ? 'primary' : 'secondary'}
              size="sm"
              onClick={() => {
                setSelectedBackend(b.value);
                onSave("inference.backend", b.value);
              }}
              disabled={isTransitioning}
            >
              {b.label}
            </Button>
          ))}
        </div>
      </div>

      {/* Status */}
      {status && status.backend !== "none" && (
        <Card variant="default" className="mt-4 p-3">
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
    </Section>
  );
}
