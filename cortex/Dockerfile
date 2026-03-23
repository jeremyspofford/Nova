FROM python:3.12-slim

ARG NOVA_UID=1000
ARG NOVA_GID=1000
RUN groupadd -g ${NOVA_GID} nova && \
    useradd -u ${NOVA_UID} -g nova -m -s /bin/sh nova

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY cortex/pyproject.toml .
RUN pip install --no-cache-dir .

COPY cortex/app/ app/
RUN chown -R nova:nova /app

USER nova
EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
