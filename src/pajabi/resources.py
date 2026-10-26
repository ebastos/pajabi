"""Resource namespaces shared by the sync and async clients.

JSON:API documents are built by the functions at the top of this module. Sync
and async classes only choose the transport and whether to ``await``. List
queries share :class:`_Listing`, and ``iter`` follows pages by calling ``list``
instead of repeating it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, ParamSpec, Protocol, TypeVar
from urllib.parse import quote

from typing_extensions import Required, TypedDict, Unpack

from pajabi._bodies import (
    identifiers_document,
    one_or_many,
    resource_document,
    to_one,
)
from pajabi._query import Fields, FilterValue, Include, encode_query, merge_filters
from pajabi.errors import KajabiError
from pajabi.models import (
    Contact,
    ContactNote,
    Customer,
    Form,
    FormSubmission,
    Hook,
    Offer,
    Payout,
    Purchase,
    Resource,
    ResourceIdentifier,
)
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

SAMPLE_EVENTS = (
    "tag_added",
    "tag_removed",
    "form_submission",
    "purchase",
    "payment_succeeded",
    "order_created",
)


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


class ContactAttributes(TypedDict, total=False):
    """Fields accepted by ``contacts.create`` and ``contacts.update``.

    A key that is absent is omitted from the JSON body. ``None`` is sent as JSON null.
    """

    name: str | None
    email: str | None
    phone_number: str | None
    business_number: str | None
    subscribed: bool | None
    address_line_1: str | None
    address_line_2: str | None
    address_city: str | None
    address_state: str | None
    address_country: str | None
    address_zip: str | None
    external_user_id: str | None
    custom_1: str | None
    custom_2: str | None
    custom_3: str | None


class FormSubmissionAttributes(TypedDict, total=False):
    """Fields accepted by ``forms.submit``. ``name`` and ``email`` are required."""

    name: Required[str]
    email: Required[str]
    phone_number: str | None
    business_number: str | None
    address_line_1: str | None
    address_line_2: str | None
    address_city: str | None
    address_state: str | None
    address_country: str | None
    address_zip: str | None
    custom_1: str | None
    custom_2: str | None
    custom_3: str | None


def contact_create_body(site_id: str, attributes: ContactAttributes) -> dict[str, Any]:
    return resource_document(
        resource_type="contacts",
        attributes=attributes,
        relationships={"site": to_one(str(site_id), "sites")},
    )


def contact_update_body(
    contact_id: str,
    attributes: ContactAttributes,
    tags: Ids | None,
) -> dict[str, Any]:
    """Build a contact update.

    The spec puts ``relationships`` next to ``data`` on this request, not inside
    it. Other resources keep relationships inside ``data``. ``tags`` is omitted
    when it is ``None``, including when the caller left it out.
    """
    body = resource_document(
        resource_type="contacts",
        resource_id=str(contact_id),
        attributes=attributes,
    )
    if tags is not None:
        body["relationships"] = {"tags": {"data": tag_document(tags)["data"]}}
    return body


def note_create_body(contact_id: str, body: str) -> dict[str, Any]:
    return resource_document(
        resource_type="contact_notes",
        attributes={"body": body},
        relationships={"contact": to_one(str(contact_id), "contacts")},
    )


def note_update_body(note_id: str, body: str) -> dict[str, Any]:
    return resource_document(
        resource_type="contact_notes",
        resource_id=str(note_id),
        attributes={"body": body},
    )


def hook_create_body(
    *,
    site_id: str,
    event: str,
    target_url: str,
    resource_id: int | None,
) -> dict[str, Any]:
    attributes: dict[str, Any] = {"event": event, "target_url": target_url}
    if resource_id is not None:
        attributes["resource_id"] = resource_id
    return resource_document(
        resource_type="hooks",
        attributes=attributes,
        relationships={"site": to_one(str(site_id), "sites")},
    )


def form_submit_body(attributes: FormSubmissionAttributes) -> dict[str, Any]:
    return resource_document(resource_type="form_submissions", attributes=attributes)


def _sample_path(event: str) -> str:
    if event not in SAMPLE_EVENTS:
        known = ", ".join(SAMPLE_EVENTS)
        raise KajabiError(f"Unknown webhook sample {event!r}. Expected one of: {known}.")
    return f"/v1/hooks/{event}_sample"


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


class OfferGrants:
    """Offers granted to a contact or a customer.

    ``owner_id`` is that contact or customer. ``offer_ids`` is one id or a sequence of ids.
    """

    def __init__(self, api: SyncAPI, collection: str) -> None:
        self._api = api
        self._collection = collection

    def _path(self, owner_id: str) -> str:
        return relationship_path(self._collection, owner_id, "offers")

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
        """List offers granted to one contact or customer."""
        return self._api._get_identifiers(
            self._path(owner_id),
            params=_Listing(
                sort=sort, include=include, fields=fields, page=page, page_size=page_size
            ).params(filters),
        )

    iter = _pages(list)

    def _change(
        self,
        method: str,
        owner_id: str,
        offer_ids: Ids,
        send_welcome_email: bool | None,
    ) -> _List[ResourceIdentifier]:
        return self._api._send_identifiers(
            method,
            self._path(owner_id),
            offer_document(offer_ids, send_welcome_email),
        )

    def grant(
        self,
        owner_id: str,
        offer_ids: Ids,
        *,
        send_welcome_email: bool | None = None,
    ) -> _List[ResourceIdentifier]:
        """Grant offers. Welcome-email meta is sent only when ``send_welcome_email`` is passed."""
        return self._change("POST", owner_id, offer_ids, send_welcome_email)

    def revoke(self, owner_id: str, offer_ids: Ids) -> _List[ResourceIdentifier]:
        """Revoke offers from the contact or customer."""
        return self._change("DELETE", owner_id, offer_ids, None)

    def replace(self, owner_id: str, offer_ids: Ids) -> _List[ResourceIdentifier]:
        """Replace the contact's or customer's offers with ``offer_ids``."""
        return self._change("PATCH", owner_id, offer_ids, None)


class AsyncOfferGrants:
    """Async twin of :class:`OfferGrants`."""

    def __init__(self, api: AsyncAPI, collection: str) -> None:
        self._api = api
        self._collection = collection

    def _path(self, owner_id: str) -> str:
        return relationship_path(self._collection, owner_id, "offers")

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
        """List offers granted to one contact or customer."""
        return await self._api._get_identifiers(
            self._path(owner_id),
            params=_Listing(
                sort=sort, include=include, fields=fields, page=page, page_size=page_size
            ).params(filters),
        )

    iter = _apages(list)

    async def _change(
        self,
        method: str,
        owner_id: str,
        offer_ids: Ids,
        send_welcome_email: bool | None,
    ) -> _List[ResourceIdentifier]:
        return await self._api._send_identifiers(
            method,
            self._path(owner_id),
            offer_document(offer_ids, send_welcome_email),
        )

    async def grant(
        self,
        owner_id: str,
        offer_ids: Ids,
        *,
        send_welcome_email: bool | None = None,
    ) -> _List[ResourceIdentifier]:
        """Grant offers. Welcome-email meta is sent only when ``send_welcome_email`` is passed."""
        return await self._change("POST", owner_id, offer_ids, send_welcome_email)

    async def revoke(self, owner_id: str, offer_ids: Ids) -> _List[ResourceIdentifier]:
        return await self._change("DELETE", owner_id, offer_ids, None)

    async def replace(self, owner_id: str, offer_ids: Ids) -> _List[ResourceIdentifier]:
        return await self._change("PATCH", owner_id, offer_ids, None)


class ContactTags:
    """Tags on one contact (``/v1/contacts/{id}/relationships/tags``)."""

    def __init__(self, api: SyncAPI) -> None:
        self._api = api

    def _path(self, contact_id: str) -> str:
        return relationship_path("contacts", contact_id, "tags")

    def list(
        self,
        contact_id: str,
        *,
        sort: str | None = None,
        include: Include | None = None,
        fields: Fields | None = None,
        page: int | None = None,
        page_size: int | None = None,
        **filters: FilterValue,
    ) -> Page[ResourceIdentifier]:
        """List a contact's tags."""
        return self._api._get_identifiers(
            self._path(contact_id),
            params=_Listing(
                sort=sort, include=include, fields=fields, page=page, page_size=page_size
            ).params(filters),
        )

    iter = _pages(list)

    def _write(self, method: str, contact_id: str, tag_ids: Ids) -> _List[ResourceIdentifier]:
        return self._api._send_identifiers(method, self._path(contact_id), tag_document(tag_ids))

    def add(self, contact_id: str, tag_ids: Ids) -> _List[ResourceIdentifier]:
        """Add tags to a contact."""
        return self._write("POST", contact_id, tag_ids)

    def remove(self, contact_id: str, tag_ids: Ids) -> _List[ResourceIdentifier]:
        """Remove tags from a contact."""
        return self._write("DELETE", contact_id, tag_ids)

    def replace(self, contact_id: str, tag_ids: Ids) -> _List[ResourceIdentifier]:
        """Replace a contact's tags with ``tag_ids``."""
        return self._write("PATCH", contact_id, tag_ids)


