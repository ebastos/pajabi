"""Query strings follow Kajabi's JSON:API conventions."""

from __future__ import annotations

import httpx
import pytest
import respx

from pajabi import Kajabi
from pajabi._query import encode_query


def test_encode_include_fields_sort_page_and_filters() -> None:
    params = encode_query(
        sort="-created_at",
        include=["tags", "customer.offers"],
        fields={"contacts": ["name", "email"], "customers": "email"},
        page=2,
        page_size=25,
        filters={
            "site_id": "1",
            "title_cont": "Intro",
            "subscribed": False,
            "archived": None,
            "exclude_product_types": ["Course", "Coaching"],
        },
    )
    assert params == [
        ("sort", "-created_at"),
        ("include", "tags,customer.offers"),
        ("fields[contacts]", "name,email"),
        ("fields[customers]", "email"),
        ("page[number]", "2"),
        ("page[size]", "25"),
        ("filter[site_id]", "1"),
        ("filter[title_cont]", "Intro"),
        ("filter[subscribed]", "false"),
        ("filter[exclude_product_types][]", "Course"),
        ("filter[exclude_product_types][]", "Coaching"),
    ]


def test_include_string_is_sent_unchanged() -> None:
    assert encode_query(include="tags,offers") == [("include", "tags,offers")]


def test_courses_list_encodes_the_query_on_the_request() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(
            side_effect=lambda request: (
                httpx.Response(200, json={"data": []})
                if request.url.path != "/v1/oauth/token"
                else httpx.Response(
                    200,
                    json={
                        "access_token": "access-1",
                        "refresh_token": "refresh-1",
                        "expires_in": 3600,
                        "token_type": "Bearer",
                    },
                )
            )
        )
        with Kajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
            kajabi.courses.list(
                site_id="1",
                title_cont="Intro",
                sort="title",
                include=["modules", "lessons", "lessons.media", "offers"],
                fields={"courses": ["title"]},
                page=3,
                page_size=10,
            )
        listing = next(
            call.request for call in router.calls if call.request.url.path == "/v1/courses"
        )
        assert listing.url.params.get("filter[site_id]") == "1"
        assert listing.url.params.get("filter[title_cont]") == "Intro"
        assert listing.url.params.get("sort") == "title"
        assert listing.url.params.get("include") == "modules,lessons,lessons.media,offers"
        assert listing.url.params.get("fields[courses]") == "title"
        assert listing.url.params.get("page[number]") == "3"
        assert listing.url.params.get("page[size]") == "10"


def test_repeated_filter_uses_the_bracket_suffix() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.post("https://api.kajabi.com/v1/oauth/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        )
        router.get("https://api.kajabi.com/v1/products").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        with Kajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
            kajabi.products.list(exclude_product_types=["Course", "Coaching"])
        listing = next(
            call.request for call in router.calls if call.request.url.path == "/v1/products"
        )
        assert listing.url.params.get_list("filter[exclude_product_types][]") == [
            "Course",
            "Coaching",
        ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, "true"), (1, "1"), (1.5, "1.5")],
)
def test_scalar_filter_values(value: object, expected: str) -> None:
    params = encode_query(filters={"n": value})  # type: ignore[arg-type]
    assert params == [("filter[n]", expected)]
