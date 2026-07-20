FROM node:22.18.0-alpine AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM caddy:2.11.4-alpine
RUN apk upgrade --no-cache \
    && addgroup -S caddy \
    && adduser -S -D -H -G caddy caddy
RUN setcap cap_net_bind_service=+ep /usr/bin/caddy
COPY infra/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend-builder /build/dist /srv
USER caddy