class AsyncContactTags:
    """Async twin of :class:`ContactTags`."""

    def __init__(self, api: AsyncAPI) -> None:
        self._api = api

    def _path(self, contact_id: str) -> str:
        return relationship_path("contacts", contact_id, "tags")

    async def list(
        self,
        contact_id: str,
        *,
        sort: str | None = None,
        include: Include | None = None,
        fields: Fields | None = None,
        page: int | None = None,
        page_size: int | None = None,
        **filters: FilterValue,
    ) -> AsyncPage[ResourceIdentifier]:
        return await self._api._get_identifiers(
            self._path(contact_id),
            params=_Listing(
                sort=sort, include=include, fields=fields, page=page, page_size=page_size
            ).params(filters),
        )

    iter = _apages(list)

    async def _write(self, method: str, contact_id: str, tag_ids: Ids) -> _List[ResourceIdentifier]:
        return await self._api._send_identifiers(
            method, self._path(contact_id), tag_document(tag_ids)
        )

    async def add(self, contact_id: str, tag_ids: Ids) -> _List[ResourceIdentifier]:
        return await self._write("POST", contact_id, tag_ids)

    async def remove(self, contact_id: str, tag_ids: Ids) -> _List[ResourceIdentifier]:
        return await self._write("DELETE", contact_id, tag_ids)

    async def replace(self, contact_id: str, tag_ids: Ids) -> _List[ResourceIdentifier]:
        return await self._write("PATCH", contact_id, tag_ids)


