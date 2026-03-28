# Distributed Deployment Architecture

> **STATUS: DESIGN ONLY — NOT READY FOR IMPLEMENTATION**
>
> This spec captures the architectural vision for Nova's distributed deployment.
> It was brainstormed on 2026-03-28 and approved at the design level, but several
> sections (especially IaC details, Nano profile, and K8s Helm charts) need further
> discussion before implementation begins. When revisiting this spec, resume the
> brainstorming process — do not jump straight to implementation planning.

## Problem Statement

Nova runs as a monolithic Docker Compose stack on a single machine. All services share one bridge network, communicate via container DNS, and assume co-location. This limits deployment to machines with enough resources to run everything (currently ~8-16GB RAM).

Users want to:
- Run Nova's always-on services on low-power hardware (mini PC, Raspberry Pi) with compute-heavy work offloaded to a GPU machine or cloud
- Deploy Nova in different topologies without forking the codebase
- Have one-click cloud deployment via IaC (Terraform, AWS CDK, Ansible)
- Eventually support Kubernetes for cloud-native deployment and horizontal scaling

## Design Principles

1. **Location-agnostic services** — every inter-service URL is configurable, defaulting to current container DNS names (backwards compatible)
2. **Profiles, not forks** — a single codebase ships all deployment profiles; the difference is packaging, dependencies, and configuration
3. **Each layer delivers value independently** — the tier architecture works with Compose alone; K8s and IaC are additive, not prerequisite
4. **Minimum viable always-on** — the smallest useful Nova responds to chat, has memory, and routes to available LLMs

## Deployment Profiles

Four profiles define what runs and how. Profile selection has two axes:

1. **`NOVA_PROFILE` env var** — controls per-service runtime behavior (e.g., memory-service reads this to select ONNX vs PyTorch embedding backend, orchestrator uses it to enable/disable optional features)
2. **Compose file selection** — controls which services start (e.g., `docker-compose.gateway.yml` + `docker-compose.brain.yml` for Core)

A wrapper script or Makefile target ties these together so users pick one profile and both axes are set correctly.

### Nova Nano (2-4GB RAM)

Target: Raspberry Pi (4/5), ultra-cheap VPS, ARM or x86.

- **Single combined process** — orchestrator, chat-api, and basic memory run as routers in one FastAPI app
- **SQLite** instead of PostgreSQL (eliminates ~2GB overhead)
- **No PyTorch** — embeddings via API calls to the inference tier, or a bundled ONNX model (~50MB vs ~1.5GB)
- **No Redis** — in-process asyncio.Queue for task dispatch
- **Cloud-only LLM** — no local inference on this hardware
- **~500MB-1GB total RAM**
- **One-liner startup:** `docker run -e ANTHROPIC_API_KEY=... nova-nano`

The combined entry point:

```python
# Conceptual — same route handlers, no HTTP hops between services
app = FastAPI()
app.include_router(orchestrator_router, prefix="/api")
app.include_router(chat_router, prefix="/chat")
app.include_router(memory_router, prefix="/memory")
app.include_router(llm_proxy_router, prefix="/llm")
```

> **Needs further discussion:** Nano memory is realistically a **different backend**, not a compatibility layer over SQLite. The engram network relies on pgvector cosine similarity (`<=>` operator), recursive CTEs for spreading activation, JSONB columns, TIMESTAMPTZ, and concurrent async writers (SQLite has a single-writer lock). Options: (a) a simplified memory backend for Nano — keyword search + recency, no graph traversal; (b) keeping PostgreSQL even in Nano (kills the "eliminate 2GB" goal); (c) API-based embedding search where Nano calls a remote memory-service. This is the hardest design problem in the Nano profile.

### Nova Core (4-8GB RAM)

Target: Mini PC (Beelink N95, Intel NUC), modest VPS.

