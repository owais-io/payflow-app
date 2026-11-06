from uuid import uuid4

import httpx
import pytest

from app.accounts_client import AccountsClient, AccountsUnavailable


def _client(handler) -> AccountsClient:
    http = httpx.Client(base_url="http://accounts-api", transport=httpx.MockTransport(handler))
    return AccountsClient(http)


def test_200_means_exists():
    assert _client(lambda req: httpx.Response(200, json={})).account_exists(uuid4()) is True


def test_404_means_missing():
    assert _client(lambda req: httpx.Response(404)).account_exists(uuid4()) is False


def test_calls_the_contract_path():
    seen = []
    account_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={})

    _client(handler).account_exists(account_id)
    assert seen == [f"/accounts/{account_id}"]


def test_5xx_is_unavailable_not_missing():
    with pytest.raises(AccountsUnavailable):
        _client(lambda req: httpx.Response(500)).account_exists(uuid4())


def test_network_error_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(AccountsUnavailable):
        _client(handler).account_exists(uuid4())


def test_timeout_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(AccountsUnavailable):
        _client(handler).account_exists(uuid4())
