from prometheus_client import REGISTRY


def _count(method: str, path: str, status: str) -> float:
    labels = {"method": method, "path": path, "status": status}
    return REGISTRY.get_sample_value("http_requests_total", labels) or 0.0


def test_requests_are_labelled_by_route_template(client):
    before = _count("GET", "/accounts/{account_id}", "404")
    client.get("/accounts/00000000-0000-0000-0000-000000000000")
    client.get("/accounts/11111111-1111-1111-1111-111111111111")
    assert _count("GET", "/accounts/{account_id}", "404") == before + 2


def test_unknown_url_is_counted_as_unmatched(client):
    before = _count("GET", "unmatched", "404")
    client.get("/wp-admin")
    assert _count("GET", "unmatched", "404") == before + 1


def test_metrics_endpoint_serves_prometheus_text(client):
    client.get("/healthz")  # make sure the histogram has at least one observation
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "http_request_duration_seconds_bucket" in resp.text
    assert "00000000-0000" not in resp.text  # no raw IDs in labels
