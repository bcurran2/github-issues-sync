import time

import pytest
import requests

import fetch_issues


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None, links=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else []
        self.headers = headers or {}
        self.links = links or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def test_pull_requests_are_filtered_out(monkeypatch):
    batch = [
        {"id": 1, "updated_at": "2024-01-01T00:00:00Z"},
        {"id": 2, "updated_at": "2024-01-02T00:00:00Z", "pull_request": {"url": "x"}},
        {"id": 3, "updated_at": "2024-01-03T00:00:00Z"},
    ]

    def fake_get(url, headers=None, params=None):
        return FakeResponse(json_data=batch)

    monkeypatch.setattr(fetch_issues, "get_with_retry", fake_get)
    issues = fetch_issues.fetch_issues("owner/repo", "token")
    assert [i["id"] for i in issues] == [1, 3]


def test_pagination_follows_next_link(monkeypatch):
    pages = [
        FakeResponse(
            json_data=[{"id": 1, "updated_at": "2024-01-01T00:00:00Z"}],
            links={"next": {"url": "https://example.test/page2"}},
        ),
        FakeResponse(json_data=[{"id": 2, "updated_at": "2024-01-02T00:00:00Z"}]),
    ]
    urls_requested = []

    def fake_get(url, headers=None, params=None):
        urls_requested.append(url)
        return pages[len(urls_requested) - 1]

    monkeypatch.setattr(fetch_issues, "get_with_retry", fake_get)
    issues = fetch_issues.fetch_issues("owner/repo", "token")
    assert [i["id"] for i in issues] == [1, 2]
    assert urls_requested[1] == "https://example.test/page2"


def test_retries_on_503_then_succeeds(monkeypatch):
    responses = [FakeResponse(503), FakeResponse(503), FakeResponse(200, json_data=[{"id": 1}])]
    calls = []
    sleeps = []

    def fake_requests_get(url, headers=None, params=None, timeout=None):
        calls.append(url)
        return responses[len(calls) - 1]

    monkeypatch.setattr(fetch_issues.requests, "get", fake_requests_get)
    monkeypatch.setattr(fetch_issues.time, "sleep", sleeps.append)

    resp = fetch_issues.get_with_retry("https://example.test", headers={})
    assert resp.status_code == 200
    assert len(calls) == 3
    assert sleeps == [2, 4]


def test_gives_up_after_max_attempts(monkeypatch):
    calls = []
    sleeps = []

    def fake_requests_get(url, headers=None, params=None, timeout=None):
        calls.append(url)
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(fetch_issues.requests, "get", fake_requests_get)
    monkeypatch.setattr(fetch_issues.time, "sleep", sleeps.append)

    with pytest.raises(requests.ConnectionError):
        fetch_issues.get_with_retry("https://example.test", headers={}, max_attempts=3)
    assert len(calls) == 3
    assert sleeps == [2, 4]


def test_sleeps_until_reset_when_rate_limited(monkeypatch):
    sleeps = []
    monkeypatch.setattr(fetch_issues.time, "sleep", sleeps.append)
    reset = int(time.time()) + 100
    resp = FakeResponse(headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)})

    fetch_issues.wait_if_rate_limited(resp)
    assert len(sleeps) == 1
    assert 100 <= sleeps[0] <= 102


def test_does_not_sleep_when_requests_remain(monkeypatch):
    sleeps = []
    monkeypatch.setattr(fetch_issues.time, "sleep", sleeps.append)
    resp = FakeResponse(headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Reset": "0"})

    fetch_issues.wait_if_rate_limited(resp)
    assert sleeps == []