- **Separate lightweight services** via Docker Compose
- **PostgreSQL + Redis** — full engram network, proper queues
- **ONNX Runtime** for embeddings instead of PyTorch (~200MB vs ~1.5GB in memory-service)
- **Dashboard included** — full admin UI
- **LLM via remote inference or cloud** — no local models on this machine
- **Optional workers** — cortex, intel-worker run if RAM allows (~256MB each)
- **~3-5GB for Nova services**, leaving headroom for OS on 8GB hardware

RAM budget (8GB machine):

| Component | RAM |
|-----------|-----|
| OS + overhead | ~1.5 GB |
| PostgreSQL | 1-1.5 GB (tuned down from current 2GB limit) |
| Redis | 512 MB |
| memory-service (ONNX) | ~500-600 MB |
| orchestrator | ~500 MB - 1 GB |
| llm-gateway | ~200 MB |
| chat-api + chat-bridge | ~300 MB |
| dashboard + recovery | ~300 MB |
| **Total** | **~4.9 - 6.1 GB** |

The ~2-3GB headroom allows cortex (~256MB), intel-worker (~100MB), and comfortable operation without swap. If headroom is tighter than expected, cortex and intel-worker are the first services to disable.

### Nova Full (16GB+ RAM)

Target: Desktop, workstation, dedicated server.

- **All services** including cortex, intel-worker, knowledge-worker, voice-service
- **Full PyTorch** for neural router training
- **Local inference** — Ollama, vLLM, or SGLang with GPU
- **This is what Nova is today** — current docker-compose.yml, no changes needed
- **Remains the default** for users who run everything on one machine

### Nova Cloud (Kubernetes)

Target: AWS EKS, GCP GKE, self-hosted K8s, k3s clusters.

- **Helm chart deployment** — configurable replicas, resource limits, node affinity
- **Managed databases** — RDS for PostgreSQL, ElastiCache for Redis (or in-cluster)
- **GPU node pools** for inference tier, CPU node pools for gateway/brain tiers
- **Horizontal scaling** when needed (multi-tenant future)
- **Terraform/CDK provisions infrastructure**, Helm deploys Nova onto it

> **Needs further discussion:** Helm chart structure, cloud provider specifics (EKS vs GKE vs self-hosted), managed vs in-cluster databases, cost optimization.

## Service Tier Architecture

Services are grouped into three logical tiers by role:

### Gateway Tier (always-on, user-facing)

| Service | Purpose | RAM | Required? |
|---------|---------|-----|-----------|
| chat-api | WebSocket endpoint, the front door | ~150 MB | Yes |
| chat-bridge | Telegram/Slack relay | ~150 MB | Optional (profile: bridges) |
| dashboard | Admin UI (nginx) | ~50 MB | Yes |
| recovery | Backup/restore, stays alive when others crash | ~256 MB | Yes |
| llm-gateway | Routes LLM requests to inference tier | ~200 MB | Yes |
| voice-service | STT/TTS provider proxy | ~100 MB | Optional (profile: voice) |

Lightweight, low-RAM, must be reachable 24/7. On a distributed home setup, this tier lives on the always-on mini PC.

**Dashboard proxy caveat:** The dashboard's nginx.conf currently hardcodes upstream URLs (`http://orchestrator:8000`, `http://llm-gateway:8001`, etc.) at build time. For distributed deployment, nginx must resolve service URLs at container startup — either via `envsubst` templating or an nginx Lua module. This is a prerequisite for Phase 2.

### Brain Tier (core intelligence)

| Service | Purpose | RAM | Always-on? |
|---------|---------|-----|------------|
| orchestrator | Task queue, pipeline, MCP tools | ~500 MB - 1 GB | Yes (chat depends on it) |
| memory-service | Engram network, embeddings, retrieval | ~400 MB (ONNX) / ~1.5 GB (PyTorch) | Yes (orchestrator depends on it) |
| cortex | Autonomous thinking loop, goals | ~256 MB | Optional |
| intel-worker | RSS/Reddit/GitHub feed polling | ~100 MB | Optional |
| knowledge-worker | Web crawling, document ingestion | ~100 MB | Optional |
| neural-router-trainer | ML re-ranker training | ~512 MB | Optional (batch job, requires PyTorch) |

