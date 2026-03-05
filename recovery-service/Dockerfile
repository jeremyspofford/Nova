FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install standalone docker compose CLI (needed for profiled service management)
RUN ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${ARCH}" \
      -o /usr/local/bin/docker-compose && \
    chmod +x /usr/local/bin/docker-compose && \
    ln -sf /usr/local/bin/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose 2>/dev/null; \
    mkdir -p /usr/local/lib/docker/cli-plugins && \
    ln -sf /usr/local/bin/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose

WORKDIR /app

COPY recovery-service/pyproject.toml .
RUN pip install --no-cache-dir .

COPY recovery-service/app/ app/

EXPOSE 8888

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8888"]
