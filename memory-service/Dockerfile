FROM python:3.12-slim

ARG NOVA_UID=1000
ARG NOVA_GID=1000
RUN groupadd -g ${NOVA_GID} nova && \
    useradd -u ${NOVA_UID} -g nova -m -s /bin/sh nova

WORKDIR /app

# Install build tools for asyncpg compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && rm -rf /var/lib/apt/lists/*

# Install nova-contracts first (rarely changes)
COPY nova-contracts /nova-contracts
RUN pip install --no-cache-dir /nova-contracts

COPY memory-service/pyproject.toml .
RUN pip install --no-cache-dir .

COPY memory-service/app/ app/
RUN chown -R nova:nova /app

USER nova
EXPOSE 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
