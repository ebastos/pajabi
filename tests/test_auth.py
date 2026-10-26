"""OAuth client-credentials, refresh, 401 retry, static tokens, and revoke."""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from pajabi import (
    AsyncKajabi,
    AuthenticationError,
    Kajabi,
    KajabiError,
)
from tests.transport import ACCESS_TOKEN, token_document

BASE = "https://api.kajabi.com"
SITES = {"data": []}


def _form(request: httpx.Request) -> dict[str, str]:
    parsed = parse_qs(request.content.decode())
    return {key: values[0] for key, values in parsed.items()}


def _token_calls(router: respx.MockRouter) -> list[httpx.Request]:
    return [call.request for call in router.calls if call.request.url.path == "/v1/oauth/token"]


def _api_calls(router: respx.MockRouter) -> list[httpx.Request]:
    return [call.request for call in router.calls if call.request.url.path == "/v1/sites"]


def test_client_credentials_are_form_encoded_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pajabi._clock.now", lambda: 1_000_000.0)
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(
            side_effect=lambda request: (
                httpx.Response(200, json=token_document())
                if request.url.path == "/v1/oauth/token"
                else httpx.Response(200, json=SITES)
            )
        )
        with Kajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
            kajabi.sites.list()
            kajabi.sites.list()
            assert kajabi._auth.access_token == ACCESS_TOKEN
            assert kajabi._auth.expires_at == 1_000_000.0 + 3600 - 30
        tokens = _token_calls(router)
        assert len(tokens) == 1
        assert _form(tokens[0]) == {
            "grant_type": "client_credentials",
            "client_id": "id",
            "client_secret": "secret",
        }
        assert "application/x-www-form-urlencoded" in tokens[0].headers["content-type"]
        assert _api_calls(router)[0].headers["authorization"] == f"Bearer {ACCESS_TOKEN}"


def test_refresh_near_expiry_and_fallback_to_client_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": 1_000_000.0}
    monkeypatch.setattr("pajabi._clock.now", lambda: clock["now"])

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/v1/oauth/token":
            return httpx.Response(200, json=SITES)
        if _form(request)["grant_type"] == "refresh_token":
            return httpx.Response(
                400,
                json={"error": "invalid_grant", "error_description": "expired"},
            )
        return httpx.Response(200, json=token_document(access_token="access-2"))

    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=respond)
        with Kajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
            kajabi.sites.list()
            clock["now"] = (kajabi._auth.expires_at or 0) + 5
            kajabi.sites.list()
            assert kajabi._auth.access_token == "access-2"
        grants = [_form(request)["grant_type"] for request in _token_calls(router)]
        assert grants == ["client_credentials", "refresh_token", "client_credentials"]


def test_refresh_only_client_uses_the_refresh_grant() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(
            side_effect=lambda request: (
                httpx.Response(200, json=token_document())
                if request.url.path == "/v1/oauth/token"
                else httpx.Response(200, json=SITES)
            )
        )
        with Kajabi(refresh_token="ref-1", max_retries=0, timeout=1.0) as kajabi:
            kajabi.sites.list()
        assert _form(_token_calls(router)[0]) == {
            "grant_type": "refresh_token",
            "refresh_token": "ref-1",
        }


def test_unauthorized_response_reauthenticates_once() -> None:
    hits = {"api": 0}

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth/token":
            grant = _form(request)["grant_type"]
            access = "first" if grant == "client_credentials" else "second"
            return httpx.Response(200, json=token_document(access_token=access))
        hits["api"] += 1
        if hits["api"] == 1:
            return httpx.Response(
                401,
                json={"errors": [{"title": "Unauthorized", "detail": "expired"}]},
            )
        return httpx.Response(200, json=SITES)

    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=respond)
        with Kajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
            kajabi.sites.list()
            assert kajabi._auth.access_token == "second"
        assert hits["api"] == 2
        grants = [_form(request)["grant_type"] for request in _token_calls(router)]
        assert grants == ["client_credentials", "refresh_token"]
        assert _api_calls(router)[1].headers["authorization"] == "Bearer second"


