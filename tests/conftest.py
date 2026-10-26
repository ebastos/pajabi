"""Shared fixtures. Tests never sleep and never read developer credentials."""

from __future__ import annotations

import pytest

import pajabi._clock


@pytest.fixture(autouse=True)
def _clear_kajabi_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KAJABI_CLIENT_ID", raising=False)
    monkeypatch.delenv("KAJABI_CLIENT_SECRET", raising=False)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record retry delays instead of sleeping."""
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)

    async def asleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(pajabi._clock, "sleep", sleep)
    monkeypatch.setattr(pajabi._clock, "asleep", asleep)
    return slept
