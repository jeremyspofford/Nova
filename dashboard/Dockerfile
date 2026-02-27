# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

# Install dependencies first for better layer caching
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm install

# Copy source and build
COPY dashboard/ .
RUN npm run build

# ── Stage 2: serve ────────────────────────────────────────────────────────────
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY dashboard/nginx.conf /etc/nginx/conf.d/default.conf

# Remove the default nginx config that also listens on 80
RUN rm -f /etc/nginx/conf.d/default.conf.bak 2>/dev/null; \
    sed -i '/listen.*80/d' /etc/nginx/nginx.conf 2>/dev/null || true
COPY dashboard/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000
