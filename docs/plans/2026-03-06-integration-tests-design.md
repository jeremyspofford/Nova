# Integration Test Harness Design

## Goal

Add a real integration test suite that validates Nova services work correctly
by making actual HTTP/WebSocket calls against running services. No mocks.

## Structure

```
tests/
  conftest.py           # Service URLs, auth fixtures, skip logic, cleanup
  requirements.txt      # Test dependencies
  test_health.py        # All services respond to health probes
  test_orchestrator.py  # Agent CRUD, task submission, keys, config, pods
  test_memory.py        # Memory store/search/delete/bulk, facts, context
  test_llm_gateway.py   # Model listing, discovery, provider catalog
  test_recovery.py      # Status, backups, service listing
  test_chat_api.py      # WebSocket connectivity
  test_pipeline.py      # Full pipeline run (opt-in, requires LLM)
```

## Key Decisions

1. **Top-level directory** — integration tests live at repo root, not per-service
2. **Real services only** — tests hit localhost endpoints, no mocks
3. **Self-cleaning** — all test resources use `nova-test-` prefix, cleaned up via fixture teardown
4. **Pipeline opt-in** — `requires_llm` marker skips pipeline tests unless a provider is available
5. **Runs against dev stack** — assumes `make dev` is already running

## conftest.py Design

- Base URLs from env vars with defaults (localhost:8000, 8001, 8002, 8080, 8888)
- Shared `httpx.AsyncClient` per service (session-scoped)
- Reads `NOVA_ADMIN_SECRET` from `.env` file
- Session fixture: creates test API key at start, revokes at teardown
- `requires_llm` marker: checks `/models` for available providers, skips if none

## Test Data Strategy

- Fixtures use `yield` pattern: create → yield → delete
- Resources named with `nova-test-` prefix
- No separate test database — tests only touch what they create

## Makefile Targets

- `make test` — full suite (skips pipeline if no LLM)
- `make test-quick` — health endpoints only

## Dependencies

pytest, pytest-asyncio, httpx, websockets, python-dotenv
