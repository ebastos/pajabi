"""Every resource method hits the method, path, and body the spec describes."""

from __future__ import annotations

import inspect
import json
from collections.abc import Iterator
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from pajabi import AsyncKajabi, Kajabi
from tests.catalog import CASES, Case
from tests.transport import dispatch

PATH_TOKENS = ("{id}", "{contact_id}", "{customer_id}", "{offer_id}")


def _concrete(path: str) -> str:
    concrete = path
    for token in PATH_TOKENS:
        concrete = concrete.replace(token, "1")
    return concrete


def _prime(client: Kajabi | AsyncKajabi, case: Case) -> None:
    """Revoke uses the cached token and does not fetch one in order to drop it."""
    if case.path != "/v1/oauth/revoke":
        return
    client._auth.access_token = "access-1"
    client._auth.token_type = "Bearer"


def _invoke(client: Kajabi | AsyncKajabi, case: Case) -> object:
    target: object = client
    for part in case.call.split("."):
        target = getattr(target, part)
    if not callable(target):
        raise AssertionError(f"{case.call} is not callable")
    return target(*case.args, **case.kwargs)


def _watched(router: respx.MockRouter, case: Case) -> httpx.Request:
    path = "/v1/oauth/token" if case.watch == "token" else _concrete(case.path)
    found = [
        call.request
        for call in router.calls
        if call.request.method == case.method and call.request.url.path == path
    ]
    assert found, f"{case.name} did not send {case.method} {path}"
    return found[-1]


def _assert_request(request: httpx.Request, case: Case) -> None:
    if case.auth:
        assert request.headers["authorization"].startswith("Bearer ")
        assert request.headers["user-agent"].startswith("pajabi/")
    else:
        assert "authorization" not in request.headers
    if case.json_body is not None:
        assert json.loads(request.content) == case.json_body
        assert request.headers["content-type"] == "application/vnd.api+json"
    if case.empty_body:
        assert request.content == b""
    if case.query:
        for key, value in case.query.items():
            assert request.url.params.get(key) == value
    if case.form is not None:
        parsed = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        assert parsed == case.form
        assert "application/x-www-form-urlencoded" in request.headers["content-type"]
    if case.path == "/v1/version":
        assert request.url.path == "/v1/version"


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        mock.route().mock(side_effect=dispatch)
        yield mock


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_sync_method(case: Case, router: respx.MockRouter) -> None:
    with Kajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
        _prime(kajabi, case)
        result = _invoke(kajabi, case)
        if inspect.isgenerator(result):
            list(result)
    request = _watched(router, case)
    _assert_request(request, case)
    if case.path == "/v1/version":
        assert not any(call.request.url.path == "/v1/oauth/token" for call in router.calls)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
async def test_async_method(case: Case, router: respx.MockRouter) -> None:
    async with AsyncKajabi("id", "secret", max_retries=0, timeout=1.0) as kajabi:
        _prime(kajabi, case)
        result = _invoke(kajabi, case)
        if inspect.isasyncgen(result):
            async for _item in result:
                pass
        elif inspect.isawaitable(result):
            await result
    request = _watched(router, case)
    _assert_request(request, case)
    if case.path == "/v1/version":
        assert not any(call.request.url.path == "/v1/oauth/token" for call in router.calls)
