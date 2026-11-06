# frontend

One static page (HTML, JS, CSS; no framework, no build step) for PayFlow: create accounts,
make transfers, view history. Served by nginx (unprivileged) on port 8080.

| File | Purpose |
|---|---|
| `index.html` | Page layout and forms |
| `app.js` | API calls, rendering, form handling |
| `styles.css` | Styles |
| `dev/nginx.local.conf` | Local only: serves the page and routes `/api/...` to the APIs |

## API paths
The page only calls relative paths, so it works behind any host name with no CORS:

| Browser calls | Goes to |
|---|---|
| `/api/accounts...` | accounts-api `/accounts...` |
| `/api/payments...` | payments-api `/payments...` |

In Kubernetes the Ingress does this routing and strips `/api`. Locally,
`dev/nginx.local.conf` does the same.

## Run locally
accounts-api on 8001 and payments-api on 8002 must be running. From this folder:

```bash
docker run --rm --name payflow-frontend --network host \
  -v "$PWD":/usr/share/nginx/html:ro \
  -v "$PWD/dev/nginx.local.conf":/etc/nginx/conf.d/default.conf:ro \
  nginxinc/nginx-unprivileged:1.27-alpine
```

Open http://localhost:8080.

The accounts list is kept in the browser's localStorage (IDs and names only); balances
and history always come from the APIs.
