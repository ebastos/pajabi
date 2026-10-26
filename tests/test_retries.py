"""429 is always retried. 5xx and transport errors are retried only when idempotent."""

from __future__ import annotations

from email.utils import formatdate

import httpx
import pytest
import respx

from pajabi import (
    APIConnectionError,
    APITimeoutError,
    AsyncKajabi,
    InternalServerError,
    Kajabi,
    RateLimitError,
)

SITES = {"data": []}
URL = "https://api.kajabi.com/v1/sites"
CONTACTS = "https://api.kajabi.com/v1/contacts"


def test_retry_after_seconds_are_honoured(no_sleep: list[float]) -> None:
    hits = {"n": 0}

    def respond(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        if hits["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={"errors": []})
        return httpx.Response(200, json=SITES)

    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(side_effect=respond)
        with Kajabi(access_token="static", max_retries=2, timeout=1.0) as kajabi:
            page = kajabi.sites.list()
    assert page.data == []
    assert no_sleep == [2.0]
    assert hits["n"] == 2


def test_retry_after_http_date(no_sleep: list[float], monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = 1_000_000_000.0
    monkeypatch.setattr("pajabi._clock.now", lambda: fixed)
    hits = {"n": 0}

    def respond(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        if hits["n"] == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": formatdate(fixed + 5, usegmt=True)},
                json={"errors": []},
            )
        return httpx.Response(200, json=SITES)

    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(side_effect=respond)
        with Kajabi(access_token="static", max_retries=2, timeout=1.0) as kajabi:
            kajabi.sites.list()
    assert no_sleep == [pytest.approx(5.0)]
    assert hits["n"] == 2


def test_retry_after_is_capped_at_one_minute(no_sleep: list[float]) -> None:
    hits = {"n": 0}

    def respond(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        if hits["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "3600"}, json={"errors": []})
        return httpx.Response(200, json=SITES)

    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(side_effect=respond)
        with Kajabi(access_token="static", max_retries=2, timeout=1.0) as kajabi:
            kajabi.sites.list()
    assert no_sleep == [60.0]
    assert hits["n"] == 2


def test_retry_after_http_date_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    from pajabi._retry import retry_after_seconds

    fixed = 1_000_000_000.0
    monkeypatch.setattr("pajabi._clock.now", lambda: fixed)
    response = httpx.Response(
        429,
        headers={"Retry-After": formatdate(fixed + 3600, usegmt=True)},
    )
    assert retry_after_seconds(response, now=fixed) == 60.0


def test_rate_limit_stops_at_max_retries(
    no_sleep: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pajabi._retry.random.random", lambda: 1.0)
    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(return_value=httpx.Response(429, json={"errors": [{"title": "Slow"}]}))
        with Kajabi(access_token="static", max_retries=2, timeout=1.0) as kajabi:
            with pytest.raises(RateLimitError):
                kajabi.sites.list()
        assert router.calls.call_count == 3
        # attempt 0 ceiling 0.5, attempt 1 ceiling 1.0, full jitter with random() == 1.
        assert no_sleep == [0.5, 1.0]


def test_get_server_error_retries_and_post_does_not(no_sleep: list[float]) -> None:
    get_hits = {"n": 0}

    def respond(request: httpx.Request) -> httpx.Response:
        get_hits["n"] += 1
        if get_hits["n"] == 1:
            return httpx.Response(500, json={"errors": [{"title": "Boom"}]})
        return httpx.Response(200, json=SITES)

    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(side_effect=respond)
        router.post(CONTACTS).mock(
            return_value=httpx.Response(500, json={"errors": [{"title": "Boom"}]})
        )
        with Kajabi(access_token="static", max_retries=2, timeout=1.0) as kajabi:
            kajabi.sites.list()
            with pytest.raises(InternalServerError):
                kajabi.contacts.create(site_id="1", name="Jane", email="jane@example.com")
        assert get_hits["n"] == 2
        posts = [call for call in router.calls if call.request.method == "POST"]
        assert len(posts) == 1
        assert len(no_sleep) == 1


def test_post_rate_limit_is_retried(no_sleep: list[float]) -> None:
    hits = {"n": 0}

    def respond(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        if hits["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={"errors": []})
        return httpx.Response(
            200,
            json={"data": {"id": "1", "type": "contacts", "attributes": {"name": "Jane"}}},
        )

    with respx.mock(assert_all_called=False) as router:
        router.post(CONTACTS).mock(side_effect=respond)
        with Kajabi(access_token="static", max_retries=2, timeout=1.0) as kajabi:
            contact = kajabi.contacts.create(site_id="1", name="Jane", email="jane@example.com")
    assert contact.id == "1"
    assert hits["n"] == 2
    assert no_sleep == [1.0]


def test_get_connection_and_timeout_retry_post_connection_does_not(no_sleep: list[float]) -> None:
    state = {"gets": 0}

    def on_get(request: httpx.Request) -> httpx.Response:
        state["gets"] += 1
        if state["gets"] == 1:
            raise httpx.ConnectError("down")
        if state["gets"] == 2:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200, json=SITES)

    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(side_effect=on_get)
        router.post(CONTACTS).mock(side_effect=httpx.ConnectError("down"))
        with Kajabi(access_token="static", max_retries=2, timeout=1.0) as kajabi:
            kajabi.sites.list()
            with pytest.raises(APIConnectionError):
                kajabi.contacts.create(site_id="1", email="jane@example.com")
        assert state["gets"] == 3
        assert len([call for call in router.calls if call.request.method == "POST"]) == 1
        assert len(no_sleep) == 2


def test_get_timeout_without_recovery_raises(no_sleep: list[float]) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
        with Kajabi(access_token="static", max_retries=1, timeout=1.0) as kajabi:
            with pytest.raises(APITimeoutError):
                kajabi.sites.list()
        assert router.calls.call_count == 2
        assert len(no_sleep) == 1


async def test_async_get_retries_server_error(no_sleep: list[float]) -> None:
    hits = {"n": 0}

    def respond(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        if hits["n"] == 1:
            return httpx.Response(500, json={"errors": [{"title": "Boom"}]})
        return httpx.Response(200, json=SITES)

    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(side_effect=respond)
        async with AsyncKajabi(access_token="static", max_retries=2, timeout=1.0) as kajabi:
            page = await kajabi.sites.list()
    assert [item.id for item in page] == []
    assert hits["n"] == 2
    assert len(no_sleep) == 1
