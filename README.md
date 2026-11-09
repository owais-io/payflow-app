# PayFlow App

Application code for **PayFlow**, a small fintech payments app: create accounts, transfer money, get notified.

> **Status:** Work in progress. Deployment, CI/CD and infrastructure live in [payflow-platform](https://github.com/owais-io/payflow-platform).

## Services

| Service | Language | Role | Local port |
|---|---|---|---|
| accounts-api | Python (FastAPI) | Accounts and balances | 8001 |
| payments-api | Python (FastAPI) | Transfers between accounts; publishes `payment.completed` | 8002 |
| notification-worker | Python | Consumes `payment.completed` from Redis and logs a notification | 9100 (metrics only) |
| frontend | HTML/JS on nginx | Web UI; calls the APIs via `/api/accounts` and `/api/payments` | 8080 |
| PostgreSQL | postgres:17 | Accounts and transactions | 5432 |
| Redis | redis:7 | Event stream between payments-api and the worker | 6379 |

Design, API contracts, data model and events: [docs/architecture.md](docs/architecture.md).

## Run it with Docker Compose (recommended)

One command builds the four images and starts all six containers in the right order.
Kubernetes comes later (payflow-platform).

**Prerequisites:** Docker with Compose v2 (`docker compose version`); host port 8081 free.

```bash
cp .env.example .env          # then edit .env: at least set POSTGRES_PASSWORD
docker compose up -d --build
docker compose ps             # all six (healthy) after ~15 s
```
Open http://localhost:8081 (or the `FRONTEND_PORT` you set in `.env`).

| Command | What it does |
|---|---|
| `docker compose logs -f notification-worker` | Follow the worker; a transfer logs `"notification sent"` |
| `python3 scripts/seed.py --gateway http://localhost:8081` | Demo data through the frontend, like the browser |
| `python3 scripts/smoke_test.py` | End-to-end check through the frontend: exit 0 = healthy, 1 = a check failed, 2 = unreachable |
| `docker compose down` | Stop and remove the containers; **data is kept** (volume `payflow-app_pgdata`) |
| `docker compose down -v` | Also delete the volume: **all accounts and payments are gone** |

**How it fits together** ([compose.yaml](compose.yaml)):
- **Start order uses healthchecks, not just container start.** postgres and redis → accounts-api
  → payments-api → frontend; each waits for `condition: service_healthy`. The APIs' checks use
  `/readyz` (database reachable), so nothing starts against a database it can't reach.
- **Config comes from `.env`** (gitignored), documented in [.env.example](.env.example). Required
  values use `${VAR:?}`, so a missing one stops compose with a clear message. `DATABASE_URL` is
  built from the same `POSTGRES_*` values the database uses. The `services/*/.env.example` files
  are separate: they are for the manual run below.
- **Only the frontend is published** to the host. PostgreSQL, Redis and the APIs are reachable
  only inside the compose network, by service name.
- **[frontend/dev/nginx.compose.conf](frontend/dev/nginx.compose.conf)** is mounted over the
  image's nginx config and routes `/api/...` to the APIs, standing in for the Kubernetes Ingress.
- **PostgreSQL keeps its data in a named volume.** Redis has none on purpose: it only carries
  events in flight, and losing unread events on a local restart is acceptable.

### Smoke test

[scripts/smoke_test.py](scripts/smoke_test.py) checks that a running stack works end to end,
through the gateway like the browser: it creates two accounts, transfers 250.00, checks both
balances and the history, and checks that an overdraft is refused with 409 and moves no money.
Standard library only, so no virtualenv is needed.

```bash
python3 scripts/smoke_test.py                                  # compose on localhost:8081
python3 scripts/smoke_test.py --base-url http://localhost:8082 # another port or host
SMOKE_BASE_URL=http://localhost:8081 python3 scripts/smoke_test.py --wait 120
```

| Exit code | Meaning |
|---|---|
| 0 | All checks passed |
| 1 | A check failed, or part of the stack stopped answering during the test |
| 2 | The stack could not be reached within `--wait` seconds (default 60); nothing was tested |

Each run creates two new `smoke-<timestamp>` accounts; they stay in the database.

## Run it locally without Docker Compose

Everything runs on your machine: the two data stores in Docker, the Python services with
uvicorn, the frontend in an nginx container. Useful when working on one service's code.

### Prerequisites
- Python 3.12+, Docker, `curl`, `jq`
- Ports 5432, 6379, 8001, 8002, 8080 and 9100 free (see [Troubleshooting](#troubleshooting))

### 1. PostgreSQL and Redis

First time:
```bash
docker run -d --name payflow-pg -p 5432:5432 \
  -e POSTGRES_USER=payflow -e POSTGRES_PASSWORD=payflow -e POSTGRES_DB=payflow \
  postgres:17
docker run -d --name payflow-redis -p 6379:6379 redis:7
```
After that:
```bash
docker start payflow-pg payflow-redis
```
These credentials are for local development only.

### 2. Python services (once per service)
Each service has its own virtualenv and `.env`:
```bash
cd services/<service>
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp --update=none .env.example .env
```

### 3. Start the services (one terminal each)
In every terminal, first load the service's environment:
```bash
cd services/<service> && source .venv/bin/activate && set -a && source .env && set +a
```
Then:

| Terminal | Service | Command |
|---|---|---|
| 1 | accounts-api | `uvicorn app.main:app --port 8001 --no-access-log` |
| 2 | payments-api | `uvicorn app.main:app --port 8002 --no-access-log` |
| 3 | notification-worker | `python -m app.main` |

Tables are created by Alembic migrations: accounts-migrate and payments-migrate run alembic upgrade head before the APIs start.
Check them:
```bash
curl -s localhost:8001/readyz; echo
curl -s localhost:8002/readyz; echo
```

### 4. Frontend (terminal 4)
```bash
cd frontend
docker run --rm --name payflow-frontend --network host \
  -v "$PWD":/usr/share/nginx/html:ro \
  -v "$PWD/dev/nginx.local.conf":/etc/nginx/conf.d/default.conf:ro \
  nginxinc/nginx-unprivileged:1.30.6-alpine
```
Open http://localhost:8080. `dev/nginx.local.conf` routes `/api/...` to the APIs the same way
the Kubernetes Ingress will.

**If port 8080 is already in use** (`bind() to 0.0.0.0:8080 failed (98: Address in use)`;
a Jenkins installed on the host uses 8080 by default), serve the page on another port.
Make a temporary copy of the config with a different `listen` port and mount that copy
instead, so the file in the repo stays unchanged:
```bash
cd frontend
PORT=8081   # any free port
sed "s/listen 8080;/listen $PORT;/" dev/nginx.local.conf > /tmp/payflow-nginx.conf
docker run --rm --name payflow-frontend --network host \
  -v "$PWD":/usr/share/nginx/html:ro \
  -v /tmp/payflow-nginx.conf:/etc/nginx/conf.d/default.conf:ro \
  nginxinc/nginx-unprivileged:1.30.6-alpine
```
Then open `http://localhost:$PORT` (and use that port with `--gateway` in step 5).
`sudo ss -ltnp 'sport = :8080'` shows what is using 8080.

### 5. Demo data
```bash
python3 scripts/seed.py                                  # straight to the APIs
python3 scripts/seed.py --gateway http://localhost:8080  # through nginx, like the browser
                                                         # (your port, if you changed it)
```
Creates five demo accounts and five transfers, then prints the final balances and IDs.
Paste an ID into the frontend's "Add an existing account" to see it on the page. No virtualenv
needed (standard library only).

### 6. One transfer end to end, from the command line
```bash
A=$(curl -s -X POST localhost:8001/accounts -H 'Content-Type: application/json' \
  -d '{"owner_name":"Ali","initial_balance":"1000.00"}' | jq -r .id)
B=$(curl -s -X POST localhost:8001/accounts -H 'Content-Type: application/json' \
  -d '{"owner_name":"Sara"}' | jq -r .id)
curl -s -X POST localhost:8002/payments -H 'Content-Type: application/json' \
  -d "{\"from_account_id\":\"$A\",\"to_account_id\":\"$B\",\"amount\":\"250.00\"}" | jq
```
Terminal 3 (the worker) logs `"notification sent"` with the same `payment_id`.

### Stop everything
`Ctrl+C` in each terminal, then:
```bash
docker stop payflow-pg payflow-redis
```

## Tests

Unit tests need no database, Redis or network; each service has a 70% coverage gate.
```bash
cd services/<service> && source .venv/bin/activate
pytest
ruff check . && ruff format --check .
```
## Container images

Each service and the frontend has its own `Dockerfile` next to its code. Every image runs as a
non-root user and pins its base image by tag and digest.

| Image | Build context | Base image | User (UID) | Port | Health check |
|---|---|---|---|---|---|
| accounts-api | `services/accounts-api` | `python:3.12.16-slim-trixie` | 10001 | 8001 | `GET /healthz` |
| payments-api | `services/payments-api` | `python:3.12.16-slim-trixie` | 10001 | 8002 | `GET /healthz` |
| notification-worker | `services/notification-worker` | `python:3.12.16-slim-trixie` | 10001 | 9100 (metrics) | `GET /metrics` |
| frontend | `frontend` | `nginxinc/nginx-unprivileged:1.30.6-alpine` | 101 | 8080 | `GET /healthz` |

- **Python images are multi-stage.** The builder stage installs the service and its
  dependencies into a virtualenv at `/opt/venv`. The runtime stage copies only that venv, which
  stays owned by root, so the app can run its code but not change it.
- **`.dockerignore` files are allowlists.** Everything is excluded, then only what the
  Dockerfile copies is let back in. If an image needs a new file, add a `!path` line.
- **The frontend image serves static files only.** `/api` routing is done by the Kubernetes
  Ingress, or locally by `frontend/dev/nginx.local.conf`.
- **Version metadata comes from build args:** `VERSION` and `REVISION` become the OCI labels
  `org.opencontainers.image.version` and `.revision`.

### Build

```bash
V=0.1.0; R=$(git rev-parse --short HEAD)
for s in accounts-api payments-api notification-worker; do
  docker build -t $s:dev --build-arg VERSION=$V --build-arg REVISION=$R services/$s
done
docker build -t frontend:dev --build-arg VERSION=$V --build-arg REVISION=$R frontend
```

### Run

PostgreSQL and Redis must be running ([step 1](#1-postgresql-and-redis)). One terminal each:

```bash
docker run --rm --name accounts-api --network host \
  -e DATABASE_URL=postgresql+psycopg://payflow:payflow@localhost:5432/payflow \
  accounts-api:dev

docker run --rm --name payments-api --network host \
  -e DATABASE_URL=postgresql+psycopg://payflow:payflow@localhost:5432/payflow \
  -e ACCOUNTS_API_URL=http://127.0.0.1:8001 \
  -e REDIS_URL=redis://localhost:6379/0 \
  payments-api:dev

docker run --rm --name notification-worker --network host \
  -e REDIS_URL=redis://localhost:6379/0 \
  notification-worker:dev
```

With `--network host`, the worker's consumer name (`HOSTNAME`) is your machine's host name,
so run only one worker this way. In Kubernetes each pod gets its own name.

The frontend image on its own (static page only, `/api` returns 404):

```bash
docker run --rm --name frontend -p 8080:8080 frontend:dev
```

The frontend with the APIs, using the dev config in place of the image's config:

```bash
docker run --rm --name frontend --network host --no-healthcheck \
  -v "$PWD/frontend/dev/nginx.local.conf":/etc/nginx/conf.d/default.conf:ro \
  frontend:dev
```

Open http://localhost:8080. `--no-healthcheck` is needed here because the dev config has no
`/healthz`. If 8080 is taken, use the `sed` copy from [step 4](#4-frontend-terminal-4).

### Check

```bash
docker ps                                                        # every container (healthy) after ~10 s
docker inspect --format '{{json .Config.Labels}}' accounts-api:dev | jq
```
### Image sizes

Measured 2026-11-08 with Docker 29.9.2 . **Content size** is compressed: what a
registry stores and a node downloads. **Disk usage** is unpacked, on the node.

**Where the size comes from (accounts-api, three ways to build it):**

| Variant | Base image | Stages | Content size | Disk usage |
|---|---|---|---|---|
| Naive | `python:3.12.16-trixie` (full) | 1 | 468 MB | 1.79 GB |
| Single-stage slim | `python:3.12.16-slim-trixie` | 1 | 74.0 MB | 316 MB |
| **Multi-stage slim (this repo)** | `python:3.12.16-slim-trixie` | 2 | **74.4 MB** | **320 MB** |

- **The slim base did almost all the work: 84% smaller to download** (468 → 74 MB). The full
  image carries compilers, headers and about 1 GB of Debian packages the services never use.
- **Multi-stage added about 3 MB here instead of saving it.** Every dependency installs from a
  pre-built wheel (including `psycopg[binary]`), so the builder stage has nothing big to leave
  behind. The extra size is the virtualenv's own copy of pip.
- **`PIP_NO_CACHE_DIR=1` alone saved about 27 MB:** the naive build's `pip install` layer is
  135 MB, against 108 MB with the cache disabled.
- **Multi-stage is kept because of what it keeps out of the runtime image**, not for size: no
  build files (`build/`, `*.egg-info`, source tree), and the app runs from a root-owned venv. It
  becomes a real size saving as soon as a dependency has to be compiled (for example `psycopg`
  from source, which needs `gcc` and `libpq-dev` in the builder only).

**All images (built from this repo's Dockerfiles):**

| Image | Content size | Disk usage |
|---|---|---|
| accounts-api | 74.4 MB | 320 MB |
| payments-api | 76.5 MB | 330 MB |
| notification-worker | 52.9 MB | 219 MB |
| frontend | 25.6 MB | 90.2 MB |
## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Address already in use` / `bind() ... failed (98)` | Something else is on that port (an old run, or e.g. a host Jenkins on 8080) | `sudo ss -ltnp 'sport = :<port>'` to find it; stop it, or use another port: `--port` for uvicorn, `METRICS_PORT` in the worker's `.env`, or for the frontend the `sed` copy in [step 4](#4-frontend-terminal-4) |
| `ModuleNotFoundError: No module named 'uvicorn'` | Wrong folder or virtualenv not active | `cd` into the service and `source .venv/bin/activate` |
| `POST /payments` returns 503 | accounts-api is not running, or `ACCOUNTS_API_URL` is wrong | Start accounts-api on 8001 |
| Payment works but no notification | Worker not running, or Redis down (payments-api logs `event publish failed`) | Start the worker; `docker start payflow-redis` |
| `/readyz` says `"database": "down"` | PostgreSQL container stopped | `docker start payflow-pg` |
| Worker fails at startup with a validation error | `REDIS_URL` or `HOSTNAME` not set | `set -a; source .env; set +a` in that terminal |
| `failed to bind host port 0.0.0.0:8080` from `docker run -p` | Something on the host already uses 8080 (e.g. Jenkins) | Publish another host port: `-p 8081:8080` (the container still listens on 8080) |
| A root-owned folder appears where a mounted file should be (`rm` says write-protected), or compose fails with `not a directory: Are you trying to mount a directory onto a file` | The mount's source path did not exist, so Docker created an empty directory there as root | `docker compose down`, `sudo rmdir <path>`, put the file at that path, then `up` again |
| Compose: `failed to bind host port 0.0.0.0:8081: address already in use` | Something on the host already uses that port | Set another `FRONTEND_PORT` in `.env` |
| Compose: `required variable POSTGRES_PASSWORD is missing a value` | No `.env`, or the variable is missing from it | `cp .env.example .env` and fill it in |
| Compose: APIs never become healthy, logs show `password authentication failed` | `POSTGRES_*` in `.env` changed after the volume was created; PostgreSQL only reads them on first start | Put the old values back, or `docker compose down -v` (**deletes the data**) and `up` again |

## License

MIT
