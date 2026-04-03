FROM python:3.12-slim

WORKDIR /app

# Install nova-contracts first (rarely changes)
COPY nova-contracts /nova-contracts
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir /nova-contracts

COPY baseline-mem0/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

COPY baseline-mem0/app/ app/

# Create data directory for Mem0's local Qdrant storage
RUN mkdir -p /data/mem0

EXPOSE 8004

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