class Contacts(ReadOnly[Contact]):
    """Contacts, including their tags and offers."""

    def __init__(self, api: SyncAPI) -> None:
        super().__init__(api, "/v1/contacts", Contact)
        self.tags = ContactTags(api)
        self.offers = OfferGrants(api, "contacts")

    def create(self, *, site_id: str, **attributes: Unpack[ContactAttributes]) -> Contact:
        """Create a contact on ``site_id``.

        Keyword fields are :class:`ContactAttributes`. Omitted keys are left out
        of the body. ``None`` is sent as JSON null.
        """
        return self._api._send_json(
            "POST",
            self._path,
            contact_create_body(site_id, attributes),
            Contact,
        )

    def update(
        self,
        contact_id: str,
        *,
        tags: Ids | None = None,
        **attributes: Unpack[ContactAttributes],
    ) -> Contact:
        """Update a contact.

        ``tags=None`` (the default) leaves the contact's tags unchanged. Pass a
        list, including ``[]``, to replace them.
        """
        return self._api._send_json(
            "PATCH",
            item_path(self._path, contact_id),
            contact_update_body(contact_id, attributes, tags),
            Contact,
        )

    def delete(self, contact_id: str) -> None:
        """Delete a contact."""
        self._api._delete(item_path(self._path, contact_id))


