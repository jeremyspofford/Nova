# Phase 0: Foundation API — Design Spec

**Date:** 2026-04-12
**Status:** Approved
**Scope:** `services/api` + `infra/docker-compose.yml`

---

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Database | PostgreSQL | Phase 3 HA entity sync generates continuous write load; SQLite would require painful migration |
| API framework | FastAPI (Python) | Nova-lite (Phase 2) needs LLM/agent SDKs that are Python-native; shared language avoids cross-service boundary |
| Service structure | Single service, domain module boundaries | Ships Phase 0 in hours; module boundaries (routers/, models/, schemas/) make later extraction clean |
| Migrations | Alembic, run on container startup | Simplest for local dev; `depends_on: service_healthy` in Compose handles Postgres readiness |

---

## File Layout

```
nova-suite/
├── services/
│   └── api/
│       ├── Dockerfile
│       ├── requirements.txt
│       ├── alembic.ini
│       ├── alembic/
│       │   ├── env.py
│       │   └── versions/
│       │       └── 0001_initial_schema.py
│       └── app/
│           ├── main.py            # FastAPI app factory + lifespan
│           ├── database.py        # SQLAlchemy engine + session dependency
│           ├── config.py          # Settings via pydantic-settings / env vars
│           ├── models/            # SQLAlchemy ORM models
│           │   ├── __init__.py
│           │   ├── task.py
│           │   ├── event.py
│           │   ├── run.py
│           │   ├── approval.py
│           │   ├── board_column.py
│           │   ├── entity.py
│           │   ├── tool.py
│           │   └── llm_provider.py
│           ├── schemas/           # Pydantic request/response schemas
│           │   ├── __init__.py
│           │   ├── task.py        # full request/response schemas
│           │   ├── common.py      # shared enums (Priority, RiskClass, etc.)
│           │   ├── event.py       # stub schema (used by router for Swagger docs)
│           │   ├── run.py         # stub schema
│           │   ├── approval.py    # stub schema
│           │   ├── board.py       # stub schema
│           │   ├── tool.py        # stub schema
│           │   ├── entity.py      # stub schema
│           │   └── llm_provider.py # stub schema
│           └── routers/           # FastAPI routers
│               ├── __init__.py
│               ├── health.py      # GET /health, GET /system/info — IMPLEMENTED
│               ├── tasks.py       # GET/POST /tasks, GET/PATCH /tasks/{id} — IMPLEMENTED
│               ├── events.py      # POST/GET /events — STUB (501)
│               ├── board.py       # GET /board, PATCH /board/tasks/{id} — STUB (501)
│               ├── tools.py       # GET /tools, GET /tools/{name}, POST /tools/{name}/invoke — STUB (501)
│               ├── runs.py        # GET /runs, GET /runs/{id}, GET /tasks/{id}/runs — STUB (501)
│               ├── approvals.py   # POST /tasks/{id}/approvals, GET /approvals/{id}, POST /approvals/{id}/respond — STUB (501)
│               ├── entities.py    # GET /entities, GET /entities/{id}, POST /entities/sync — STUB (501)
│               └── llm.py         # GET /llm/providers, GET /llm/providers/{id}, POST /llm/route — STUB (501)
└── infra/
    └── docker-compose.yml
```

---

## Implemented Endpoints (Phase 0)

### `GET /health`
Returns aggregate health including DB connectivity check.
```json
{"status": "ok", "db": "ok"}
```
Returns `{"status": "degraded", "db": "error"}` if DB is unreachable (HTTP 200 either way — health endpoints should not 5xx for monitoring compatibility).

### `GET /system/info`
Returns static deployment metadata.
```json
{"service": "nova-api", "version": "0.1.0", "deployment_mode": "local"}
```

### `POST /tasks`
Creates a task. Required: `title`. All other fields optional per spec.
Returns HTTP 201 with full `Task` object. Defaults: `status=inbox`, `last_decision=none`, `priority=normal`, `risk_class=low`, `approval_required=false`, `labels=[]`, `metadata={}`.

### `GET /tasks`
Lists tasks. Supports all filters from spec: `status`, `owner_type`, `owner_id`, `board_column_id`, `priority`, `risk_class`, `approval_required`, `limit` (default 50), `offset` (default 0).
Returns `{"tasks": Task[]}`.

### `GET /tasks/{id}`
Returns single Task or 404.

### `PATCH /tasks/{id}`
Partial update of mutable fields: `title`, `description`, `goal`, `status`, `last_decision`, `priority`, `board_column_id`, `owner_type`, `owner_id`, `due_at`, `next_check_at`, `result_summary`, `labels`, `metadata`.
Returns HTTP 200 with updated Task, or 404.

**Safety signal note:** `risk_class` and `approval_required` are excluded from PATCH — this is consistent with the frozen 15-16 spec which does not list them as allowed updates. They are set at creation and can only be changed through the policy layer (Phase 1+). Do not add them to the PATCH schema without a policy spec.

---

## Stubbed Endpoints (Phase 0 — return HTTP 501)

All routes in: events, board, tools, runs, approvals, entities, llm routers.
Each stub is registered on the app so the full API surface is documented in `/docs` (Swagger UI).

---

## Data Models

All 8 models from `15-16-data-models-and-apis.md` are created as SQLAlchemy ORM models and migrated in the initial Alembic revision. JSONB used for `payload`, `state`, `metadata`, `input_schema`, `output_schema`, `options`, `labels` columns in PostgreSQL.

**Tool primary key:** The `Tool` model uses `name` (string) as its primary key — there is no surrogate `id` column. This matches the 15-16 spec exactly. Do not add an `id` column.

**Health response extension:** The spec adds a `"db"` key to the health response beyond the minimum `{"status": "ok"}` required by CLAUDE.md. This is intentional — DB connectivity is the only meaningful health signal in Phase 0.

---

## Infrastructure

### docker-compose.yml
Two services: `db` (postgres:16-alpine) and `api` (local Dockerfile build).
- `db` exposes port 5432, uses named volume for persistence
- `db` has a `pg_isready` healthcheck
- `api` depends on `db` with `condition: service_healthy`
- `api` runs `alembic upgrade head && uvicorn app.main:app` as its command
- `api` exposes port 8000

### Startup sequencing
The `api` container command is `sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"`. Migration failure exits the container with a non-zero code, which Docker Compose surfaces as a crash loop. No restart policy is set in Phase 0 — a failed migration should be visible immediately, not retried silently. The `config.py` Settings class must validate `DATABASE_URL` is present at import time (fail-fast before the migration runs).

### Environment variables (api service)
```
DATABASE_URL=postgresql://nova:nova@db:5432/nova
DEPLOYMENT_MODE=local
```
No application secrets are required in Phase 0 — authentication is out of scope. Do not hardcode credentials in source files; the database password is set only via environment variables.

---

## Phase 0 Success Criteria

- [ ] `docker compose up` starts without errors
- [ ] `GET /health` returns `{"status": "ok", "db": "ok"}`
- [ ] `POST /tasks` with `{"title": "test"}` returns a task with an ID
- [ ] `GET /tasks` returns `{"tasks": [...]}`
- [ ] All 8 DB tables created by Alembic migration
- [ ] Swagger UI available at `http://localhost:8000/docs`

---

## Out of Scope (Phase 0)

- Authentication / API keys
- WebSocket / real-time updates
- Nova-lite agent loop
- Nova Board frontend
- Home Assistant integration
- Workflow adapter (n8n/Windmill)
