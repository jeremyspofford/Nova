# Repo Structure

```bash
nova-suite/
  architecture-pack/      # Specs and diagrams (00–18)
  services/
    api/                  # Core HTTP API & data models
    nova-lite/            # Planner/orchestrator loop
    board/                # Board backend API (if separate)
    state/                # Home Assistant & entity sync
    workflow-adapter/     # n8n/Windmill integration
  web/
    board-ui/             # Frontend for Nova Board
  infra/
    docker-compose.yml    # Local dev stack
    env.example           # Sample configuration
  CLAUDE.md               # Implementation instructions for Claude
```