Orchestrator and memory-service must be co-located with the Gateway Tier (or reachable with low latency) because chat-api calls orchestrator synchronously. On the N95, they run locally. Cortex, intel-worker, and knowledge-worker are optional based on available resources.

**Neural-router-trainer on Core profile:** This service imports PyTorch at module level (it uses the memory-service Dockerfile). It cannot run on Core profile machines that use ONNX-only memory-service. It must either run on a Full/Inference tier machine or be disabled entirely in Core. Training is a periodic batch job, not latency-sensitive — running it on the Dell when available is fine.

**Recovery service caveat:** Recovery's inference controller (`recovery-service/app/inference/controller.py`) hardcodes URLs for llm-gateway, vLLM, and SGLang. In a distributed deployment where inference is remote, recovery's inference management features need configurable URLs or must be scoped to only manage local services.

### Inference Tier (LLM compute, fully remote by design)

| Backend | Where | Cost | Availability |
|---------|-------|------|--------------|
| Dell GPU (Ollama) | Home network, WoL | Free | When powered on |
| Cheap VPS (small Ollama model) | Cloud | ~$5-20/mo | Always-on |
| Cloud API providers | Anthropic, OpenAI, Groq, etc. | Per-token | Always-on |

The Inference Tier never runs on the Gateway/Brain machine in Core profile. The llm-gateway routes to it based on health probes and preference.

## Configurable Service Discovery

### Current state (hardcoded container DNS)

```yaml
# docker-compose.yml
environment:
  LLM_GATEWAY_URL: http://llm-gateway:8001
  MEMORY_SERVICE_URL: http://memory-service:8002
  ORCHESTRATOR_URL: http://orchestrator:8000
```

### New state (env-var driven, backwards compatible)

Every inter-service URL becomes an environment variable that **defaults to the current container name** so single-machine deployments need zero config changes:

| Variable | Default (single-machine) | Example (distributed) |
|----------|--------------------------|----------------------|
| `LLM_GATEWAY_URL` | `http://llm-gateway:8001` | `http://minipc.tailnet:8001` |
| `MEMORY_SERVICE_URL` | `http://memory-service:8002` | `http://minipc.tailnet:8002` |
| `ORCHESTRATOR_URL` | `http://orchestrator:8000` | `http://minipc.tailnet:8000` |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | `http://dell.tailnet:11434` |
| `POSTGRES_HOST` | `postgres` | `minipc.tailnet` |
| `REDIS_HOST` | `redis` | `minipc.tailnet` |

Services that already use env vars for URLs (like `OLLAMA_BASE_URL`) need no changes. Services that hardcode container names need to read from env vars instead.

**Scope of hardcoded URL cleanup (Phase 1):** The problem is worse than it appears. While some services (cortex, intel-worker, knowledge-worker) already use `os.getenv()` with defaults, the orchestrator — the most critical service — has config-based URLs in `config.py` but bypasses them with inline hardcoded URLs in multiple files:
- `orchestrator/app/router.py` — hardcoded health check URLs
- `orchestrator/app/engram_router.py` — hardcoded memory-service URLs (not using `settings.memory_service_url`)
- `orchestrator/app/tools/diagnosis_tools.py` — hardcoded URL map
- `orchestrator/app/tools/memory_tools.py` — hardcoded `MEMORY_BASE`
- `recovery-service/app/inference/controller.py` — hardcoded vllm/sglang/llm-gateway URLs
- `dashboard/nginx.conf` — six hardcoded upstream URLs (requires nginx template solution)

Phase 1 must include a comprehensive audit of all inter-service URLs, not just the obvious ones in config files.

