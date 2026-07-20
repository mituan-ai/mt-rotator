FROM node:22.18.0-alpine AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM caddy:2.10.2-alpine
COPY infra/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend-builder /build/dist /srv
