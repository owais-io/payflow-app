#!/usr/bin/env python3
"""Create demo accounts and a few transfers through the PayFlow APIs.

Uses only the Python standard library, so it runs without a virtualenv.

Examples:
  # APIs started with uvicorn on this machine (default)
  python3 scripts/seed.py

  # through the frontend's nginx, or later through the Ingress: /api/accounts, /api/payments
  python3 scripts/seed.py --gateway http://localhost:8081

  # accounts only, no transfers
  python3 scripts/seed.py --no-transfers

Each run creates new accounts (the API has no lookup by name), so running it twice
gives two sets. Exit code 0 on success, 1 on the first failed request.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 5

# (owner_name, initial_balance)
DEMO_ACCOUNTS = [
    ("Ayesha Siddiqui", "50000.00"),
    ("Bilal Ahmed", "25000.00"),
    ("Fatima Noor", "10000.00"),
    ("Hamza Raza", "5000.00"),
    ("Zainab Ali", "0.00"),
]

# (from index, to index, amount): every account ends up with some history.
DEMO_TRANSFERS = [
    (0, 1, "2500.00"),
    (1, 2, "1200.50"),
    (2, 3, "750.00"),
    (0, 4, "1000.00"),
    (3, 0, "300.00"),
]


class SeedError(Exception):
    pass


def request(method: str, url: str, body: dict | None = None) -> dict | list:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.load(exc).get("detail", "")
        except (ValueError, AttributeError):
            detail = ""
        raise SeedError(f"{method} {url} -> HTTP {exc.code} {detail}".rstrip()) from exc
    except urllib.error.URLError as exc:
        raise SeedError(f"cannot reach {url} ({exc.reason}). Is it running?") from exc


def endpoints(args: argparse.Namespace) -> tuple[str, str]:
    if args.gateway:
        base = args.gateway.rstrip("/")
        return f"{base}/api/accounts", f"{base}/api/payments"
    return (
        f"{args.accounts_url.rstrip('/')}/accounts",
        f"{args.payments_url.rstrip('/')}/payments",
    )


def seed(accounts_endpoint: str, payments_endpoint: str, transfers: bool) -> list[dict]:
    created = []
    for owner, balance in DEMO_ACCOUNTS:
        account = request(
            "POST",
            accounts_endpoint,
            {"owner_name": owner, "initial_balance": balance},
        )
        created.append(account)
        print(f"created  {account['owner_name']:<16} {account['id']}")

    if transfers:
        for src, dst, amount in DEMO_TRANSFERS:
            payment = request(
                "POST",
                payments_endpoint,
                {
                    "from_account_id": created[src]["id"],
                    "to_account_id": created[dst]["id"],
                    "amount": amount,
                },
            )
            print(
                f"sent     {amount:>9} {created[src]['owner_name']} -> "
                f"{created[dst]['owner_name']}  (payment {payment['id'][:8]})"
            )

    # Final balances, read back from accounts-api rather than calculated here.
    for account in created:
        balance = request("GET", f"{accounts_endpoint}/{account['id']}/balance")
        account["balance"] = balance["balance"]
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed PayFlow with demo data.")
    parser.add_argument(
        "--accounts-url",
        default=os.getenv("ACCOUNTS_URL", "http://127.0.0.1:8001"),
        help="accounts-api base URL (default: %(default)s, or $ACCOUNTS_URL)",
    )
    parser.add_argument(
        "--payments-url",
        default=os.getenv("PAYMENTS_URL", "http://127.0.0.1:8002"),
        help="payments-api base URL (default: %(default)s, or $PAYMENTS_URL)",
    )
    parser.add_argument(
        "--gateway",
        help="one URL that routes /api/accounts and /api/payments (nginx or Ingress); "
        "overrides --accounts-url and --payments-url",
    )
    parser.add_argument(
        "--no-transfers", action="store_true", help="create accounts only"
    )
    args = parser.parse_args()

    accounts_endpoint, payments_endpoint = endpoints(args)
    try:
        accounts = seed(accounts_endpoint, payments_endpoint, not args.no_transfers)
    except SeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print()
    print(f"{'Owner':<16} {'Balance (PKR)':>14}  Account ID")
    for account in accounts:
        print(f"{account['owner_name']:<16} {account['balance']:>14}  {account['id']}")
    print(
        "\nPaste an ID into the frontend's 'Add an existing account' to see it there."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
