#!/usr/bin/env python3
"""End-to-end smoke test for a running PayFlow stack.

Goes through the gateway (nginx locally, the Ingress in Kubernetes), the same path a
browser takes: creates two accounts, makes a transfer, checks the balances and the
history, and checks that an overdraft is rejected without moving money.

Uses only the Python standard library, so it runs without a virtualenv.

Examples:
  python3 scripts/smoke_test.py                                   # docker compose on :8081
  python3 scripts/smoke_test.py --base-url http://payflow.local   # later: the Ingress
  SMOKE_BASE_URL=http://localhost:8081 python3 scripts/smoke_test.py --wait 120

Exit codes:
  0  all checks passed
  1  at least one check failed, including part of the stack not answering mid-test
  2  the stack could not be reached before testing started (nothing was tested)
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal

TIMEOUT_SECONDS = 5

EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_UNREACHABLE = 2


class HttpError(Exception):
    """The server answered, but with an HTTP error status."""

    def __init__(self, method: str, url: str, status: int, detail: str):
        super().__init__(f"{method} {url} -> HTTP {status} {detail}".rstrip())
        self.status = status


class Unreachable(Exception):
    """No HTTP answer at all: connection refused, DNS failure, timeout."""


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
        raise HttpError(method, url, exc.code, str(detail)) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise Unreachable(f"cannot reach {url} ({reason})") from exc


class Checks:
    """Records results instead of using assert (asserts vanish under python -O)."""

    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<26} {detail}".rstrip(), flush=True)
        if ok:
            self.passed += 1
        else:
            self.failed += 1
        return ok


def wait_until_ready(accounts: str, wait_seconds: int) -> None:
    """Retry until the accounts API answers through the gateway, or time runs out.

    Right after a deploy the stack may still be starting; that is not a test failure.
    Any HTTP answer from the API (even 404 for a made-up ID) means it is up.
    A 502/503/504 means the gateway is up but the API behind it is not yet.
    """
    probe = f"{accounts}/00000000-0000-0000-0000-000000000000"
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            request("GET", probe)
            return
        except HttpError as exc:
            if exc.status not in (502, 503, 504):
                return
            last = str(exc)
        except Unreachable as exc:
            last = str(exc)
        if time.monotonic() >= deadline:
            raise Unreachable(f"not ready after {wait_seconds}s: {last}")
        time.sleep(2)


def balance_of(accounts: str, account_id: str) -> Decimal:
    return Decimal(request("GET", f"{accounts}/{account_id}/balance")["balance"])


def run(base_url: str, wait_seconds: int) -> int:
    accounts = f"{base_url}/api/accounts"
    payments = f"{base_url}/api/payments"
    checks = Checks()
    print(f"PayFlow smoke test against {base_url}", flush=True)

    try:
        wait_until_ready(accounts, wait_seconds)

        # 1. Two fresh accounts; unique names because the database keeps old runs.
        run_id = time.strftime("%Y%m%d-%H%M%S")
        a = request(
            "POST",
            accounts,
            {"owner_name": f"smoke-{run_id}-A", "initial_balance": "1000.00"},
        )
        b = request(
            "POST",
            accounts,
            {"owner_name": f"smoke-{run_id}-B", "initial_balance": "0.00"},
        )
    except (HttpError, Unreachable, KeyError) as exc:
        print(f"ERROR setup: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE

    checks.check(
        "create accounts",
        Decimal(a["balance"]) == Decimal("1000.00")
        and Decimal(b["balance"]) == Decimal("0.00"),
        f"A={a['id'][:8]} B={b['id'][:8]}",
    )

    try:
        # 2. A normal transfer.
        payment = request(
            "POST",
            payments,
            {"from_account_id": a["id"], "to_account_id": b["id"], "amount": "250.00"},
        )
        checks.check(
            "transfer 250.00",
            payment.get("status") == "completed"
            and Decimal(payment["amount"]) == Decimal("250.00"),
            f"payment {payment['id'][:8]} {payment.get('status')}",
        )

        # 3. Balances, read back from accounts-api rather than trusted from the payment.
        bal_a, bal_b = balance_of(accounts, a["id"]), balance_of(accounts, b["id"])
        checks.check(
            "balances after transfer",
            bal_a == Decimal("750.00") and bal_b == Decimal("250.00"),
            f"A={bal_a} B={bal_b} (want 750.00 / 250.00)",
        )

        # 4. The payment appears in A's history.
        history = request("GET", f"{payments}?account_id={a['id']}")
        checks.check(
            "payment in history",
            any(p.get("id") == payment["id"] for p in history),
            f"{len(history)} payment(s) for A",
        )

        # 5. Overdraft: must be refused with 409 and must not move any money.
        try:
            request(
                "POST",
                payments,
                {
                    "from_account_id": a["id"],
                    "to_account_id": b["id"],
                    "amount": "10000.00",
                },
            )
            status = 201
        except HttpError as exc:
            status = exc.status
        after_a, after_b = balance_of(accounts, a["id"]), balance_of(accounts, b["id"])
        checks.check(
            "overdraft rejected",
            status == 409 and after_a == bal_a and after_b == bal_b,
            f"HTTP {status} (want 409), A={after_a} B={after_b}",
        )
    except (HttpError, KeyError, TypeError) as exc:
        # An unexpected error mid-test: the stack answered, but wrongly.
        checks.check("unexpected error", False, str(exc))
    except Unreachable as exc:
        # Setup worked, so the stack is there: a part of it not answering is a
        # failure (exit 1), not "nothing deployed" (exit 2).
        checks.check("stack answered", False, str(exc))

    total = checks.passed + checks.failed
    print(f"{checks.passed}/{total} checks passed")
    return EXIT_OK if checks.failed == 0 else EXIT_CHECK_FAILED


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-end smoke test for PayFlow.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("SMOKE_BASE_URL", "http://localhost:8081"),
        help="gateway URL that routes /api/accounts and /api/payments "
        "(default: %(default)s, or $SMOKE_BASE_URL)",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=60,
        help="seconds to keep retrying until the stack answers (default: %(default)s)",
    )
    args = parser.parse_args()
    return run(args.base_url.rstrip("/"), args.wait)


if __name__ == "__main__":
    sys.exit(main())
