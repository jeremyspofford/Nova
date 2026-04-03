FROM alpine:3.20

RUN apk add --no-cache \
    neovim \
    ttyd \
    git \
    ripgrep \
    fd \
    nodejs \
    npm \
    python3 \
    py3-pip \
    curl \
    openssh-client \
    bash

COPY editor-neovim/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /workspace

EXPOSE 7681

HEALTHCHECK --interval=5s --timeout=5s --retries=3 --start-period=10s \
    CMD curl -sf http://localhost:7681/editor-neovim/ || exit 1

ENTRYPOINT ["/entrypoint.sh"]
