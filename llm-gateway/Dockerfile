FROM python:3.12-slim

WORKDIR /app

COPY nova-contracts /nova-contracts
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir /nova-contracts

COPY nova-worker-common /nova-worker-common
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir /nova-worker-common

COPY llm-gateway/pyproject.toml .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install .

COPY llm-gateway/app/ app/

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