def test_persistent_unauthorized_is_not_retried_forever() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(
            side_effect=lambda request: (
                httpx.Response(200, json=token_document())
                if request.url.path == "/v1/oauth/token"
                else httpx.Response(
                    401,
                    json={"errors": [{"title": "Unauthorized", "detail": "nope"}]},
                )
            )
        )
        with Kajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
            with pytest.raises(AuthenticationError) as caught:
                kajabi.sites.list()
        assert caught.value.status_code == 401
        assert "nope" in str(caught.value)
        assert len(_api_calls(router)) == 2
        assert len(_token_calls(router)) == 2


def test_static_access_token_is_sent_as_is_and_not_refreshed() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/v1/sites").mock(return_value=httpx.Response(200, json=SITES))
        with Kajabi(access_token="static", max_retries=0, timeout=1.0) as kajabi:
            kajabi.sites.list()
        assert _token_calls(router) == []
        assert _api_calls(router)[0].headers["authorization"] == "Bearer static"


def test_static_access_token_does_not_retry_a_401() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/v1/sites").mock(
            return_value=httpx.Response(
                401,
                json={"errors": [{"title": "Unauthorized", "detail": "bad token"}]},
            )
        )
        with Kajabi(access_token="static", max_retries=0, timeout=1.0) as kajabi:
            with pytest.raises(AuthenticationError):
                kajabi.sites.list()
        assert len(_api_calls(router)) == 1
        assert _token_calls(router) == []


def test_revoke_sends_the_bearer_token_and_forgets_it() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(
            side_effect=lambda request: (
                httpx.Response(200, json=token_document())
                if request.url.path == "/v1/oauth/token"
                else httpx.Response(
                    200, json={} if request.url.path == "/v1/oauth/revoke" else SITES
                )
            )
        )
        with Kajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
            kajabi.revoke_token()
            assert kajabi._auth.access_token is None
            assert not any(call.request.url.path == "/v1/oauth/revoke" for call in router.calls)
            kajabi.sites.list()
            kajabi.revoke_token()
            assert kajabi._auth.access_token is None
            kajabi.sites.list()
        revoke = [
            call.request for call in router.calls if call.request.url.path == "/v1/oauth/revoke"
        ]
        assert len(revoke) == 1
        assert _form(revoke[0]) == {"token": ACCESS_TOKEN}
        assert revoke[0].headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
        assert "application/x-www-form-urlencoded" in revoke[0].headers["content-type"]
        assert len(_token_calls(router)) == 2


def test_credentials_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAJABI_CLIENT_ID", "env-id")
    monkeypatch.setenv("KAJABI_CLIENT_SECRET", "env-secret")
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(
            side_effect=lambda request: (
                httpx.Response(200, json=token_document())
                if request.url.path == "/v1/oauth/token"
                else httpx.Response(200, json=SITES)
            )
        )
        with Kajabi(max_retries=0, timeout=1.0) as kajabi:
            kajabi.sites.list()
        assert _form(_token_calls(router)[0])["client_id"] == "env-id"
        assert _form(_token_calls(router)[0])["client_secret"] == "env-secret"


def test_constructor_credentials_override_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAJABI_CLIENT_ID", "env-id")
    monkeypatch.setenv("KAJABI_CLIENT_SECRET", "env-secret")
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(
            side_effect=lambda request: (
                httpx.Response(200, json=token_document())
                if request.url.path == "/v1/oauth/token"
                else httpx.Response(200, json=SITES)
            )
        )
        with Kajabi("explicit", "explicit-secret", max_retries=0, timeout=1.0) as kajabi:
            kajabi.sites.list()
        form = _form(_token_calls(router)[0])
        assert form["client_id"] == "explicit"
        assert form["client_secret"] == "explicit-secret"


def test_missing_credentials_raise() -> None:
    with Kajabi(max_retries=0, timeout=1.0) as kajabi:
        with pytest.raises(KajabiError, match="credentials"):
            kajabi.sites.list()


