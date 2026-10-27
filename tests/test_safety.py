"""Origin checks and lazy iteration."""

from __future__ import annotations

import gc
import warnings

import httpx
import pytest
import respx

from pajabi import AsyncKajabi, Kajabi, KajabiError

BASE = "https://api.kajabi.com"
EVIL = "https://evil.example/steal"
SITE = {"id": "1", "type": "sites", "attributes": {}}


def _page(next_url: str | None) -> dict[str, object]:
    links: dict[str, object] = {}
    if next_url is not None:
        links["next"] = next_url
    return {"data": [SITE], "links": links}


def test_sync_iter_and_request_refuse_a_foreign_origin() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/v1/sites").mock(return_value=httpx.Response(200, json=_page(EVIL)))
        evil = router.get(EVIL).mock(return_value=httpx.Response(200, json={"data": []}))
        with Kajabi(access_token="SECRET", max_retries=0) as kajabi:
            with pytest.raises(KajabiError, match="evil.example"):
                list(kajabi.sites.iter())
            with pytest.raises(KajabiError, match="evil.example"):
                kajabi.request("GET", EVIL)
            page = kajabi.sites.list()
            with pytest.raises(KajabiError, match="evil.example"):
                page.next_page()
        assert evil.call_count == 0
        assert not any(call.request.url.host == "evil.example" for call in router.calls)


async def test_async_iter_and_request_refuse_a_foreign_origin() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/v1/sites").mock(return_value=httpx.Response(200, json=_page(EVIL)))
        evil = router.get(EVIL).mock(return_value=httpx.Response(200, json={"data": []}))
        async with AsyncKajabi(access_token="SECRET", max_retries=0) as kajabi:
            with pytest.raises(KajabiError, match="evil.example"):
                [item async for item in kajabi.sites.iter()]
            with pytest.raises(KajabiError, match="evil.example"):
                await kajabi.request("GET", EVIL)
        assert evil.call_count == 0
        assert not any(call.request.url.host == "evil.example" for call in router.calls)


def test_explicit_default_port_matches_the_client_origin() -> None:
    next_url = f"{BASE}:443/v1/sites?page[number]=2"
    with respx.mock(assert_all_called=False) as router:
        router.get(url__regex=r"https://api\.kajabi\.com(?::443)?/v1/sites.*").mock(
            side_effect=lambda request: httpx.Response(
                200,
                json=(
                    _page(None)
                    if request.url.params.get("page[number]") == "2"
                    else _page(next_url)
                ),
            )
        )
        with Kajabi(access_token="SECRET", max_retries=0) as kajabi:
            assert [item.id for item in kajabi.sites.iter()] == ["1", "1"]
        assert sum(1 for call in router.calls if call.request.url.host == "api.kajabi.com") == 2


def test_iter_sends_nothing_until_iteration_starts() -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{BASE}/v1/sites").mock(
            return_value=httpx.Response(200, json=_page(None))
        )
        with Kajabi(access_token="SECRET", max_retries=0) as kajabi:
            iterator = kajabi.sites.iter()
            assert route.call_count == 0
            assert next(iterator).id == "1"
            assert route.call_count == 1


async def test_async_iter_is_lazy_and_an_unused_call_is_not_a_warning() -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{BASE}/v1/sites").mock(
            return_value=httpx.Response(200, json=_page(None))
        )
        async with AsyncKajabi(access_token="SECRET", max_retries=0) as kajabi:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                unused = kajabi.sites.iter()
                assert route.call_count == 0
                del unused
                gc.collect()
            assert not any("never awaited" in str(warning.message) for warning in caught)
            iterator = kajabi.sites.iter()
            assert route.call_count == 0
            assert (await anext(iterator)).id == "1"
            assert route.call_count == 1


def test_request_returns_parsed_json_api_body() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/v1/ping").mock(return_value=httpx.Response(204))
        router.post(f"{BASE}/v1/ping").mock(
            return_value=httpx.Response(200, json={"data": {"id": "1"}})
        )
        with Kajabi(access_token="SECRET", max_retries=0) as kajabi:
            assert kajabi.request("GET", "/v1/ping") is None
            assert kajabi.request("POST", "/v1/ping", json={"data": {"type": "pings"}}) == {
                "data": {"id": "1"}
            }
        get, post = (call.request for call in router.calls)
        assert get.headers["accept"] == "application/vnd.api+json"
        assert get.headers["authorization"] == "Bearer SECRET"
        assert post.headers["content-type"] == "application/vnd.api+json"
        assert post.read() == b'{"data": {"type": "pings"}}'