class AsyncContacts(AsyncReadOnly[Contact]):
    """Async twin of :class:`Contacts`."""

    def __init__(self, api: AsyncAPI) -> None:
        super().__init__(api, "/v1/contacts", Contact)
        self.tags = AsyncContactTags(api)
        self.offers = AsyncOfferGrants(api, "contacts")

    async def create(self, *, site_id: str, **attributes: Unpack[ContactAttributes]) -> Contact:
        """Create a contact. See :meth:`Contacts.create`."""
        return await self._api._send_json(
            "POST",
            self._path,
            contact_create_body(site_id, attributes),
            Contact,
        )

    async def update(
        self,
        contact_id: str,
        *,
        tags: Ids | None = None,
        **attributes: Unpack[ContactAttributes],
    ) -> Contact:
        """Update a contact. See :meth:`Contacts.update`."""
        return await self._api._send_json(
            "PATCH",
            item_path(self._path, contact_id),
            contact_update_body(contact_id, attributes, tags),
            Contact,
        )

    async def delete(self, contact_id: str) -> None:
        await self._api._delete(item_path(self._path, contact_id))


class ContactNotes(ReadOnly[ContactNote]):
    """Notes attached to contacts."""

    def __init__(self, api: SyncAPI) -> None:
        super().__init__(api, "/v1/contact_notes", ContactNote)

    def create(self, *, contact_id: str, body: str) -> ContactNote:
        """Create a note on a contact."""
        return self._api._send_json(
            "POST", self._path, note_create_body(contact_id, body), ContactNote
        )

    def update(self, note_id: str, *, body: str) -> ContactNote:
        """Replace a note's body."""
        return self._api._send_json(
            "PATCH",
            item_path(self._path, note_id),
            note_update_body(note_id, body),
            ContactNote,
        )

    def delete(self, note_id: str) -> None:
        """Delete a note."""
        self._api._delete(item_path(self._path, note_id))


class AsyncContactNotes(AsyncReadOnly[ContactNote]):
    """Async twin of :class:`ContactNotes`."""

    def __init__(self, api: AsyncAPI) -> None:
        super().__init__(api, "/v1/contact_notes", ContactNote)

    async def create(self, *, contact_id: str, body: str) -> ContactNote:
        return await self._api._send_json(
            "POST", self._path, note_create_body(contact_id, body), ContactNote
        )

    async def update(self, note_id: str, *, body: str) -> ContactNote:
        return await self._api._send_json(
            "PATCH",
            item_path(self._path, note_id),
            note_update_body(note_id, body),
            ContactNote,
        )

    async def delete(self, note_id: str) -> None:
        await self._api._delete(item_path(self._path, note_id))


class Customers(ReadOnly[Customer]):
    """Customers and the offers granted to them."""

    def __init__(self, api: SyncAPI) -> None:
        super().__init__(api, "/v1/customers", Customer)
        self.offers = OfferGrants(api, "customers")


class AsyncCustomers(AsyncReadOnly[Customer]):
    """Async twin of :class:`Customers`."""

    def __init__(self, api: AsyncAPI) -> None:
        super().__init__(api, "/v1/customers", Customer)
        self.offers = AsyncOfferGrants(api, "customers")


class Forms(ReadOnly[Form]):
    """Forms and form submission."""

    def __init__(self, api: SyncAPI) -> None:
        super().__init__(api, "/v1/forms", Form)

    def submit(
        self, form_id: str, **attributes: Unpack[FormSubmissionAttributes]
    ) -> FormSubmission:
        """Submit a form. ``name`` and ``email`` are required by Kajabi.

        Fields are :class:`FormSubmissionAttributes`. Kajabi returns
        ``mobile_phone_number`` and does not accept it on submit.
        """
        return self._api._send_json(
            "POST",
            f"{item_path(self._path, form_id)}/submit",
            form_submit_body(attributes),
            FormSubmission,
        )


