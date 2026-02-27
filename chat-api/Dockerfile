FROM python:3.12-slim

WORKDIR /app

COPY nova-contracts /nova-contracts
RUN pip install --no-cache-dir /nova-contracts

COPY chat-api/pyproject.toml .
RUN pip install --no-cache-dir .

COPY chat-api/app/ app/

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
