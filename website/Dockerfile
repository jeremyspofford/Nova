# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM node:22-alpine AS builder
WORKDIR /app

COPY website/package.json website/package-lock.json* ./
RUN npm install

COPY website/ .
RUN npm run build

# ── Stage 2: serve ────────────────────────────────────────────────────────────
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY website/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 4000
