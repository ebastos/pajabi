"""List, get, and identifier relationships shared by the resource namespaces.

Sync and async classes only choose the transport and whether to ``await``.
List queries share :class:`_Listing`, and ``iter`` follows pages by calling
``list`` instead of repeating it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, ParamSpec, Protocol, TypeVar
from urllib.parse import quote

from pajabi._bodies import identifiers_document, one_or_many
from pajabi._query import Fields, FilterValue, Include, encode_query, merge_filters
from pajabi.models import Resource, ResourceIdentifier
from pajabi.pagination import AsyncPage, Page, aiterate, iterate

T = TypeVar("T", bound=Resource)
_Item = TypeVar("_Item")
_P = ParamSpec("_P")
Id = str | int
Ids = Id | Sequence[Id]
# Classes below define a method named ``list``, which would shadow this name
# in their annotations.
_List = list
Query = list[tuple[str, str]] | None


@dataclass(frozen=True, slots=True)
class _Listing:
    """The keyword arguments shared by ``list`` and ``iter``."""

    sort: str | None = None
    include: Include | None = None
    fields: Fields | None = None
    page: int | None = None
    page_size: int | None = None
    site_id: FilterValue = None

    def params(self, filters: Mapping[str, FilterValue] | None = None) -> Query:
        encoded = encode_query(
            sort=self.sort,
            include=self.include,
            fields=self.fields,
            page=self.page,
            page_size=self.page_size,
            filters=merge_filters(filters or {}, site_id=self.site_id),
        )
        return encoded or None


def _pages(first: Callable[_P, Page[_Item]]) -> Callable[_P, Iterator[_Item]]:
    """Build ``iter`` from ``list`` so both share one signature.

    The body is a generator, so the first page is fetched when iteration
    starts, not when ``iter`` is called.
    """

    def iter(*args: _P.args, **kwargs: _P.kwargs) -> Iterator[_Item]:
        yield from iterate(first(*args, **kwargs))

    iter.__doc__ = "Yield every item across pages. Arguments match ``list``."
    return iter


def _apages(
    first: Callable[_P, Coroutine[Any, Any, AsyncPage[_Item]]],
) -> Callable[_P, AsyncIterator[_Item]]:
    """Async twin of :func:`_pages`.

    Calling ``iter`` only builds the async generator. The page request starts
    on the first iteration, so an unused call leaves no coroutine behind.
    """

    async def iter(*args: _P.args, **kwargs: _P.kwargs) -> AsyncIterator[_Item]:
        async for item in aiterate(first(*args, **kwargs)):
            yield item

    iter.__doc__ = "Async-yield every item across pages. Arguments match ``list``."
    return iter


def item_path(prefix: str, resource_id: str) -> str:
    return f"{prefix}/{quote(str(resource_id), safe='')}"


def relationship_path(collection: str, resource_id: str, name: str) -> str:
    return f"/v1/{collection}/{quote(str(resource_id), safe='')}/relationships/{name}"


def offer_document(offer_ids: Ids, send_welcome_email: bool | None) -> dict[str, Any]:
    meta = None
    if send_welcome_email is not None:
        meta = {"send_customer_welcome_email": send_welcome_email}
    return identifiers_document(one_or_many(offer_ids), "offers", meta=meta)


def tag_document(tag_ids: Ids) -> dict[str, Any]:
    return identifiers_document(one_or_many(tag_ids), "contact_tags")


class SyncAPI(Protocol):
    """The slice of :class:`pajabi.Kajabi` that resources call."""

    def _get_page(self, path: str, model: type[T], *, params: Query = None) -> Page[T]: ...

    def _get_resource(self, path: str, model: type[T], *, params: Query = None) -> T: ...

    def _get_identifiers(self, path: str, *, params: Query = None) -> Page[ResourceIdentifier]: ...

    def _send_json(self, method: str, path: str, body: Mapping[str, Any], model: type[T]) -> T: ...

    def _send_identifiers(
        self, method: str, path: str, body: Mapping[str, Any]
    ) -> _List[ResourceIdentifier]: ...

    def _post_resource(self, path: str, model: type[T]) -> T: ...

    def _delete(self, path: str, *, body: Mapping[str, Any] | None = None) -> None: ...

    def _request_json(self, method: str, path: str) -> Any: ...


class AsyncAPI(Protocol):
    """The slice of :class:`pajabi.AsyncKajabi` that async resources call."""

    async def _get_page(
        self, path: str, model: type[T], *, params: Query = None
    ) -> AsyncPage[T]: ...

    async def _get_resource(self, path: str, model: type[T], *, params: Query = None) -> T: ...

    async def _get_identifiers(
        self, path: str, *, params: Query = None
    ) -> AsyncPage[ResourceIdentifier]: ...

    async def _send_json(
        self, method: str, path: str, body: Mapping[str, Any], model: type[T]
    ) -> T: ...

    async def _send_identifiers(
        self, method: str, path: str, body: Mapping[str, Any]
    ) -> _List[ResourceIdentifier]: ...

    async def _post_resource(self, path: str, model: type[T]) -> T: ...

    async def _delete(self, path: str, *, body: Mapping[str, Any] | None = None) -> None: ...

    async def _request_json(self, method: str, path: str) -> Any: ...


class ReadOnly(Generic[T]):
    """List and fetch resources of one JSON:API type."""

    def __init__(self, api: SyncAPI, path: str, model: type[T]) -> None:
        self._api = api
        self._path = path
        self._model = model

    def list(
        self,
        *,
        sort: str | None = None,
        include: Include | None = None,
        fields: Fields | None = None,
        page: int | None = None,
        page_size: int | None = None,
        site_id: FilterValue = None,
        **filters: FilterValue,
    ) -> Page[T]:
        """Return one page.

        Each keyword in ``filters`` is sent as ``filter[<name>]``. ``include``
        is a comma-separated string or a list of relationship paths. ``fields``
        maps a JSON:API type to attribute names. ``sort="-created_at"`` sorts
        descending.
        """
        return self._api._get_page(
            self._path,
            self._model,
            params=_Listing(
                sort=sort,
                include=include,
                fields=fields,
                page=page,
                page_size=page_size,
                site_id=site_id,
            ).params(filters),
        )

    iter = _pages(list)

    def get(
        self,
        resource_id: str,
        *,
        include: Include | None = None,
        fields: Fields | None = None,
        **filters: FilterValue,
    ) -> T:
        """Fetch one resource by id."""
        return self._api._get_resource(
            item_path(self._path, resource_id),
            self._model,
            params=_Listing(include=include, fields=fields).params(filters),
        )


class AsyncReadOnly(Generic[T]):
    """Async twin of :class:`ReadOnly`."""

    def __init__(self, api: AsyncAPI, path: str, model: type[T]) -> None:
        self._api = api
        self._path = path
        self._model = model

    async def list(
        self,
        *,
        sort: str | None = None,
        include: Include | None = None,
        fields: Fields | None = None,
        page: int | None = None,
        page_size: int | None = None,
        site_id: FilterValue = None,
        **filters: FilterValue,
    ) -> AsyncPage[T]:
        """Return one page. See :meth:`ReadOnly.list`."""
        return await self._api._get_page(
            self._path,
            self._model,
            params=_Listing(
                sort=sort,
                include=include,
                fields=fields,
                page=page,
                page_size=page_size,
                site_id=site_id,
            ).params(filters),
        )

    iter = _apages(list)

    async def get(
        self,
        resource_id: str,
        *,
        include: Include | None = None,
        fields: Fields | None = None,
        **filters: FilterValue,
    ) -> T:
        """Fetch one resource by id."""
        return await self._api._get_resource(
            item_path(self._path, resource_id),
            self._model,
            params=_Listing(include=include, fields=fields).params(filters),
        )


class _IdentifierRelation:
    """``list``, ``iter``, and the write call for one identifier relationship."""

    def __init__(self, api: SyncAPI, collection: str, name: str) -> None:
        self._api = api
        self._collection = collection
        self._name = name

    def list(
        self,
        owner_id: str,
        *,
        sort: str | None = None,
        include: Include | None = None,
        fields: Fields | None = None,
        page: int | None = None,
        page_size: int | None = None,
        **filters: FilterValue,
    ) -> Page[ResourceIdentifier]:
        """Return one page of identifiers for ``owner_id``."""
        return self._api._get_identifiers(
            relationship_path(self._collection, owner_id, self._name),
            params=_Listing(
                sort=sort, include=include, fields=fields, page=page, page_size=page_size
            ).params(filters),
        )

    iter = _pages(list)

    def _change(
        self, method: str, owner_id: str, body: Mapping[str, Any]
    ) -> _List[ResourceIdentifier]:
        return self._api._send_identifiers(
            method,
            relationship_path(self._collection, owner_id, self._name),
            body,
        )


class _AsyncIdentifierRelation:
    """Async twin of :class:`_IdentifierRelation`."""

    def __init__(self, api: AsyncAPI, collection: str, name: str) -> None:
        self._api = api
        self._collection = collection
        self._name = name

    async def list(
        self,
        owner_id: str,
        *,
        sort: str | None = None,
        include: Include | None = None,
        fields: Fields | None = None,
        page: int | None = None,
        page_size: int | None = None,
        **filters: FilterValue,
    ) -> AsyncPage[ResourceIdentifier]:
        """Return one page of identifiers for ``owner_id``."""
        return await self._api._get_identifiers(
            relationship_path(self._collection, owner_id, self._name),
            params=_Listing(
                sort=sort, include=include, fields=fields, page=page, page_size=page_size
            ).params(filters),
        )

    iter = _apages(list)

    async def _change(
        self, method: str, owner_id: str, body: Mapping[str, Any]
    ) -> _List[ResourceIdentifier]:
        return await self._api._send_identifiers(
            method,
            relationship_path(self._collection, owner_id, self._name),
            body,
        )


class OfferGrants(_IdentifierRelation):
    """Offers granted to a contact or a customer.

    ``owner_id`` is that contact or customer. ``offer_ids`` is one id or a sequence of ids.
    """

    def __init__(self, api: SyncAPI, collection: str) -> None:
        super().__init__(api, collection, "offers")

    def grant(
        self,
        owner_id: str,
        offer_ids: Ids,
        *,
        send_welcome_email: bool | None = None,
    ) -> _List[ResourceIdentifier]:
        """Grant offers. Welcome-email meta is sent only when ``send_welcome_email`` is passed."""
        return self._change("POST", owner_id, offer_document(offer_ids, send_welcome_email))

    def revoke(self, owner_id: str, offer_ids: Ids) -> _List[ResourceIdentifier]:
        """Revoke offers from the contact or customer."""
        return self._change("DELETE", owner_id, offer_document(offer_ids, None))

    def replace(self, owner_id: str, offer_ids: Ids) -> _List[ResourceIdentifier]:
        """Replace the contact's or customer's offers with ``offer_ids``."""
        return self._change("PATCH", owner_id, offer_document(offer_ids, None))


class AsyncOfferGrants(_AsyncIdentifierRelation):
    """Async twin of :class:`OfferGrants`."""

    def __init__(self, api: AsyncAPI, collection: str) -> None:
        super().__init__(api, collection, "offers")

    async def grant(
        self,
        owner_id: str,
        offer_ids: Ids,
        *,
        send_welcome_email: bool | None = None,
    ) -> _List[ResourceIdentifier]:
        """Grant offers. Welcome-email meta is sent only when ``send_welcome_email`` is passed."""
        return await self._change("POST", owner_id, offer_document(offer_ids, send_welcome_email))

    async def revoke(self, owner_id: str, offer_ids: Ids) -> _List[ResourceIdentifier]:
        return await self._change("DELETE", owner_id, offer_document(offer_ids, None))

    async def replace(self, owner_id: str, offer_ids: Ids) -> _List[ResourceIdentifier]:
        return await self._change("PATCH", owner_id, offer_document(offer_ids, None))