### Networking: Tailscale for home, K8s DNS for cloud

**Home deployments:** Tailscale mesh VPN gives each machine a stable DNS name (`minipc.tailnet`, `dell.tailnet`) on a private network. Zero port forwarding, zero firewall config. Nova already has a Tailscale profile in docker-compose.yml.

**Cloud deployments:** K8s service discovery (`service-name.namespace.svc.cluster.local`) replaces Tailscale. Standard K8s networking, no special config.

**Single-machine:** Container DNS, same as today. Nothing changes.

### Inter-service auth & TLS

Today all inter-service traffic is on a Docker bridge network — trusted, unencrypted. In distributed deployments:

- **Home (Tailscale):** Traffic is encrypted in transit by Tailscale's WireGuard tunnel. No mutual auth between services, but the Tailscale network is private (only your devices). Acceptable for personal use.
- **Cloud (K8s):** Requires service mesh (Istio, Linkerd) or mTLS for encrypted inter-service communication. The `NOVA_ADMIN_SECRET` header protects admin endpoints but is not used for service-to-service calls — this gap must be addressed for cloud deployments.
- **VPS:** Tailscale between VPS and home provides encryption. Direct internet exposure without Tailscale is not supported.

## Health-Aware Inference Routing

### Current state

llm-gateway has routing strategies (`local-first`, `cloud-first`, etc.) that assume all backends are on the same network. The strategy is static — set once via env var or Redis config.

### New state: location-aware with health probing

The llm-gateway maintains a **live availability map** by periodically probing each configured inference endpoint:

```
Inference Endpoints (ordered by preference):
  1. Dell GPU (Ollama)    → http://dell.tailnet:11434    → HEALTHY / UNREACHABLE / DRAINING
  2. VPS (small Ollama)   → http://vps.tailnet:11434     → HEALTHY / UNREACHABLE / DRAINING
  3. Anthropic API        → https://api.anthropic.com    → HEALTHY / RATE_LIMITED / NO_KEY
  4. OpenAI API           → https://api.openai.com       → HEALTHY / RATE_LIMITED / NO_KEY
  5. Groq API             → https://api.groq.com         → HEALTHY / RATE_LIMITED / NO_KEY
```

**Routing logic:**

1. Walk the preference list top-to-bottom
2. Skip endpoints that are UNREACHABLE or DRAINING
3. For each HEALTHY endpoint, check if it can serve the requested model
4. If the top choice is UNREACHABLE and supports WoL, send a wake packet and queue the request (with a timeout — fall through to next backend if wake fails)
5. Rate-limited cloud endpoints get exponential backoff

**Health probing:**