def test_sync_redirect_refuses_a_foreign_origin() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/v1/sites").mock(
            return_value=httpx.Response(302, headers={"Location": EVIL})
        )
        evil = router.get(EVIL).mock(return_value=httpx.Response(200, json={"data": []}))
        with Kajabi(access_token="SECRET", max_retries=0) as kajabi:
            http = kajabi._http
            with pytest.raises(KajabiError, match="evil.example"):
                kajabi.sites.list()
        assert evil.call_count == 0
        assert not any(call.request.url.host == "evil.example" for call in router.calls)
        assert kajabi._guard_redirect not in http.event_hooks["response"]


async def test_async_redirect_refuses_a_foreign_origin() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/v1/sites").mock(
            return_value=httpx.Response(302, headers={"Location": EVIL})
        )
        evil = router.get(EVIL).mock(return_value=httpx.Response(200, json={"data": []}))
        async with AsyncKajabi(access_token="SECRET", max_retries=0) as kajabi:
            http = kajabi._http
            with pytest.raises(KajabiError, match="evil.example"):
                await kajabi.sites.list()
        assert evil.call_count == 0
        assert not any(call.request.url.host == "evil.example" for call in router.calls)
        assert kajabi._guard_redirect not in http.event_hooks["response"]


@pytest.mark.parametrize(
    "location",
    [
        pytest.param(f"{BASE}/v1/sites?page[number]=2", id="absolute"),
        pytest.param(f"{BASE}:443/v1/sites?page[number]=2", id="explicit-default-port"),
        pytest.param("/v1/sites?page[number]=2", id="relative"),
    ],
)
def test_redirect_to_the_same_origin_is_followed(location: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page[number]") == "2":
            return httpx.Response(200, json=_page(None))
        return httpx.Response(302, headers={"Location": location})

    with respx.mock(assert_all_called=False) as router:
        router.get(url__regex=r"https://api\.kajabi\.com(?::443)?/v1/sites.*").mock(
            side_effect=respond
        )
        with Kajabi(access_token="SECRET", max_retries=0) as kajabi:
            page = kajabi.sites.list()
        assert [site.id for site in page] == ["1"]
        assert len(router.calls) == 2
        assert router.calls[1].request.url.host == "api.kajabi.com"
        assert router.calls[1].request.url.params["page[number]"] == "2"


@pytest.mark.parametrize(
    "location",
    [
        pytest.param(f"{BASE}/v1/sites?page[number]=2", id="absolute"),
        pytest.param(f"{BASE}:443/v1/sites?page[number]=2", id="explicit-default-port"),
        pytest.param("/v1/sites?page[number]=2", id="relative"),
    ],
)
async def test_async_redirect_to_the_same_origin_is_followed(location: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page[number]") == "2":
            return httpx.Response(200, json=_page(None))
        return httpx.Response(302, headers={"Location": location})

    with respx.mock(assert_all_called=False) as router:
        router.get(url__regex=r"https://api\.kajabi\.com(?::443)?/v1/sites.*").mock(
            side_effect=respond
        )
        async with AsyncKajabi(access_token="SECRET", max_retries=0) as kajabi:
            page = await kajabi.sites.list()
        assert [site.id for site in page] == ["1"]
        assert len(router.calls) == 2
        assert router.calls[1].request.url.host == "api.kajabi.com"
        assert router.calls[1].request.url.params["page[number]"] == "2"


def test_close_removes_the_redirect_hook() -> None:
    with Kajabi(access_token="SECRET", max_retries=0) as kajabi:
        http = kajabi._http
        assert kajabi._guard_redirect in http.event_hooks["response"]
    assert http.is_closed
    assert kajabi._guard_redirect not in http.event_hooks["response"]

    external = httpx.Client()
    with Kajabi(access_token="SECRET", max_retries=0, http_client=external) as kajabi:
        assert kajabi._guard_redirect in external.event_hooks["response"]
    assert not external.is_closed
    assert kajabi._guard_redirect not in external.event_hooks["response"]
    external.close()


async def test_aclose_removes_the_redirect_hook() -> None:
    async with AsyncKajabi(access_token="SECRET", max_retries=0) as kajabi:
        http = kajabi._http
        assert kajabi._guard_redirect in http.event_hooks["response"]
    assert http.is_closed
    assert kajabi._guard_redirect not in http.event_hooks["response"]

    external = httpx.AsyncClient()
    async with AsyncKajabi(access_token="SECRET", max_retries=0, http_client=external) as kajabi:
        assert kajabi._guard_redirect in external.event_hooks["response"]
    assert not external.is_closed
    assert kajabi._guard_redirect not in external.event_hooks["response"]
    await external.aclose()
