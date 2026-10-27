"""Contacts, contact notes, and the tags on a contact."""

from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict, Unpack

from pajabi._bodies import resource_document, to_one
from pajabi._query import Fields, FilterValue, Include
from pajabi.models import Contact, ContactNote, ResourceIdentifier
from pajabi.pagination import AsyncPage, Page
from pajabi.resources._common import (
    AsyncAPI,
    AsyncOfferGrants,
    AsyncReadOnly,
    Ids,
    OfferGrants,
    ReadOnly,
    SyncAPI,
    _apages,
    _AsyncIdentifierRelation,
    _IdentifierRelation,
    _pages,
    item_path,
    tag_document,
)

# Classes below define a method named ``list``, which would shadow this name
# in their annotations.
_List = list


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


class ContactTags:
    """Tags on one contact (``/v1/contacts/{id}/relationships/tags``)."""

    def __init__(self, api: SyncAPI) -> None:
        self._relation = _IdentifierRelation(api, "contacts", "tags")

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
        return self._relation.list(
            contact_id,
            sort=sort,
            include=include,
            fields=fields,
            page=page,
            page_size=page_size,
            **filters,
        )

    iter = _pages(list)

    def add(self, contact_id: str, tag_ids: Ids) -> _List[ResourceIdentifier]:
        """Add tags to a contact."""
        return self._relation._change("POST", contact_id, tag_document(tag_ids))

    def remove(self, contact_id: str, tag_ids: Ids) -> _List[ResourceIdentifier]:
        """Remove tags from a contact."""
        return self._relation._change("DELETE", contact_id, tag_document(tag_ids))

    def replace(self, contact_id: str, tag_ids: Ids) -> _List[ResourceIdentifier]:
        """Replace a contact's tags with ``tag_ids``."""
        return self._relation._change("PATCH", contact_id, tag_document(tag_ids))


class AsyncContactTags:
    """Async twin of :class:`ContactTags`."""

    def __init__(self, api: AsyncAPI) -> None:
        self._relation = _AsyncIdentifierRelation(api, "contacts", "tags")

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
        """List a contact's tags. See :meth:`ContactTags.list`."""
        return await self._relation.list(
            contact_id,
            sort=sort,
            include=include,
            fields=fields,
            page=page,
            page_size=page_size,
            **filters,
        )

    iter = _apages(list)

    async def add(self, contact_id: str, tag_ids: Ids) -> _List[ResourceIdentifier]:
        return await self._relation._change("POST", contact_id, tag_document(tag_ids))

    async def remove(self, contact_id: str, tag_ids: Ids) -> _List[ResourceIdentifier]:
        return await self._relation._change("DELETE", contact_id, tag_document(tag_ids))

    async def replace(self, contact_id: str, tag_ids: Ids) -> _List[ResourceIdentifier]:
        return await self._relation._change("PATCH", contact_id, tag_document(tag_ids))


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