- Local/VPS endpoints: HTTP health check every 30s (`GET /health/ready` or Ollama's `GET /api/tags`)
- Cloud APIs: Passive health — track recent request success/failure rates, no active probing
- Dell WoL state: Track last-seen time; if >5min since last health check response, mark as UNREACHABLE (asleep)

**Configuration:** The endpoint list and preference order are configurable via dashboard UI (runtime Redis config) or env vars. This extends the existing `llm.routing_strategy` Redis config.

> **Needs further discussion:** WoL integration details (magic packet from which machine? what's the wake-to-ready latency?), request queuing semantics while waiting for WoL, timeout thresholds.

## Data & State Management

### PostgreSQL

PostgreSQL holds engrams, sources, tasks, goals, and cortex state. It's the most critical piece of persistent state.

**Single-machine / Core:** Postgres runs on the always-on machine (N95/mini PC). All services connect to it directly. For Core profile on 8GB machines, PostgreSQL needs tuning beyond just lowering the container memory limit — `shared_buffers`, `work_mem`, and `effective_cache_size` must be set appropriately. pgvector similarity searches load vectors into `work_mem` for sorting; with large engram collections (10k+ at 768 dimensions), a single spreading activation query can spike memory. Lowering the container limit without tuning causes OOM kills rather than graceful degradation.

**Cloud / K8s:** Options:
- Managed database (RDS, Cloud SQL) — recommended for production
- In-cluster PostgreSQL with PVC — simpler but requires backup strategy
- Both use the same `POSTGRES_HOST` env var

**Nano:** SQLite replaces PostgreSQL. Requires a compatibility layer for engram queries (pgvector similarity search doesn't exist in SQLite — would need an alternative like sqlite-vss or API-based embedding search).

**Backup:** Recovery service handles backup/restore. For distributed deployments, backups should be pushed to object storage (S3, etc.) in addition to local filesystem.

### Redis

Redis handles task queues, rate limiting, session state, and runtime config. It's ephemeral by design — losing Redis data is recoverable (tasks re-queue, sessions re-establish).

**Single-machine / Core:** Redis runs on the always-on machine alongside PostgreSQL.

**Cloud / K8s:** ElastiCache or in-cluster Redis. Single-node is fine — Nova doesn't need Redis clustering.

**Nano:** Replaced by in-process asyncio.Queue and dict-based state. No persistence needed.

### Volumes & Filesystem

| Data | Where | Cross-machine concern |
|------|-------|-----------------------|
| `./data/postgres` | Always-on machine | Must not be shared; single writer |
| `./data/redis` | Always-on machine | Must not be shared; single writer |
| `./data/sources` | Always-on machine (memory-service reads/writes) | If knowledge-worker runs elsewhere, it needs to push content via API, not filesystem |
| `NOVA_WORKSPACE` | Orchestrator's machine | Agent working directory — must be local to orchestrator |
| Model caches (Ollama, vLLM) | Inference tier machines | Each inference node manages its own model cache |
| Backups | Always-on machine + remote (S3) | Recovery service writes locally; push to remote for durability |

**Key constraint:** No shared filesystems between machines. Services on different machines communicate via HTTP APIs, not shared volumes. The `./data/sources` directory is only accessed by memory-service; knowledge-worker pushes content via the orchestrator/memory-service API.

## Deployment Adapters & IaC

### Docker Compose Tiers (Phase 1 — solves the immediate need)

Split the current monolithic `docker-compose.yml` into composable tier files:

```
docker-compose.yml              # Base: postgres, redis, shared config
docker-compose.gateway.yml      # Gateway tier services
docker-compose.brain.yml        # Brain tier services
docker-compose.inference.yml    # Local inference (Ollama, vLLM, etc.)
docker-compose.gpu.yml          # GPU overlay (existing)
docker-compose.rocm.yml         # ROCm overlay (existing)
```

Usage:

```bash
# Single machine (equivalent to today):
docker compose -f docker-compose.yml \
  -f docker-compose.gateway.yml \
  -f docker-compose.brain.yml \
  -f docker-compose.inference.yml up -d

# Mini PC (Core profile — gateway + brain, no inference):
docker compose -f docker-compose.yml \
  -f docker-compose.gateway.yml \
  -f docker-compose.brain.yml up -d

# Dell (inference only — joins via Tailscale):
# Note: inference tier compose file must be self-contained (own network
# definition, no dependency on base file's YAML anchors or postgres/redis).
# Inference services don't need postgres or redis — they just serve models.
docker compose -f docker-compose.inference.yml \
  -f docker-compose.gpu.yml up -d
```

Makefile targets for common configurations:

```makefile
deploy-core:     # Mini PC: gateway + brain
deploy-inference: # GPU machine: inference only
deploy-full:     # Single machine: everything
deploy-nano:     # Ultra-light: combined process
```

### Helm Charts (Phase 2 — K8s deployment)

A Helm chart with values files for each profile:

```
deploy/helm/nova/
  Chart.yaml
  values.yaml              # Defaults (Full profile)
  values-core.yaml         # Core profile overrides
  values-cloud.yaml        # Cloud profile (managed DB, GPU node pools)
  templates/
    gateway/               # Gateway tier deployments + services
    brain/                 # Brain tier deployments + services
    inference/             # Inference tier deployments + services
    config/                # ConfigMaps, Secrets
    ingress.yaml           # Ingress controller config
```

Usage:

```bash
helm install nova ./deploy/helm/nova -f values-cloud.yaml
```

> **Needs further discussion:** Chart structure, ingress strategy, secret management (Vault? Sealed Secrets? External Secrets Operator?), GPU node affinity, PVC sizing.

### Terraform / AWS CDK (Phase 3 — infrastructure provisioning)

IaC provisions the infrastructure that Nova deploys onto:

```
deploy/terraform/
  aws/
    eks.tf                 # EKS cluster, node groups (CPU + GPU)
    rds.tf                 # PostgreSQL (pgvector extension)
    elasticache.tf         # Redis
    networking.tf          # VPC, subnets, security groups
    s3.tf                  # Backup storage
  modules/
    nova-cluster/          # Reusable module for Nova infrastructure
```

Or AWS CDK (TypeScript):

```
deploy/cdk/
  lib/
    nova-stack.ts          # VPC + EKS + RDS + ElastiCache + S3
  bin/
    deploy.ts              # Entry point with profile selection
```

> **Needs further discussion:** AWS CDK vs Terraform (Jeremy is studying for SAA-C03, so CDK aligns with AWS focus — but Terraform is cloud-agnostic). Single cloud vs multi-cloud. Cost estimation for typical cloud deployments.

### Ansible (Phase 3 — bare-metal / VPS provisioning)

For users who deploy to bare metal or VPS (not K8s):

```
deploy/ansible/
  inventory/
    example-home.yml       # Mini PC + Dell example
    example-vps.yml        # VPS-only example
  playbooks/
    setup-node.yml         # Install Docker, Tailscale, configure firewall
    deploy-gateway.yml     # Deploy gateway tier Compose files
    deploy-brain.yml       # Deploy brain tier Compose files
    deploy-inference.yml   # Deploy inference tier with GPU setup
  roles/
    common/                # Docker, Tailscale, monitoring agent
    nova-gateway/          # Gateway tier deployment
    nova-brain/            # Brain tier deployment
    nova-inference/        # Inference tier with GPU detection
```

> **Needs further discussion:** Ansible vs just shell scripts for simple cases, Tailscale auth key management, WoL configuration.

## Build Sequence

When implementation begins, build in this order. Each phase is independently useful:

### Phase 1: Configurable Service Discovery
- Comprehensive audit of all inter-service URLs (orchestrator has hardcoded URLs in 4+ files beyond config.py)
- Replace hardcoded container names with env vars across all services
- Convert dashboard nginx.conf to envsubst template for runtime URL resolution
- Update recovery service inference controller to use configurable URLs
- Backwards compatible — defaults to current behavior
- **Value:** Services can talk across machines with just env var changes

### Phase 2: Compose Tier Files
- Split docker-compose.yml into gateway/brain/inference tier files
- Create Makefile targets for common deployment configs
- Document the profiles and which services go where
- **Value:** Deploy Nova across two machines (mini PC + GPU desktop)

### Phase 3: Health-Aware Inference Routing
- Upgrade llm-gateway to probe multiple remote endpoints
- Add WoL integration for waking GPU machines
- Dashboard UI for managing inference endpoints and preference order
- **Value:** Automatic fallback when Dell sleeps, seamless cloud failover

### Phase 4: Memory-Service Optimization
- Make PyTorch an optional dependency; conditional imports for neural router code
- Add ONNX Runtime as alternative embedding backend, selectable via `NOVA_PROFILE` or config
- Ship both backends — Full profile uses PyTorch, Core uses ONNX
- Disable neural-router-trainer in Core profile (it requires PyTorch)
- Tune PostgreSQL for 8GB machines (shared_buffers, work_mem, effective_cache_size — not just container limit)
- Profile and optimize RAM usage across all services
- **Value:** Nova Core runs comfortably on 8GB mini PC

### Phase 5: Helm Charts + IaC
- Create Helm chart with per-profile values files
- Terraform/CDK modules for AWS infrastructure
- Ansible playbooks for bare-metal/VPS
- **Value:** One-click cloud deployment, reproducible infrastructure

### Phase 6: Nova Nano (Future)
- Combined single-process entry point
- SQLite backend with engram compatibility layer
- In-process queues replacing Redis
- Minimal Docker image (~200MB)
- **Value:** Run Nova on a Raspberry Pi or $5/mo VPS

## Hardware Reference

### Jeremy's setup (design target for Core profile)

**Always-on (N95 mini PC):**
- Beelink N95: Intel 12th gen, 4 cores @ 3.4GHz, 8GB DDR4, 256GB SSD
- Runs: Gateway Tier + Brain Tier (Core profile)
- WoL capable

**On-demand GPU (Dell desktop):**
- Personal daily driver, not always on
- GPU for local inference (Ollama)
- WoL capable — N95 can wake it when LLM requests arrive
- Runs: Inference Tier only

**Cloud fallback:**
- Cloud API providers (Anthropic, OpenAI, Groq) — pay-per-token
- Optional: cheap VPS with small Ollama model (~$5-20/mo) — always-on middle tier
- Optional: spin-up-on-demand cloud GPU for heavy inference

### Resource constraints driving design decisions

| Constraint | Impact |
|-----------|--------|
| N95 has 8GB RAM total | Memory-service must use ONNX (realistically ~500-600MB with model loaded, vs ~1.5GB PyTorch); postgres tuned down with proper shared_buffers/work_mem settings, not just a lower container limit |
| N95 has no GPU | All inference is remote — llm-gateway must route to Dell/VPS/cloud |
| Dell is intermittent | Health-aware routing with WoL + cloud fallback is required, not optional |
| K3s control plane needs ~500MB-1GB | K8s on the N95 is not viable; Compose is the right tool for home deployment |
| Raspberry Pi has 4-8GB ARM | Nano profile must eliminate PyTorch, PostgreSQL, and Redis entirely |

## Open Questions

These must be resolved before implementation:

1. **Memory-service ONNX migration** — Which embedding model? What's the accuracy delta vs PyTorch? Can we ship both backends and select via config?
2. **SQLite engram compatibility (Nano)** — pgvector similarity search has no SQLite equivalent. Options: sqlite-vss, API-based embedding search, or a simplified retrieval mode.
3. **WoL integration** — Which service sends the magic packet? How long to wait for Dell to boot + Ollama to load models before falling through to cloud?
4. **Helm chart scope** — Full K8s deployment is a large surface area. Start with a minimal chart (Core profile equivalent) or comprehensive from day one?
5. **Terraform vs CDK** — Terraform is cloud-agnostic; CDK is AWS-native and aligns with SAA-C03 study. Could support both, or pick one.
6. **Secret management in cloud** — .env files don't work in K8s/cloud. AWS Secrets Manager? HashiCorp Vault? K8s Sealed Secrets?
7. **Nano combined-process feasibility** — How much refactoring is needed to run orchestrator + memory-service in-process? Are there threading/async conflicts?
8. **Cost modeling** — What does a typical cloud deployment cost? Helps users decide between home hardware and cloud.
9. **Dashboard nginx template** — envsubst vs Lua module for runtime URL resolution. envsubst is simpler but limited (no conditionals); Lua is more flexible but adds complexity.
10. **Recovery service scope in distributed mode** — Recovery currently manages inference backends via Docker socket. When inference is remote, should recovery only manage local services, or should it gain SSH/API-based remote management?
11. **Inter-service auth for cloud** — Service-to-service calls have no auth today (trusted Docker network). Cloud deployments need either service mesh mTLS or a shared service token.
