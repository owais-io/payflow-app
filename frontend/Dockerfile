# syntax=docker/dockerfile:1
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.30.6-alpine@sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03

# ---- Stage 1: builder ----
FROM ${NGINX_IMAGE}

COPY index.html app.js styles.css /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf

ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/owais-io/payflow-app" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.revision="$REVISION" \
      org.opencontainers.image.title="frontend" \
      org.opencontainers.image.licenses="MIT"

USER 101:101

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"]
