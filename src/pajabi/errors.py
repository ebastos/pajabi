"""Exceptions raised by the Kajabi client."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict


class KajabiError(Exception):
    """Base class for every error raised by this library."""


class APIConnectionError(KajabiError):
    """A request failed before Kajabi returned an HTTP response."""


class APITimeoutError(KajabiError):
    """A request timed out before Kajabi returned an HTTP response."""


class ErrorSource(BaseModel):
    """JSON:API ``source`` object, usually a pointer to the bad field."""

    model_config = ConfigDict(extra="allow")

    pointer: str | None = None


class APIErrorItem(BaseModel):
    """One object from a JSON:API ``errors`` array."""

    model_config = ConfigDict(extra="allow")

    status: str | None = None
    title: str | None = None
    detail: str | None = None
    source: ErrorSource | None = None


class APIError(KajabiError):
    """Kajabi returned an HTTP error.

    ``errors`` is the parsed JSON:API error list (empty when the body was not
    JSON:API). ``str(error)`` joins each item's title, detail, and source pointer.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        errors: list[APIErrorItem] | None = None,
        response: httpx.Response | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.errors = list(errors or [])
        self.response = response


class BadRequestError(APIError):
    """400 Bad Request."""


class AuthenticationError(APIError):
    """401 Unauthorized."""


class PermissionDeniedError(APIError):
    """403 Forbidden."""


class NotFoundError(APIError):
    """404 Not Found."""


class UnprocessableEntityError(APIError):
    """422 Unprocessable Entity."""


class RateLimitError(APIError):
    """429 Too Many Requests."""


class InternalServerError(APIError):
    """5xx response from Kajabi."""


_STATUS_ERRORS: dict[int, type[APIError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    422: UnprocessableEntityError,
    429: RateLimitError,
}


def parse_error_items(payload: Any) -> list[APIErrorItem]:
    """Read JSON:API errors, or an OAuth ``{"error": ...}`` body."""
    if not isinstance(payload, dict):
        return []
    raw_errors = payload.get("errors")
    if isinstance(raw_errors, list):
        items: list[APIErrorItem] = []
        for entry in raw_errors:
            if isinstance(entry, dict):
                items.append(APIErrorItem.model_validate(entry))
            elif entry is not None:
                items.append(APIErrorItem(detail=str(entry)))
        if items:
            return items
    oauth_error = payload.get("error")
    if isinstance(oauth_error, str):
        description = payload.get("error_description")
        detail = description if isinstance(description, str) else None
        return [APIErrorItem(title=oauth_error, detail=detail)]
    return []


def _format_message(status_code: int, errors: list[APIErrorItem], response: httpx.Response) -> str:
    parts: list[str] = []
    for item in errors:
        text = ": ".join(piece for piece in (item.title, item.detail) if piece)
        pointer = item.source.pointer if item.source is not None else None
        if pointer:
            text = f"{text} ({pointer})" if text else pointer
        if text:
            parts.append(text)
    if parts:
        return f"{status_code} {'; '.join(parts)}"
    reason = response.reason_phrase or ""
    body = ""
    try:
        body = response.text.strip()
    except httpx.ResponseNotRead:
        body = ""
    if len(body) > 500:
        body = body[:500] + "..."
    suffix = " ".join(piece for piece in (reason, body) if piece)
    return f"{status_code} {suffix}".rstrip()


def error_from_response(response: httpx.Response) -> APIError:
    """Map an HTTP error response to the matching exception class."""
    payload: Any = None
    try:
        payload = response.json()
    except ValueError:
        payload = None
    items = parse_error_items(payload)
    status_code = response.status_code
    if 500 <= status_code <= 599:
        error_type: type[APIError] = InternalServerError
    else:
        error_type = _STATUS_ERRORS.get(status_code, APIError)
    message = _format_message(status_code, items, response)
    return error_type(message, status_code=status_code, errors=items, response=response)
