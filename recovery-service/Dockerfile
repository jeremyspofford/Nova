FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY recovery-service/pyproject.toml .
RUN pip install --no-cache-dir .

COPY recovery-service/app/ app/

EXPOSE 8888

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8888"]
