"""``iter`` follows ``links.next`` and stays quiet when a page has no next link."""

from __future__ import annotations

import httpx
import respx

from pajabi import AsyncKajabi, Kajabi

BASE = "https://api.kajabi.com"
TOKEN = {
    "access_token": "access-1",
    "refresh_token": "refresh-1",
    "expires_in": 3600,
    "token_type": "Bearer",
}


def _site(resource_id: str, title: str) -> dict[str, object]:
    return {"id": resource_id, "type": "sites", "attributes": {"title": title}}


def test_iter_walks_pages_and_page_iteration_stays_put() -> None:
    page_two = f"{BASE}/v1/sites?page[number]=2"
    first = {
        "data": [_site("1", "One")],
        "links": {"self": f"{BASE}/v1/sites", "next": page_two},
        "meta": {"total_count": 2, "total_pages": 2, "current_page": 1},
    }
    second = {
        "data": [_site("2", "Two")],
        "links": {"self": page_two},
        "meta": {"total_count": 2, "total_pages": 2, "current_page": 2},
    }

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth/token":
            return httpx.Response(200, json=TOKEN)
        if request.url.params.get("page[number]") == "2":
            return httpx.Response(200, json=second)
        return httpx.Response(200, json=first)

    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=respond)
        with Kajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
            page = kajabi.sites.list()
            assert [item.id for item in page] == ["1"]
            assert page.has_next_page()
            assert page.meta.total_count == 2
            assert page.meta.total_pages == 2
            assert page.meta.current_page == 1
            assert [item.id for item in kajabi.sites.iter()] == ["1", "2"]
            nxt = page.next_page()
            assert nxt is not None
            assert [item.id for item in nxt] == ["2"]
            assert nxt.next_page() is None
        site_gets = [
            call
            for call in router.calls
            if call.request.method == "GET" and call.request.url.path == "/v1/sites"
        ]
        # list, iter page 1, iter page 2, next_page.
        assert len(site_gets) == 4


def test_missing_meta_and_next_does_not_crash() -> None:
    payload = {"data": [_site("1", "Only")], "links": {"self": f"{BASE}/v1/sites"}}
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{BASE}/v1/oauth/token").mock(return_value=httpx.Response(200, json=TOKEN))
        router.get(f"{BASE}/v1/sites").mock(return_value=httpx.Response(200, json=payload))
        with Kajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
            page = kajabi.sites.list()
            assert page.meta.total_count is None
            assert page.meta.total_pages is None
            assert page.has_next_page() is False
            assert [item.id for item in kajabi.sites.iter()] == ["1"]
            assert page.next_page() is None
        assert len([call for call in router.calls if call.request.url.path == "/v1/sites"]) == 2


def test_repeated_next_link_stops() -> None:
    again = f"{BASE}/v1/sites?page[number]=2"

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth/token":
            return httpx.Response(200, json=TOKEN)
        if request.url.params.get("page[number]") == "2":
            return httpx.Response(
                200,
                json={"data": [_site("2", "Two")], "links": {"next": again}},
            )
        return httpx.Response(
            200,
            json={"data": [_site("1", "One")], "links": {"next": again}},
        )

    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=respond)
        with Kajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
            assert [item.id for item in kajabi.sites.iter()] == ["1", "2"]
        pages = [call for call in router.calls if call.request.url.path == "/v1/sites"]
        assert len(pages) == 2


def test_payout_meta_is_normalized() -> None:
    payload = {
        "data": [
            {
                "id": "8",
                "type": "kajabi_payments_payouts",
                "attributes": {
                    "amount": 12.5,
                    "currency": "USD",
                    "initiated_date": "2024-01-02T03:04:05Z",
                },
            }
        ],
        "links": {"self": f"{BASE}/v1/kajabi_payments_payouts"},
        "meta": {"total": 4, "pagination": {"current": 1, "last": 2}},
    }
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{BASE}/v1/oauth/token").mock(return_value=httpx.Response(200, json=TOKEN))
        router.get(f"{BASE}/v1/kajabi_payments_payouts").mock(
            return_value=httpx.Response(200, json=payload)
        )
        with Kajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
            page = kajabi.payouts.list(site_id="3")
    assert page.meta.total_count == 4
    assert page.meta.current_page == 1
    assert page.meta.total_pages == 2
    assert page.data[0].amount == 12.5
    assert page.data[0].initiated_date is not None
    assert page.data[0].initiated_date.year == 2024


async def test_async_iter_walks_pages() -> None:
    page_two = f"{BASE}/v1/orders?page[number]=2"

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth/token":
            return httpx.Response(200, json=TOKEN)
        if request.url.params.get("page[number]") == "2":
            return httpx.Response(
                200,
                json={"data": [{"id": "2", "type": "orders", "attributes": {}}], "links": {}},
            )
        return httpx.Response(
            200,
            json={
                "data": [{"id": "1", "type": "orders", "attributes": {}}],
                "links": {"next": page_two},
            },
        )

    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=respond)
        async with AsyncKajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
            found = [item.id async for item in kajabi.orders.iter()]
        assert found == ["1", "2"]
        assert len([call for call in router.calls if call.request.url.path == "/v1/orders"]) == 2


def test_link_objects_with_href_are_followed() -> None:
    page_two = f"{BASE}/v1/sites?page[number]=2"
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{BASE}/v1/oauth/token").mock(return_value=httpx.Response(200, json=TOKEN))
        router.get(url__regex=r"https://api\.kajabi\.com/v1/sites.*").mock(
            side_effect=lambda request: httpx.Response(
                200,
                json=(
                    {"data": [_site("2", "Two")], "links": {"self": {"href": page_two}}}
                    if request.url.params.get("page[number]") == "2"
                    else {
                        "data": [_site("1", "One")],
                        "links": {"next": {"href": page_two}, "self": {"href": f"{BASE}/v1/sites"}},
                    }
                ),
            )
        )
        with Kajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
            page = kajabi.sites.list()
            assert page.links.self_link == f"{BASE}/v1/sites"
            assert page.has_next_page()
            assert [item.id for item in kajabi.sites.iter()] == ["1", "2"]
