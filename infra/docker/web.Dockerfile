# syntax=docker/dockerfile:1
# Web app: static Vite build served by Caddy, which is also the reverse proxy (infra/proxy/Caddyfile).
# Build from the repository root:  docker build -f infra/docker/web.Dockerfile -t facilityhub-web .
FROM node:22-alpine@sha256:5b05da3f938f1c604b24c633646d48805a6667f378cb4908438616f3cc48a0bf AS build
RUN corepack enable
WORKDIR /build/web
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
# vite.config.ts reads the display name from ../config/app.yaml; the build needs nothing else from the repo.
COPY config/app.yaml /build/config/app.yaml
COPY CHANGELOG.md /build/CHANGELOG.md
RUN pnpm build

FROM caddy:2-alpine@sha256:78bd35025c7ba85961dd149ae670315129954e77abe2383ac47c89106b35ade9
RUN mkdir -p /srv/web /data /config && chown -R 10001:10001 /data /config
COPY --from=build /build/web/dist /srv/web
COPY infra/proxy/Caddyfile /etc/caddy/Caddyfile
ENV XDG_DATA_HOME=/data XDG_CONFIG_HOME=/config
USER 10001
EXPOSE 8080 8443
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -q --spider http://127.0.0.1:8081/healthz || exit 1
