FROM python:3.12-slim

WORKDIR /app

COPY nova-contracts /nova-contracts
RUN pip install --no-cache-dir /nova-contracts

COPY chat-bridge/pyproject.toml .
RUN pip install --no-cache-dir .

COPY chat-bridge/app/ app/

EXPOSE 8090

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
