FROM python:3.12-slim

WORKDIR /app

COPY nova-contracts /nova-contracts
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir /nova-contracts

COPY voice-service/pyproject.toml .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install .

COPY voice-service/app/ app/

EXPOSE 8130

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8130"]
