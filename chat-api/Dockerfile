FROM python:3.12-slim

ARG NOVA_UID=1000
ARG NOVA_GID=1000
RUN groupadd -g ${NOVA_GID} nova && \
    useradd -u ${NOVA_UID} -g nova -m -s /bin/sh nova

WORKDIR /app

COPY nova-contracts /nova-contracts
RUN pip install --no-cache-dir /nova-contracts

COPY chat-api/pyproject.toml .
RUN pip install --no-cache-dir .

COPY chat-api/app/ app/
RUN chown -R nova:nova /app

USER nova
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
