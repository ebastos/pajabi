"""Sync and async Kajabi clients.

Request building, retries, and response parsing live in helpers both clients
call. Each client only owns its httpx transport and the await (or lack of one).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from typing import Any, TypeVar
from urllib.parse import urlencode

import httpx

from pajabi import _clock
from pajabi._auth import KajabiAuth
from pajabi._parsing import parse_collection, parse_identifiers, parse_one, parse_version
from pajabi._retry import retry_delay
from pajabi._version import __version__
from pajabi.errors import APIConnectionError, APITimeoutError, KajabiError, error_from_response
from pajabi.models import (
    BlogPost,
    ContactTag,
    Course,
    CustomField,
    FormSubmission,
    LandingPage,
    Order,
    OrderItem,
    Podcast,
    Product,
    Resource,
    ResourceIdentifier,
    Site,
    Transaction,
    User,
    Version,
    WebsitePage,
)
from pajabi.pagination import AsyncPage, Page
from pajabi.resources import (
    AsyncContactNotes,
    AsyncContacts,
    AsyncCustomers,
    AsyncForms,
    AsyncHooks,
    AsyncOffers,
    AsyncPayouts,
    AsyncPurchases,
    AsyncReadOnly,
    ContactNotes,
    Contacts,
    Customers,
    Forms,
    Hooks,
    Offers,
    Payouts,
    Purchases,
    ReadOnly,
)

T = TypeVar("T", bound=Resource)

JSON_API = "application/vnd.api+json"
_USER_AGENT = f"pajabi/{__version__}"
Params = list[tuple[str, str]] | None
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _credential(value: str | None, env_name: str) -> str | None:
    if value is not None:
        return value
    found = os.environ.get(env_name)
    return found or None


def _port(url: httpx.URL) -> int | None:
    """Return the URL port, filling in 80 or 443 when the port is omitted.

    ``httpx.URL`` already drops an explicit default port, so ``:443`` and an
    omitted HTTPS port compare equal.
    """
    if url.port is not None:
        return url.port
    return _DEFAULT_PORTS.get(url.scheme)


def _absolute(base_url: str, path: str, params: Params = None) -> str:
    """Resolve ``path`` against ``base_url``.

    An absolute URL is allowed only when its scheme, host, and port match
    ``base_url``. Anything else raises :class:`KajabiError` before a request
    is sent. Redirect targets are checked here too.
    """
    candidate = httpx.URL(path)
    if candidate.is_absolute_url:
        base = httpx.URL(base_url)
        if (candidate.scheme, candidate.host, _port(candidate)) != (
            base.scheme,
            base.host,
            _port(base),
        ):
            raise KajabiError(
                f"Refusing to send a request to {candidate.scheme}://{candidate.host}, "
                f"which is outside {base_url}."
            )
        url = path
    else:
        suffix = path if path.startswith("/") else f"/{path}"
        url = f"{base_url}{suffix}"
    if not params:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


def _check_redirect(base_url: str, response: httpx.Response) -> None:
    """Raise when a redirect target is outside ``base_url``.

    httpx calls response hooks before it builds the next request, and closes
    the response if the hook raises. The redirected request is not sent.
    """
    if not response.has_redirect_location:
        return
    target = str(response.url.join(response.headers["location"]))
    _absolute(base_url, target)


def _detach_hook(client: httpx.Client | httpx.AsyncClient, hook: Callable[..., Any]) -> None:
    """Drop a response hook so a shared client does not keep it."""
    hooks = client.event_hooks["response"]
    if hook in hooks:
        hooks.remove(hook)


def _dump(body: Mapping[str, Any]) -> bytes:
    return json.dumps(body).encode()


def read_json(response: httpx.Response) -> Any:
    """Parse a response body and close it. An empty body is ``None``."""
    try:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise KajabiError("Kajabi returned a response that is not JSON.") from exc
    finally:
        # ``send(stream=False)`` already reads the body. An async response's
        # stream rejects ``close()``; it was released by ``aread``.
        if not response.is_closed:
            response.close()


def _headers(
    content_type: str | None,
    extra: Mapping[str, str] | None,
) -> dict[str, str]:
    headers = {"Accept": JSON_API, "User-Agent": _USER_AGENT}
    if content_type:
        headers["Content-Type"] = content_type
    if extra:
        headers.update(dict(extra))
    return headers


def _failure_delay(
    *,
    method: str,
    attempt: int,
    max_retries: int,
    response: httpx.Response | None = None,
    transport_error: bool = False,
) -> float | None:
    return retry_delay(
        method=method,
        attempt=attempt,
        max_retries=max_retries,
        response=response,
        transport_error=transport_error,
        now=_clock.now(),
    )


def _retry_outcome(
    *,
    method: str,
    attempt: int,
    max_retries: int,
    response: httpx.Response | None = None,
    transport_error: httpx.TransportError | None = None,
) -> float | Exception | None:
    """Decide the next step of one attempt.

    ``None`` means the response succeeded. A float is how long to sleep before
    the next attempt. An exception is ready to raise, after the caller closes
    a response it still holds.
    """
    if transport_error is not None:
        delay = _failure_delay(
            method=method,
            attempt=attempt,
            max_retries=max_retries,
            transport_error=True,
        )
        if delay is None:
            error_type = (
                APITimeoutError
                if isinstance(transport_error, httpx.TimeoutException)
                else APIConnectionError
            )
            return error_type(str(transport_error))
        return delay
    if response is None or response.status_code < 400:
        return None
    delay = _failure_delay(
        method=method,
        attempt=attempt,
        max_retries=max_retries,
        response=response,
    )
    if delay is None:
        return error_from_response(response)
    return delay


def _outgoing(
    method: str,
    url: str,
    content: bytes | None,
    content_type: str | None,
    headers: Mapping[str, str] | None,
) -> httpx.Request:
    return httpx.Request(method, url, content=content, headers=_headers(content_type, headers))


def _revoke_form(token: str, token_type: str) -> tuple[bytes, dict[str, str]]:
    return (
        urlencode({"token": token}).encode(),
        {"Accept": "application/json", "Authorization": f"{token_type} {token}"},
    )


class Kajabi:
    """Synchronous client for the Kajabi Public API.

    Pass ``client_id`` and ``client_secret`` to fetch an OAuth token on the
    first request, or pass ``access_token`` to send a bearer token you already
    have. ``client_id`` and ``client_secret`` fall back to ``KAJABI_CLIENT_ID``
    and ``KAJABI_CLIENT_SECRET``.

    Use the client as a context manager so its HTTP connection closes::

        with Kajabi(client_id=..., client_secret=...) as kajabi:
            page = kajabi.contacts.list(site_id="123")

    :meth:`request` is the low-level JSON:API escape hatch. Resource namespaces
    cover the public API; nothing else on the client sends HTTP.
    """

    blog_posts: ReadOnly[BlogPost]
    contact_tags: ReadOnly[ContactTag]
    courses: ReadOnly[Course]
    custom_fields: ReadOnly[CustomField]
    form_submissions: ReadOnly[FormSubmission]
    landing_pages: ReadOnly[LandingPage]
    order_items: ReadOnly[OrderItem]
    orders: ReadOnly[Order]
    podcasts: ReadOnly[Podcast]
    products: ReadOnly[Product]
    sites: ReadOnly[Site]
    transactions: ReadOnly[Transaction]
    website_pages: ReadOnly[WebsitePage]
    contact_notes: ContactNotes
    contacts: Contacts
    customers: Customers
    forms: Forms
    hooks: Hooks
    payouts: Payouts
    offers: Offers
    purchases: Purchases

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        access_token: str | None = None,
        refresh_token: str | None = None,
        base_url: str = "https://api.kajabi.com",
        timeout: float | httpx.Timeout | None = 30.0,
        max_retries: int = 2,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._auth = KajabiAuth(
            client_id=_credential(client_id, "KAJABI_CLIENT_ID"),
            client_secret=_credential(client_secret, "KAJABI_CLIENT_SECRET"),
            access_token=access_token,
            refresh_token=refresh_token,
            base_url=self.base_url,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
        )
        self._http.event_hooks["response"].append(self._guard_redirect)
        _mount(self)

    def __enter__(self) -> Kajabi:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _guard_redirect(self, response: httpx.Response) -> None:
        _check_redirect(self.base_url, response)

    def close(self) -> None:
        """Close the HTTP client this object created.

        A client passed in as ``http_client`` is left open. This still removes
        the redirect hook installed on that client.
        """
        _detach_hook(self._http, self._guard_redirect)
        if self._owns_http:
            self._http.close()

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: Params = None,
        content: bytes | None = None,
        content_type: str | None = None,
        headers: Mapping[str, str] | None = None,
        authenticated: bool = True,
    ) -> httpx.Response:
        """Send one HTTP request and return the response.

        Absolute URLs must match this client's origin. A redirect to another
        origin raises before that request is sent. ``authenticated=False``
        skips bearer auth. The returned response has already been read.
        """
        url = _absolute(self.base_url, path, params)
        selected: httpx.Auth | None = self._auth if authenticated else None
        attempt = 0
        while True:
            try:
                response = self._http.send(
                    _outgoing(method, url, content, content_type, headers),
                    auth=selected,
                )
            except httpx.TransportError as exc:
                outcome = _retry_outcome(
                    method=method,
                    attempt=attempt,
                    max_retries=self.max_retries,
                    transport_error=exc,
                )
                if isinstance(outcome, Exception):
                    raise outcome from exc
                if not isinstance(outcome, float):
                    raise KajabiError("Retry decision was not a delay.") from exc
                _clock.sleep(outcome)
                attempt += 1
                continue
            outcome = _retry_outcome(
                method=method,
                attempt=attempt,
                max_retries=self.max_retries,
                response=response,
            )
            if outcome is None:
                return response
            if isinstance(outcome, Exception):
                response.close()
                raise outcome
            response.close()
            _clock.sleep(outcome)
            attempt += 1

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> Any:
        """Send a JSON:API request and return the parsed body.

        ``Accept`` is ``application/vnd.api+json``. When ``json`` is given, the
        body uses that content type too. An empty body returns ``None``.
        Absolute URLs must match this client's origin. Retries follow the same
        policy as the resource methods.
        """
        query = None if params is None else list(params.items())
        body = None if json is None else _dump(json)
        content_type = None if json is None else JSON_API
        return read_json(
            self._send(method, path, params=query, content=body, content_type=content_type)
        )

    def _get_page(self, path: str, model: type[T], *, params: Params = None) -> Page[T]:
        payload = read_json(self._send("GET", path, params=params))
        items, meta, links = parse_collection(payload, model)

        def fetch(url: str) -> Page[T]:
            return self._get_page(url, model)

        return Page(data=items, meta=meta, links=links, _fetch=fetch)

    def _get_resource(self, path: str, model: type[T], *, params: Params = None) -> T:
        payload = read_json(self._send("GET", path, params=params))
        return parse_one(payload, model)

    def _get_identifiers(self, path: str, *, params: Params = None) -> Page[ResourceIdentifier]:
        payload = read_json(self._send("GET", path, params=params))
        items, meta, links = parse_identifiers(payload)

        def fetch(url: str) -> Page[ResourceIdentifier]:
            return self._get_identifiers(url)

        return Page(data=items, meta=meta, links=links, _fetch=fetch)

    def _send_json(self, method: str, path: str, body: Mapping[str, Any], model: type[T]) -> T:
        payload = read_json(self._send(method, path, content=_dump(body), content_type=JSON_API))
        return parse_one(payload, model)

    def _send_identifiers(
        self, method: str, path: str, body: Mapping[str, Any]
    ) -> list[ResourceIdentifier]:
        payload = read_json(self._send(method, path, content=_dump(body), content_type=JSON_API))
        items, _meta, _links = parse_identifiers(payload)
        return items

    def _post_resource(self, path: str, model: type[T]) -> T:
        """POST with no body and parse the resource Kajabi returns."""
        payload = read_json(self._send("POST", path))
        return parse_one(payload, model)

    def _delete(self, path: str, *, body: Mapping[str, Any] | None = None) -> None:
        content = None if body is None else _dump(body)
        content_type = JSON_API if body is not None else None
        response = self._send("DELETE", path, content=content, content_type=content_type)
        response.close()

    def _request_json(self, method: str, path: str) -> Any:
        """Return the parsed JSON body. Used for webhook sample payloads."""
        return read_json(self._send(method, path))

    def me(self) -> User:
        """Return the user that owns the access token (``GET /v1/me``)."""
        return self._get_resource("/v1/me", User)

    def version(self) -> Version:
        """Return API version information. This endpoint does not use auth."""
        payload = read_json(self._send("GET", "/v1/version", authenticated=False))
        return parse_version(payload)

    def revoke_token(self) -> None:
        """Revoke the cached access token and forget it.

        Sends ``POST /v1/oauth/revoke`` for the token this client already
        holds. Does nothing when no token has been obtained yet, and does not
        fetch a token in order to revoke it.
        """
        token = self._auth.access_token
        if not token:
            return
        content, headers = _revoke_form(token, self._auth.token_type)
        response = self._send(
            "POST",
            "/v1/oauth/revoke",
            content=content,
            content_type="application/x-www-form-urlencoded",
            headers=headers,
            authenticated=False,
        )
        response.close()
        self._auth.clear()


class AsyncKajabi:
    """Asynchronous client for the Kajabi Public API.

    The constructor matches :class:`Kajabi`. Resource methods are coroutines,
    and ``async for item in client.contacts.iter()`` walks every page::

        async with AsyncKajabi(client_id=..., client_secret=...) as kajabi:
            contact = await kajabi.contacts.get("123")

    :meth:`request` is the low-level JSON:API escape hatch, as on :class:`Kajabi`.
    """

    blog_posts: AsyncReadOnly[BlogPost]
    contact_tags: AsyncReadOnly[ContactTag]
    courses: AsyncReadOnly[Course]
    custom_fields: AsyncReadOnly[CustomField]
    form_submissions: AsyncReadOnly[FormSubmission]
    landing_pages: AsyncReadOnly[LandingPage]
    order_items: AsyncReadOnly[OrderItem]
    orders: AsyncReadOnly[Order]
    podcasts: AsyncReadOnly[Podcast]
    products: AsyncReadOnly[Product]
    sites: AsyncReadOnly[Site]
    transactions: AsyncReadOnly[Transaction]
    website_pages: AsyncReadOnly[WebsitePage]
    contact_notes: AsyncContactNotes
    contacts: AsyncContacts
    customers: AsyncCustomers
    forms: AsyncForms
    hooks: AsyncHooks
    payouts: AsyncPayouts
    offers: AsyncOffers
    purchases: AsyncPurchases

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        access_token: str | None = None,
        refresh_token: str | None = None,
        base_url: str = "https://api.kajabi.com",
        timeout: float | httpx.Timeout | None = 30.0,
        max_retries: int = 2,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._auth = KajabiAuth(
            client_id=_credential(client_id, "KAJABI_CLIENT_ID"),
            client_secret=_credential(client_secret, "KAJABI_CLIENT_SECRET"),
            access_token=access_token,
            refresh_token=refresh_token,
            base_url=self.base_url,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
        )
        self._http.event_hooks["response"].append(self._guard_redirect)
        _mount(self)

    async def __aenter__(self) -> AsyncKajabi:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _guard_redirect(self, response: httpx.Response) -> None:
        _check_redirect(self.base_url, response)

    async def aclose(self) -> None:
        """Close the HTTP client this object created.

        A client passed in as ``http_client`` is left open. This still removes
        the redirect hook installed on that client.
        """
        _detach_hook(self._http, self._guard_redirect)
        if self._owns_http:
            await self._http.aclose()

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: Params = None,
        content: bytes | None = None,
        content_type: str | None = None,
        headers: Mapping[str, str] | None = None,
        authenticated: bool = True,
    ) -> httpx.Response:
        """Async twin of :meth:`Kajabi._send`."""
        url = _absolute(self.base_url, path, params)
        selected: httpx.Auth | None = self._auth if authenticated else None
        attempt = 0
        while True:
            try:
                response = await self._http.send(
                    _outgoing(method, url, content, content_type, headers),
                    auth=selected,
                )
            except httpx.TransportError as exc:
                outcome = _retry_outcome(
                    method=method,
                    attempt=attempt,
                    max_retries=self.max_retries,
                    transport_error=exc,
                )
                if isinstance(outcome, Exception):
                    raise outcome from exc
                if not isinstance(outcome, float):
                    raise KajabiError("Retry decision was not a delay.") from exc
                await _clock.asleep(outcome)
                attempt += 1
                continue
            outcome = _retry_outcome(
                method=method,
                attempt=attempt,
                max_retries=self.max_retries,
                response=response,
            )
            if outcome is None:
                return response
            if isinstance(outcome, Exception):
                await response.aclose()
                raise outcome
            await response.aclose()
            await _clock.asleep(outcome)
            attempt += 1

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> Any:
        """Async twin of :meth:`Kajabi.request`."""
        query = None if params is None else list(params.items())
        body = None if json is None else _dump(json)
        content_type = None if json is None else JSON_API
        return read_json(
            await self._send(method, path, params=query, content=body, content_type=content_type)
        )

    async def _get_page(self, path: str, model: type[T], *, params: Params = None) -> AsyncPage[T]:
        payload = read_json(await self._send("GET", path, params=params))
        items, meta, links = parse_collection(payload, model)

        async def fetch(url: str) -> AsyncPage[T]:
            return await self._get_page(url, model)

        return AsyncPage(data=items, meta=meta, links=links, _fetch=fetch)

    async def _get_resource(self, path: str, model: type[T], *, params: Params = None) -> T:
        payload = read_json(await self._send("GET", path, params=params))
        return parse_one(payload, model)

    async def _get_identifiers(
        self, path: str, *, params: Params = None
    ) -> AsyncPage[ResourceIdentifier]:
        payload = read_json(await self._send("GET", path, params=params))
        items, meta, links = parse_identifiers(payload)

        async def fetch(url: str) -> AsyncPage[ResourceIdentifier]:
            return await self._get_identifiers(url)

        return AsyncPage(data=items, meta=meta, links=links, _fetch=fetch)

    async def _send_json(
        self, method: str, path: str, body: Mapping[str, Any], model: type[T]
    ) -> T:
        payload = read_json(
            await self._send(method, path, content=_dump(body), content_type=JSON_API)
        )
        return parse_one(payload, model)

    async def _send_identifiers(
        self, method: str, path: str, body: Mapping[str, Any]
    ) -> list[ResourceIdentifier]:
        payload = read_json(
            await self._send(method, path, content=_dump(body), content_type=JSON_API)
        )
        items, _meta, _links = parse_identifiers(payload)
        return items

    async def _post_resource(self, path: str, model: type[T]) -> T:
        payload = read_json(await self._send("POST", path))
        return parse_one(payload, model)

    async def _delete(self, path: str, *, body: Mapping[str, Any] | None = None) -> None:
        content = None if body is None else _dump(body)
        content_type = JSON_API if body is not None else None
        response = await self._send("DELETE", path, content=content, content_type=content_type)
        await response.aclose()

    async def _request_json(self, method: str, path: str) -> Any:
        return read_json(await self._send(method, path))

    async def me(self) -> User:
        """Return the user that owns the access token (``GET /v1/me``)."""
        return await self._get_resource("/v1/me", User)

    async def version(self) -> Version:
        """Return API version information. This endpoint does not use auth."""
        payload = read_json(await self._send("GET", "/v1/version", authenticated=False))
        return parse_version(payload)

    async def revoke_token(self) -> None:
        """Revoke the cached access token and forget it.

        Sends ``POST /v1/oauth/revoke`` for the token this client already
        holds. Does nothing when no token has been obtained yet, and does not
        fetch a token in order to revoke it.
        """
        token = self._auth.access_token
        if not token:
            return
        content, headers = _revoke_form(token, self._auth.token_type)
        response = await self._send(
            "POST",
            "/v1/oauth/revoke",
            content=content,
            content_type="application/x-www-form-urlencoded",
            headers=headers,
            authenticated=False,
        )
        await response.aclose()
        self._auth.clear()


# Read-only rows are (attribute, path, model). The other rows are
# (attribute, sync class, async class). Both clients are built from this.
_NAMESPACE_TABLE = (
    (
        ("blog_posts", "/v1/blog_posts", BlogPost),
        ("contact_tags", "/v1/contact_tags", ContactTag),
        ("courses", "/v1/courses", Course),
        ("custom_fields", "/v1/custom_fields", CustomField),
        ("form_submissions", "/v1/form_submissions", FormSubmission),
        ("landing_pages", "/v1/landing_pages", LandingPage),
        ("order_items", "/v1/order_items", OrderItem),
        ("orders", "/v1/orders", Order),
        ("podcasts", "/v1/podcasts", Podcast),
        ("products", "/v1/products", Product),
        ("sites", "/v1/sites", Site),
        ("transactions", "/v1/transactions", Transaction),
        ("website_pages", "/v1/website_pages", WebsitePage),
    ),
    (
        ("contact_notes", ContactNotes, AsyncContactNotes),
        ("contacts", Contacts, AsyncContacts),
        ("customers", Customers, AsyncCustomers),
        ("forms", Forms, AsyncForms),
        ("hooks", Hooks, AsyncHooks),
        ("payouts", Payouts, AsyncPayouts),
        ("offers", Offers, AsyncOffers),
        ("purchases", Purchases, AsyncPurchases),
    ),
)


def _mount(client: Kajabi | AsyncKajabi) -> None:
    """Attach every namespace in :data:`_NAMESPACE_TABLE`."""
    read_only, namespaces = _NAMESPACE_TABLE
    if isinstance(client, AsyncKajabi):
        for attribute, path, model in read_only:
            setattr(client, attribute, AsyncReadOnly(client, path, model))
        for attribute, _sync_namespace, async_namespace in namespaces:
            setattr(client, attribute, async_namespace(client))
        return
    for attribute, path, model in read_only:
        setattr(client, attribute, ReadOnly(client, path, model))
    for attribute, sync_namespace, _async_namespace in namespaces:
        setattr(client, attribute, sync_namespace(client))
