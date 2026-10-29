# PayFlow App

Application code for **PayFlow**, a small fintech payments app: create accounts, transfer money, get notified.

> **Status:** Work in progress. Deployment, CI/CD and infrastructure live in [payflow-platform](https://github.com/owais-io/payflow-platform).

## Services

| Service | Language | Role |
|---|---|---|
| accounts-api | Python (FastAPI) | Accounts and balances |
| payments-api | Python (FastAPI) | Transfers between accounts |
| notification-worker | Python | Sends payment notifications from a Redis queue |
| frontend | HTML/JS on nginx | Web UI |

## License

MIT
