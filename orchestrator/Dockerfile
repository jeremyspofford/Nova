FROM python:3.12-slim

# Node.js is needed for npx-based MCP servers (e.g. puppeteer, brave-search)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY nova-contracts /nova-contracts
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir /nova-contracts

COPY nova-worker-common /nova-worker-common
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir /nova-worker-common

COPY orchestrator/pyproject.toml .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install .

COPY orchestrator/app/ app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
