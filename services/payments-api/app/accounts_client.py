from uuid import UUID

import httpx


class AccountsUnavailable(Exception):
    """accounts-api could not be reached or gave an unexpected answer."""


class AccountsClient:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def account_exists(self, account_id: UUID) -> bool:
        try:
            resp = self._http.get(f"/accounts/{account_id}")
        except httpx.HTTPError as exc:
            raise AccountsUnavailable(str(exc)) from exc
        if resp.status_code == 200:
            return True
        if resp.status_code == 404:
            return False
        raise AccountsUnavailable(f"accounts-api returned {resp.status_code}")
