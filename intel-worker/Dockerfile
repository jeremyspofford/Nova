FROM python:3.12-slim
RUN apt-get update && apt-get install -y curl && apt-get clean
WORKDIR /app
COPY intel-worker/pyproject.toml .
RUN pip install .
COPY intel-worker/app/ app/
EXPOSE 8110
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8110"]
