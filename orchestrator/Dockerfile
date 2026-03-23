FROM python:3.12-slim

# Node.js is needed for npx-based MCP servers (e.g. puppeteer, brave-search)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Non-root user — UID/GID match the host user so workspace files have correct
# ownership. Override at build time: --build-arg NOVA_UID=1001
ARG NOVA_UID=1000
ARG NOVA_GID=1000
RUN groupadd -g ${NOVA_GID} nova && \
    useradd -u ${NOVA_UID} -g nova -m -s /bin/sh nova

WORKDIR /app

COPY nova-contracts /nova-contracts
RUN pip install --no-cache-dir /nova-contracts

COPY orchestrator/pyproject.toml .
RUN pip install --no-cache-dir .

COPY orchestrator/app/ app/
RUN chown -R nova:nova /app

USER nova

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
