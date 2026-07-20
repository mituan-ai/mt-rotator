FROM node:22.18.0-alpine AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM golang:1.26.5-alpine3.23 AS caddy-builder
RUN CGO_ENABLED=0 go install github.com/caddyserver/caddy/v2/cmd/caddy@v2.11.4

FROM caddy:2.11.4-alpine
RUN apk upgrade --no-cache \
    && addgroup -S caddy \
    && adduser -S -D -H -G caddy caddy
COPY --from=caddy-builder /go/bin/caddy /usr/bin/caddy
RUN setcap cap_net_bind_service=+ep /usr/bin/caddy
COPY infra/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend-builder /build/dist /srv
USER caddy