class AsyncForms(AsyncReadOnly[Form]):
    """Async twin of :class:`Forms`."""

    def __init__(self, api: AsyncAPI) -> None:
        super().__init__(api, "/v1/forms", Form)

    async def submit(
        self, form_id: str, **attributes: Unpack[FormSubmissionAttributes]
    ) -> FormSubmission:
        """Submit a form. See :meth:`Forms.submit`."""
        return await self._api._send_json(
            "POST",
            f"{item_path(self._path, form_id)}/submit",
            form_submit_body(attributes),
            FormSubmission,
        )


class Hooks(ReadOnly[Hook]):
    """Webhook subscriptions."""

    def __init__(self, api: SyncAPI) -> None:
        super().__init__(api, "/v1/hooks", Hook)

    def create(
        self,
        *,
        site_id: str,
        event: str,
        target_url: str,
        resource_id: int | None = None,
    ) -> Hook:
        """Subscribe ``target_url`` to ``event`` on a site.

        Omit ``resource_id`` (or pass ``None``) to receive every event of that
        type. Pass an integer id to limit the subscription to one resource.
        """
        return self._api._send_json(
            "POST",
            self._path,
            hook_create_body(
                site_id=site_id,
                event=event,
                target_url=target_url,
                resource_id=resource_id,
            ),
            Hook,
        )

    def delete(self, hook_id: str) -> None:
        """Delete a webhook subscription."""
        self._api._delete(item_path(self._path, hook_id))

    def sample(self, event: str) -> Any:
        """Return Kajabi's sample payload for a webhook event.

        ``event`` is one of ``tag_added``, ``tag_removed``, ``form_submission``,
        ``purchase``, ``payment_succeeded``, or ``order_created``.
        """
        return self._api._request_json("GET", _sample_path(event))


class AsyncHooks(AsyncReadOnly[Hook]):
    """Async twin of :class:`Hooks`."""

    def __init__(self, api: AsyncAPI) -> None:
        super().__init__(api, "/v1/hooks", Hook)

    async def create(
        self,
        *,
        site_id: str,
        event: str,
        target_url: str,
        resource_id: int | None = None,
    ) -> Hook:
        return await self._api._send_json(
            "POST",
            self._path,
            hook_create_body(
                site_id=site_id,
                event=event,
                target_url=target_url,
                resource_id=resource_id,
            ),
            Hook,
        )

    async def delete(self, hook_id: str) -> None:
        await self._api._delete(item_path(self._path, hook_id))

    async def sample(self, event: str) -> Any:
        return await self._api._request_json("GET", _sample_path(event))


class Offers(ReadOnly[Offer]):
    """Offers."""

    def __init__(self, api: SyncAPI) -> None:
        super().__init__(api, "/v1/offers", Offer)

    def products(
        self,
        offer_id: str,
        *,
        sort: str | None = None,
        include: Include | None = None,
        fields: Fields | None = None,
        page: int | None = None,
        page_size: int | None = None,
        **filters: FilterValue,
    ) -> Page[ResourceIdentifier]:
        """List the products included in an offer.

        The spec returns one identifier list for this relationship and does not
        paginate it, so there is no ``iter``.
        """
        return self._api._get_identifiers(
            relationship_path("offers", offer_id, "products"),
            params=_Listing(
                sort=sort,
                include=include,
                fields=fields,
                page=page,
                page_size=page_size,
            ).params(filters),
        )


class AsyncOffers(AsyncReadOnly[Offer]):
    """Async twin of :class:`Offers`."""

    def __init__(self, api: AsyncAPI) -> None:
        super().__init__(api, "/v1/offers", Offer)

    async def products(
        self,
        offer_id: str,
        *,
        sort: str | None = None,
        include: Include | None = None,
        fields: Fields | None = None,
        page: int | None = None,
        page_size: int | None = None,
        **filters: FilterValue,
    ) -> AsyncPage[ResourceIdentifier]:
        """List the products included in an offer. See :meth:`Offers.products`."""
        return await self._api._get_identifiers(
            relationship_path("offers", offer_id, "products"),
            params=_Listing(
                sort=sort,
                include=include,
                fields=fields,
                page=page,
                page_size=page_size,
            ).params(filters),
        )