def test_version_does_not_authenticate() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/v1/version").mock(
            return_value=httpx.Response(
                200,
                json={
                    "meta": {"version": "1.0"},
                    "jsonapi": {"specficiation": "https://jsonapi.org"},
                },
            )
        )
        with Kajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
            version = kajabi.version()
        assert version.version == "1.0"
        assert version.jsonapi_specification == "https://jsonapi.org"
        assert router.calls.call_count == 1
        assert "authorization" not in router.calls[0].request.headers


def test_owned_client_closes_and_injected_client_stays_open() -> None:
    with Kajabi(access_token="static", timeout=1.0) as kajabi:
        http = kajabi._http
    assert http.is_closed
    external = httpx.Client()
    with Kajabi(access_token="static", http_client=external, timeout=1.0) as kajabi:
        pass
    assert not external.is_closed
    external.close()


def test_concurrent_requests_share_one_token_fetch() -> None:
    import threading

    barrier = threading.Barrier(6)
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(
            side_effect=lambda request: (
                httpx.Response(200, json=token_document())
                if request.url.path == "/v1/oauth/token"
                else httpx.Response(200, json=SITES)
            )
        )
        with Kajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:

            def work() -> None:
                barrier.wait()
                kajabi.sites.list()

            threads = [threading.Thread(target=work) for _ in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        assert len(_token_calls(router)) == 1
        assert len(_api_calls(router)) == 6


def test_oauth_error_body_is_an_authentication_error() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{BASE}/v1/oauth/token").mock(
            return_value=httpx.Response(
                401,
                json={"error": "invalid_client", "error_description": "bad secret"},
            )
        )
        with Kajabi("id", "bad", max_retries=0, timeout=1.0) as kajabi:
            with pytest.raises(AuthenticationError) as caught:
                kajabi.sites.list()
        assert "invalid_client" in str(caught.value)
        assert "bad secret" in str(caught.value)
        assert router.calls.call_count == 1


async def test_async_token_cache_reauth_and_revoke() -> None:
    hits = {"api": 0}

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth/token":
            return httpx.Response(200, json=token_document())
        if request.url.path == "/v1/oauth/revoke":
            return httpx.Response(200, json={})
        hits["api"] += 1
        if hits["api"] == 1:
            return httpx.Response(
                401,
                json={"errors": [{"title": "Unauthorized", "detail": "expired"}]},
            )
        return httpx.Response(200, json=SITES)

    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=respond)
        async with AsyncKajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
            await kajabi.sites.list()
            await kajabi.sites.list()
            await kajabi.revoke_token()
            assert kajabi._auth.access_token is None
        grants = [_form(request)["grant_type"] for request in _token_calls(router)]
        assert grants[0] == "client_credentials"
        assert "refresh_token" in grants
        assert len(_api_calls(router)) == 3
        revoke = next(
            call.request for call in router.calls if call.request.url.path == "/v1/oauth/revoke"
        )
        assert _form(revoke)["token"] == ACCESS_TOKEN


async def test_async_static_token_and_close() -> None:
    external = httpx.AsyncClient()
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/v1/sites").mock(return_value=httpx.Response(200, json=SITES))
        async with AsyncKajabi(
            access_token="static", http_client=external, max_retries=0, timeout=1.0
        ) as kajabi:
            await kajabi.sites.list()
        assert not external.is_closed
        await external.aclose()
        assert _token_calls(router) == []
    async with AsyncKajabi(access_token="static", timeout=1.0) as kajabi:
        http = kajabi._http
    assert http.is_closed


async def test_concurrent_async_requests_share_one_token_fetch() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(
            side_effect=lambda request: (
                httpx.Response(200, json=token_document())
                if request.url.path == "/v1/oauth/token"
                else httpx.Response(200, json=SITES)
            )
        )
        async with AsyncKajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
            await asyncio.gather(*(kajabi.sites.list() for _ in range(6)))
        assert len(_token_calls(router)) == 1
        assert len(_api_calls(router)) == 6
