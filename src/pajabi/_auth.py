"""OAuth2 for the Kajabi API.

``auth_flow`` is the sync flow. httpx drives it for ``Client``. ``AsyncClient``
uses ``async_auth_flow``, which reads each token response itself. A lock is
held only while a token is being exchanged, so concurrent requests share one
refresh and the API call itself stays outside the lock.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncGenerator, Generator
from typing import Any, NoReturn

import httpx

from pajabi import _clock
from pajabi.errors import KajabiError, error_from_response

_MISSING_CREDENTIALS = (
    "No Kajabi credentials are available. Pass client_id and client_secret, or an access_token."
)


def _grant_failed(last: httpx.Response | None) -> NoReturn:
    """Raise when every planned token request failed."""
    if last is None:
        raise KajabiError(_MISSING_CREDENTIALS)
    raise error_from_response(last)


def _copy_request(request: httpx.Request) -> httpx.Request:
    content = request.read()
    return httpx.Request(
        request.method,
        request.url,
        headers=request.headers,
        content=content,
        extensions=dict(request.extensions),
    )


class KajabiAuth(httpx.Auth):
    """Bearer auth that fetches and refreshes Kajabi OAuth tokens."""

    requires_response_body = True

    def __init__(
        self,
        *,
        client_id: str | None,
        client_secret: str | None,
        access_token: str | None,
        refresh_token: str | None,
        base_url: str,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_type = "Bearer"
        self.expires_at: float | None = None
        self.base_url = base_url
        self._generation = 0
        self._sync_lock = threading.Lock()
        # 3.10+ allows creating the lock before a loop is running.
        self._async_lock = asyncio.Lock()

    def needs_refresh(self) -> bool:
        """True when there is no token, or the cached token is inside the expiry window."""
        if not self.access_token:
            return True
        if self.expires_at is None:
            return False
        return _clock.now() >= self.expires_at

    def can_reauth(self) -> bool:
        """True when a 401 can be followed by a refresh or a new client-credentials grant."""
        return bool(self.refresh_token or (self.client_id and self.client_secret))

    def clear(self) -> None:
        """Forget cached tokens after revocation. Client credentials are kept."""
        self.access_token = None
        self.refresh_token = None
        self.expires_at = None
        self._generation += 1

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        if self.needs_refresh():
            with self._sync_lock:
                if self.needs_refresh():
                    yield from self._exchange()
        self._authorize(request)
        seen = self._generation
        response = yield request
        if self._should_retry_auth(request, response):
            with self._sync_lock:
                if self._generation == seen:
                    yield from self._exchange()
            retry = _copy_request(request)
            retry.extensions["kajabi_retried"] = True
            self._authorize(retry)
            yield retry

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        # Only requests yielded by this method are sent by httpx. The body of a
        # yielded token response is still unread until ``aread``.
        if self.needs_refresh():
            async with self._async_lock:
                if self.needs_refresh():
                    last: httpx.Response | None = None
                    for token_request in self._grant_plan():
                        response = yield token_request
                        await response.aread()
                        last = response
                        if self._accept(response):
                            break
                    else:
                        _grant_failed(last)
        self._authorize(request)
        seen = self._generation
        response = yield request
        if self._should_retry_auth(request, response):
            async with self._async_lock:
                if self._generation == seen:
                    last = None
                    for token_request in self._grant_plan():
                        grant_response = yield token_request
                        await grant_response.aread()
                        last = grant_response
                        if self._accept(grant_response):
                            break
                    else:
                        _grant_failed(last)
            retry = _copy_request(request)
            retry.extensions["kajabi_retried"] = True
            self._authorize(retry)
            yield retry

    def _exchange(self) -> Generator[httpx.Request, httpx.Response, None]:
        last: httpx.Response | None = None
        for token_request in self._grant_plan():
            response = yield token_request
            last = response
            if self._accept(response):
                return
        _grant_failed(last)

    def _should_retry_auth(self, request: httpx.Request, response: httpx.Response) -> bool:
        return (
            response.status_code == 401
            and not request.extensions.get("kajabi_retried")
            and self.can_reauth()
        )

    def _authorize(self, request: httpx.Request) -> None:
        if not self.access_token:
            raise KajabiError(_MISSING_CREDENTIALS)
        request.headers["Authorization"] = f"{self.token_type} {self.access_token}"

    def _grant_plan(self) -> list[httpx.Request]:
        """Token requests to try, in order.

        Refresh first only when a token is already cached and a refresh token
        is available. Otherwise use client credentials. With no client
        credentials, refresh only.
        """
        plan: list[httpx.Request] = []
        refresh = self.refresh_token
        if self.access_token is not None and refresh:
            plan.append(
                self._token_request({"grant_type": "refresh_token", "refresh_token": refresh})
            )
        client_id = self.client_id
        client_secret = self.client_secret
        if client_id and client_secret:
            plan.append(
                self._token_request(
                    {
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret,
                    }
                )
            )
        if not plan and refresh:
            plan.append(
                self._token_request({"grant_type": "refresh_token", "refresh_token": refresh})
            )
        if not plan:
            raise KajabiError(_MISSING_CREDENTIALS)
        return plan

    def _token_request(self, form: dict[str, str]) -> httpx.Request:
        return httpx.Request(
            "POST",
            f"{self.base_url}/v1/oauth/token",
            data=form,
            headers={"Accept": "application/json"},
        )

    def _accept(self, response: httpx.Response) -> bool:
        if response.status_code >= 400:
            return False
        try:
            payload: Any = response.json()
        except ValueError:
            return False
        if not isinstance(payload, dict):
            return False
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            return False
        self.access_token = token
        refresh = payload.get("refresh_token")
        if isinstance(refresh, str) and refresh:
            self.refresh_token = refresh
        token_type = payload.get("token_type")
        self.token_type = token_type if isinstance(token_type, str) and token_type else "Bearer"
        expires_in = payload.get("expires_in")
        if isinstance(expires_in, (int, float)) and not isinstance(expires_in, bool):
            lifetime = float(expires_in)
            skew = min(30.0, max(0.0, lifetime * 0.1))
            self.expires_at = _clock.now() + lifetime - skew
        else:
            self.expires_at = None
        self._generation += 1
        return True
