"""One page of a Kajabi collection."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class PageMeta:
    """Pagination counters. Missing keys stay ``None``."""

    total_count: int | None = None
    total_pages: int | None = None
    current_page: int | None = None


@dataclass
class PageLinks:
    """JSON:API pagination links. ``self`` is ``self_link`` because it is a Python keyword."""

    self_link: str | None = None
    first: str | None = None
    prev: str | None = None
    next: str | None = None
    last: str | None = None
    current: str | None = None


@dataclass
class _PageData(Generic[T]):
    data: list[T]
    meta: PageMeta = field(default_factory=PageMeta)
    links: PageLinks = field(default_factory=PageLinks)

    def has_next_page(self) -> bool:
        """True when the response included a ``links.next`` URL."""
        return bool(self.links.next)

    def __iter__(self) -> Iterator[T]:
        """Iterate the resources on this page only. The attribute is ``data``."""
        return iter(self.data)


@dataclass
class Page(_PageData[T]):
    """A page returned by a sync client.

    Iterating the page yields its own items. Call ``next_page()`` to fetch the
    following page, or use ``resource.iter()`` to walk every page.
    """

    _fetch: Callable[[str], Page[T]] | None = field(default=None, repr=False, compare=False)

    def next_page(self) -> Page[T] | None:
        """Fetch the next page, or return ``None`` when this is the last one."""
        if not self.links.next or self._fetch is None:
            return None
        return self._fetch(self.links.next)


@dataclass
class AsyncPage(_PageData[T]):
    """A page returned by an async client. ``await page.next_page()`` fetches the next one."""

    _fetch: Callable[[str], Awaitable[AsyncPage[T]]] | None = field(
        default=None, repr=False, compare=False
    )

    async def next_page(self) -> AsyncPage[T] | None:
        """Fetch the next page, or return ``None`` when this is the last one."""
        if not self.links.next or self._fetch is None:
            return None
        return await self._fetch(self.links.next)


def iterate(page: Page[T]) -> Iterator[T]:
    """Yield every item on ``page`` and each following page."""
    current: Page[T] | None = page
    seen: set[str] = set()
    while current is not None:
        yield from current.data
        nxt = current.links.next
        if not nxt or nxt in seen:
            return
        seen.add(nxt)
        current = current.next_page()


async def aiterate(first: Awaitable[AsyncPage[T]]) -> AsyncIterator[T]:
    """Async-yield every item starting at the awaited first page."""
    current: AsyncPage[T] | None = await first
    seen: set[str] = set()
    while current is not None:
        for item in current.data:
            yield item
        nxt = current.links.next
        if not nxt or nxt in seen:
            return
        seen.add(nxt)
        current = await current.next_page()
