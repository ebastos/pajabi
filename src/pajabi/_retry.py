"""Retry delays for idempotent failures and rate limits."""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import timezone
from email.utils import parsedate_to_datetime

import httpx

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "PATCH", "DELETE"})

MAX_BACKOFF = 20.0
INITIAL_BACKOFF = 0.5
# A misbehaving server must not pin a caller for an hour. Retry-After values
# above this, whether a delay or an HTTP date, are capped.
MAX_RETRY_AFTER = 60.0


def backoff_delay(attempt: int, rng: Callable[[], float] | None = None) -> float:
    """Full-jitter exponential backoff. ``attempt`` is 0 for the first retry.

    The ceiling is ``min(MAX_BACKOFF, INITIAL_BACKOFF * 2.0 ** attempt)``.
    ``float ** int`` is a float, so the expression stays typed under mypy.
    """
    ceiling = min(MAX_BACKOFF, INITIAL_BACKOFF * 2.0**attempt)
    rolled = random.random() if rng is None else rng()
    return rolled * ceiling


def _cap_retry_after(delay: float) -> float:
    return min(MAX_RETRY_AFTER, max(0.0, delay))


def retry_after_seconds(response: httpx.Response, *, now: float) -> float | None:
    """Parse ``Retry-After`` as a delay in seconds, capped at ``MAX_RETRY_AFTER``.

    The header may be a number of seconds or an HTTP date. Naive dates are UTC.
    ``None`` means the header is absent or unusable.
    """
    header = response.headers.get("Retry-After")
    if not header:
        return None
    try:
        return _cap_retry_after(float(header))
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(header)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return _cap_retry_after(parsed.timestamp() - now)


def retry_delay(
    *,
    method: str,
    attempt: int,
    max_retries: int,
    response: httpx.Response | None = None,
    transport_error: bool = False,
    now: float = 0.0,
    rng: Callable[[], float] | None = None,
) -> float | None:
    """Return how long to sleep before another attempt, or ``None`` to stop.

    429 is always retried and honours ``Retry-After`` (capped at
    ``MAX_RETRY_AFTER`` seconds). 5xx, connection errors, and timeouts are
    retried only for idempotent methods. ``max_retries`` is the number of
    retries after the first attempt.
    """
    if attempt >= max_retries:
        return None
    if response is not None and response.status_code == 429:
        declared = retry_after_seconds(response, now=now)
        if declared is not None:
            return declared
        return backoff_delay(attempt, rng)
    if method.upper() not in IDEMPOTENT_METHODS:
        return None
    if transport_error:
        return backoff_delay(attempt, rng)
    if response is not None and 500 <= response.status_code <= 599:
        return backoff_delay(attempt, rng)
    return None
