FROM python:3.12-slim

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

EXPOSE 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
