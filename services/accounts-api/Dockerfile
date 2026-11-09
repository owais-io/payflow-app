# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.12.16-slim-trixie@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54

# ---- Stage 1: builder ----
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /src
COPY pyproject.toml ./
COPY app/ ./app/
RUN pip install .

# ---- Stage 2: runtime ----
FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --gid 10001 payflow \
    && useradd --uid 10001 --gid payflow --no-create-home --shell /usr/sbin/nologin payflow

COPY --from=builder /opt/venv /opt/venv
ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.source=https://github.com/owais-io/payflow-app \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.revision="$REVISION" \
      org.opencontainers.image.title=accounts-api \
      org.opencontainers.image.licenses=MIT

WORKDIR /app
COPY alembic.ini ./
COPY migrations/ ./migrations/
USER 10001:10001
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/healthz', timeout=2)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]