class Payouts:
    """Kajabi Payments payouts. ``site_id`` is required on every call.

    Listing and fetching otherwise match :class:`ReadOnly`.
    """

    def __init__(self, api: SyncAPI) -> None:
        self._read = ReadOnly(api, "/v1/kajabi_payments_payouts", Payout)

    def list(
        self,
        *,
        site_id: str,
        sort: str | None = None,
        include: Include | None = None,
        fields: Fields | None = None,
        page: int | None = None,
        page_size: int | None = None,
        **filters: FilterValue,
    ) -> Page[Payout]:
        """List payouts for a site. ``site_id`` is required by the API."""
        return self._read.list(
            sort=sort,
            include=include,
            fields=fields,
            page=page,
            page_size=page_size,
            site_id=site_id,
            **filters,
        )

    iter = _pages(list)

    def get(
        self,
        payout_id: str,
        *,
        site_id: str,
        include: Include | None = None,
        fields: Fields | None = None,
        **filters: FilterValue,
    ) -> Payout:
        """Fetch one payout. ``site_id`` is required by the API."""
        return self._read.get(
            payout_id,
            include=include,
            fields=fields,
            site_id=site_id,
            **filters,
        )


class AsyncPayouts:
    """Async twin of :class:`Payouts`."""

    def __init__(self, api: AsyncAPI) -> None:
        self._read = AsyncReadOnly(api, "/v1/kajabi_payments_payouts", Payout)

    async def list(
        self,
        *,
        site_id: str,
        sort: str | None = None,
        include: Include | None = None,
        fields: Fields | None = None,
        page: int | None = None,
        page_size: int | None = None,
        **filters: FilterValue,
    ) -> AsyncPage[Payout]:
        """List payouts for a site. ``site_id`` is required by the API."""
        return await self._read.list(
            sort=sort,
            include=include,
            fields=fields,
            page=page,
            page_size=page_size,
            site_id=site_id,
            **filters,
        )

    iter = _apages(list)

    async def get(
        self,
        payout_id: str,
        *,
        site_id: str,
        include: Include | None = None,
        fields: Fields | None = None,
        **filters: FilterValue,
    ) -> Payout:
        """Fetch one payout. See :meth:`Payouts.get`."""
        return await self._read.get(
            payout_id,
            include=include,
            fields=fields,
            site_id=site_id,
            **filters,
        )


class Purchases(ReadOnly[Purchase]):
    """Purchases, including subscription actions."""

    def __init__(self, api: SyncAPI) -> None:
        super().__init__(api, "/v1/purchases", Purchase)

    def _action(self, purchase_id: str, action: str) -> Purchase:
        return self._api._post_resource(f"{item_path(self._path, purchase_id)}/{action}", Purchase)

    def reactivate(self, purchase_id: str) -> Purchase:
        """Reactivate a purchase. This does not reactivate its subscription."""
        return self._action(purchase_id, "reactivate")

    def deactivate(self, purchase_id: str) -> Purchase:
        """Deactivate a purchase. This does not cancel its subscription."""
        return self._action(purchase_id, "deactivate")

    def cancel_subscription(self, purchase_id: str) -> Purchase:
        """Cancel the subscription attached to a purchase."""
        return self._action(purchase_id, "cancel_subscription")


class AsyncPurchases(AsyncReadOnly[Purchase]):
    """Async twin of :class:`Purchases`."""

    def __init__(self, api: AsyncAPI) -> None:
        super().__init__(api, "/v1/purchases", Purchase)

    async def _action(self, purchase_id: str, action: str) -> Purchase:
        return await self._api._post_resource(
            f"{item_path(self._path, purchase_id)}/{action}", Purchase
        )

    async def reactivate(self, purchase_id: str) -> Purchase:
        return await self._action(purchase_id, "reactivate")

    async def deactivate(self, purchase_id: str) -> Purchase:
        return await self._action(purchase_id, "deactivate")

    async def cancel_subscription(self, purchase_id: str) -> Purchase:
        return await self._action(purchase_id, "cancel_subscription")
