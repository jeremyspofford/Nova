# 13 – Observability Specification (MVP Stub)

## MVP approach

- API logs to stdout (structured JSON)
- Basic metrics: task/run counts by status, LLM calls by provider
- `/health` endpoint tracks service uptime and DB connectivity
- Task/run history serves as audit trail

## v2 expansion

- Centralized metrics (Prometheus/Grafana)
- Distributed tracing for LLM/tool calls
- Event streams for real-time dashboards

MVP relies on task/run records + basic logging.
