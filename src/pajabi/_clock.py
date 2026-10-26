"""Time helpers tests can replace without sleeping for real."""

from __future__ import annotations

import asyncio
import time


def now() -> float:
    return time.time()


def sleep(seconds: float) -> None:
    time.sleep(seconds)


async def asleep(seconds: float) -> None:
    await asyncio.sleep(seconds)
