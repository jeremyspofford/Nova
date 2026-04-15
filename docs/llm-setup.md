# LLM Setup

Nova Suite is LLM-agnostic. Nova-lite and the API use two environment variables to connect to any Ollama-compatible endpoint:

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | *(empty)* | Full base URL of the Ollama-compatible API |
| `OLLAMA_MODEL` | `gemma3:4b` | Model tag to use for task execution |

Set these in `infra/.env` (copy from `infra/.env.example` if it exists, or create it):

```bash
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma4:e2b
```

---

## Ollama Setup

### Windows + WSL2 (recommended for Windows development)

Install Ollama from **ollama.com** on Windows. It runs as a background service accessible from both Windows and WSL2.

**Start Ollama:** Launch the Ollama app from the Start menu. It will appear in the system tray.

#### Enable mirrored networking (one-time setup)

WSL2's default networking assigns a new gateway IP on every restart, which breaks stable `localhost` access to Windows services. Enable mirrored mode to fix this permanently:

```bash
echo -e "[wsl2]\nnetworkingMode=mirrored" >> /mnt/c/Users/jeremy/.wslconfig
wsl.exe --shutdown   # restarts WSL2 — reopen your terminal after this
```

After restarting, `localhost` in WSL2 maps directly to Windows localhost. No firewall rules needed.

**Pull a model from WSL2:**

```bash
OLLAMA_HOST=http://localhost:11434 ollama pull gemma4:e2b
```

**Verify it's reachable from WSL2:**

```bash
curl http://localhost:11434
# Expected: "Ollama is running"
```

**`.env` config:**

```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=gemma4:e2b
```

> **Note:** When running services via Docker Compose, containers cannot reach `localhost` on the Windows host. Use `http://host.docker.internal:11434` in `infra/.env`. For WSL2 commands run directly (e.g., `ollama pull`), use `OLLAMA_HOST=http://localhost:11434`.

---

### Native Linux

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma4:e2b
```

**`.env` config:**

```bash
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma4:e2b
```

---

### macOS

Install from **ollama.com** or via Homebrew:

```bash
brew install ollama
ollama serve &
ollama pull gemma4:e2b
```

**`.env` config:**

```bash
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma4:e2b
```

---

## Tested Models

### Gemma 4 (recommended)

Google's Gemma 4 family. Multimodal (text + image). 128K–256K context window.

| Tag | Size on disk | Minimum VRAM | Notes |
|---|---|---|---|
| `gemma4:e2b` | 7.2 GB | 8 GB | Best fit for 8 GB cards (e.g. RTX 3060 Ti) |
| `gemma4:e4b` | 9.6 GB | 10 GB | Requires 10 GB+ VRAM |
| `gemma4:26b` | 18 GB | 20 GB | Workstation GPU or multi-GPU |

```bash
OLLAMA_MODEL=gemma4:e2b   # 8 GB VRAM
OLLAMA_MODEL=gemma4:e4b   # 10–12 GB VRAM
```

### Gemma 3 (previous generation)

Smaller and well-tested. Good fallback for very constrained hardware.

| Tag | Size on disk | Minimum VRAM |
|---|---|---|
| `gemma3:1b` | ~1 GB | 2 GB |
| `gemma3:4b` | ~3 GB | 4 GB |
| `gemma3:12b` | ~8 GB | 10 GB |

```bash
OLLAMA_MODEL=gemma3:4b
```

---

## Cloud / OpenAI-compatible APIs

Any OpenAI-compatible endpoint works by setting `OLLAMA_BASE_URL` to the provider's base URL. No code changes needed.

**OpenAI:**

```bash
OLLAMA_BASE_URL=https://api.openai.com/v1
OLLAMA_MODEL=gpt-4o-mini
```

**Anthropic (via a compatibility proxy):**

```bash
OLLAMA_BASE_URL=https://your-proxy/v1
OLLAMA_MODEL=claude-sonnet-4-6
```

> Note: API key injection is not yet implemented. If you need bearer token auth, open an issue.

---

## Troubleshooting

**`could not connect to ollama server`**

Running `ollama pull` or `ollama list` from WSL2 without `OLLAMA_HOST` set will try to reach a local WSL2 server that doesn't exist. Fix:

```bash
export OLLAMA_HOST=http://host.docker.internal:11434
ollama pull gemma4:e2b
```

**Model too large for VRAM**

Ollama will attempt to run the model on CPU if it doesn't fit in VRAM. This works but is very slow for nova-lite's loop. Use a smaller model tag instead.

**`host.docker.internal` not resolving**

On some Linux Docker setups `host.docker.internal` is not automatically added. Add it to the `api` and `nova-lite` services in `docker-compose.yml`:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

**Nova-lite not creating tasks**

Check the nova-lite logs: `docker compose logs nova-lite`. If you see LLM connection errors, verify `OLLAMA_BASE_URL` is set in `infra/.env` and the model has been pulled.
