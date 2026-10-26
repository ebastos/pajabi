"""HTTP status codes become the matching exception, with JSON:API details attached."""

from __future__ import annotations

import httpx
import pytest
import respx

from pajabi import (
    APIError,
    AsyncKajabi,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    Kajabi,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)

BODY = {
    "errors": [
        {
            "status": "422",
            "title": "Invalid attribute",
            "detail": "is missing",
            "source": {"pointer": "/data/attributes/email"},
        }
    ]
}


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (400, BadRequestError),
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (422, UnprocessableEntityError),
        (429, RateLimitError),
        (500, InternalServerError),
        (503, InternalServerError),
        (418, APIError),
    ],
)
def test_status_maps_to_exception(status: int, error_type: type[APIError]) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get("https://api.kajabi.com/v1/sites").mock(
            return_value=httpx.Response(status, json=BODY)
        )
        with Kajabi(access_token="static", max_retries=0, timeout=1.0) as kajabi:
            with pytest.raises(error_type) as caught:
                kajabi.sites.list()
        error = caught.value
        assert type(error) is error_type
        assert error.status_code == status
        assert error.errors[0].title == "Invalid attribute"
        assert error.errors[0].detail == "is missing"
        assert error.errors[0].source is not None
        assert error.errors[0].source.pointer == "/data/attributes/email"
        assert str(error) == f"{status} Invalid attribute: is missing (/data/attributes/email)"
        assert router.calls.call_count == 1


async def test_async_not_found() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get("https://api.kajabi.com/v1/contacts/missing").mock(
            return_value=httpx.Response(404, json=BODY)
        )
        async with AsyncKajabi(access_token="static", max_retries=0, timeout=1.0) as kajabi:
            with pytest.raises(NotFoundError) as caught:
                await kajabi.contacts.get("missing")
    assert caught.value.status_code == 404


def test_unknown_webhook_sample_is_rejected_before_a_request() -> None:
    from pajabi import KajabiError

    with respx.mock(assert_all_called=False) as router:
        with Kajabi(access_token="static", max_retries=0, timeout=1.0) as kajabi:
            with pytest.raises(KajabiError, match="Unknown webhook sample"):
                kajabi.hooks.sample("not-an-event")
        assert router.calls.call_count == 0
