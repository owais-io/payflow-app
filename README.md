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

## Run it locally

Everything runs on your machine: the two data stores in Docker, the Python services with
uvicorn, the frontend in an nginx container. Kubernetes comes later (payflow-platform).

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

The APIs create their tables on startup (temporary until database migrations are added).
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
  nginxinc/nginx-unprivileged:1.27-alpine
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
  nginxinc/nginx-unprivileged:1.27-alpine
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

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Address already in use` / `bind() ... failed (98)` | Something else is on that port (an old run, or e.g. a host Jenkins on 8080) | `sudo ss -ltnp 'sport = :<port>'` to find it; stop it, or use another port: `--port` for uvicorn, `METRICS_PORT` in the worker's `.env`, or for the frontend the `sed` copy in [step 4](#4-frontend-terminal-4) |
| `ModuleNotFoundError: No module named 'uvicorn'` | Wrong folder or virtualenv not active | `cd` into the service and `source .venv/bin/activate` |
| `POST /payments` returns 503 | accounts-api is not running, or `ACCOUNTS_API_URL` is wrong | Start accounts-api on 8001 |
| Payment works but no notification | Worker not running, or Redis down (payments-api logs `event publish failed`) | Start the worker; `docker start payflow-redis` |
| `/readyz` says `"database": "down"` | PostgreSQL container stopped | `docker start payflow-pg` |
| Worker fails at startup with a validation error | `REDIS_URL` or `HOSTNAME` not set | `set -a; source .env; set +a` in that terminal |

## License

MIT
