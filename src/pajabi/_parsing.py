"""Turn JSON:API documents into models and pages."""

from __future__ import annotations

from typing import Any, TypeVar, cast

from pajabi.models import MODEL_TYPES, Resource, ResourceIdentifier, Version
from pajabi.pagination import PageLinks, PageMeta

T = TypeVar("T", bound=Resource)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    return {}


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _link(value: Any) -> str | None:
    """A link may be a URL string or a JSON:API link object with ``href``."""
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        return _optional_str(value.get("href"))
    return None


def parse_meta(payload: dict[str, Any]) -> PageMeta:
    """Read ``meta``, including the payout list's alternate shape."""
    raw = _mapping(payload.get("meta"))
    if not raw:
        return PageMeta()
    total_count = _optional_int(raw.get("total_count"))
    if total_count is None:
        total_count = _optional_int(raw.get("total"))
    total_pages = _optional_int(raw.get("total_pages"))
    current_page = _optional_int(raw.get("current_page"))
    pagination = _mapping(raw.get("pagination"))
    if current_page is None:
        current_page = _optional_int(pagination.get("current"))
    if total_pages is None:
        total_pages = _optional_int(pagination.get("last"))
    return PageMeta(
        total_count=total_count,
        total_pages=total_pages,
        current_page=current_page,
    )


def parse_links(payload: dict[str, Any]) -> PageLinks:
    raw = _mapping(payload.get("links"))

    def link(name: str) -> str | None:
        return _link(raw.get(name))

    return PageLinks(
        self_link=link("self"),
        first=link("first"),
        prev=link("prev"),
        next=link("next"),
        last=link("last"),
        current=link("current"),
    )


def parse_resource(
    data: dict[str, Any],
    included: dict[tuple[str, str], Resource],
    model: type[T] | None = None,
) -> T:
    """Flatten one resource object into ``model`` (or the type registered for ``data.type``)."""
    resource_type = str(data.get("type") or "")
    model_type: type[Resource] = model or MODEL_TYPES.get(resource_type, Resource)
    attributes = data.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    raw_id = data.get("id")
    values: dict[str, Any] = dict(attributes)
    values["id"] = "" if raw_id is None else raw_id
    values["resource_type"] = resource_type
    obj = model_type.model_validate(values)
    relationships = data.get("relationships")
    obj.relationships = relationships if isinstance(relationships, dict) else {}
    links = data.get("links")
    obj.links = links if isinstance(links, dict) else {}
    obj._included = included
    return cast(T, obj)


def index_included(payload: dict[str, Any]) -> dict[tuple[str, str], Resource]:
    """Index the document's ``included`` array by ``(type, id)``.

    One course example in the spec nests ``included`` inside ``data``. The
    schema places it at the top of the document. Both are indexed.
    """
    raw_items: list[Any] = []
    included = payload.get("included")
    if isinstance(included, list):
        raw_items.extend(included)
    data = payload.get("data")
    if isinstance(data, dict):
        nested = data.get("included")
        if isinstance(nested, list):
            raw_items.extend(nested)
    parsed: list[Resource] = [
        parse_resource(item, {})
        for item in raw_items
        if isinstance(item, dict) and item.get("id") is not None
    ]
    mapping = {(item.resource_type, item.id): item for item in parsed}
    for item in parsed:
        item._included = mapping
    return mapping


def parse_one(payload: Any, model: type[T]) -> T:
    """Parse a single-resource document into ``model``."""
    from pajabi.errors import KajabiError

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise KajabiError("Expected a JSON:API resource document.")
    document = cast(dict[str, Any], payload)
    included = index_included(document)
    return parse_resource(cast(dict[str, Any], document["data"]), included, model)


def parse_collection(payload: Any, model: type[T]) -> tuple[list[T], PageMeta, PageLinks]:
    """Parse a collection document. A missing ``data`` array becomes an empty page."""
    if not isinstance(payload, dict):
        return [], PageMeta(), PageLinks()
    document = cast(dict[str, Any], payload)
    included = index_included(document)
    data = document.get("data")
    items: list[T] = []
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                items.append(parse_resource(entry, included, model))
    return items, parse_meta(document), parse_links(document)


def parse_identifiers(payload: Any) -> tuple[list[ResourceIdentifier], PageMeta, PageLinks]:
    """Parse a relationship document, which is a list of resource identifiers."""
    if not isinstance(payload, dict):
        return [], PageMeta(), PageLinks()
    document = cast(dict[str, Any], payload)
    data = document.get("data")
    items: list[ResourceIdentifier] = []
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and entry.get("id") is not None:
                items.append(
                    ResourceIdentifier(
                        id=str(entry.get("id")),
                        type=str(entry.get("type") or ""),
                    )
                )
    return items, parse_meta(document), parse_links(document)


def parse_version(payload: Any) -> Version:
    if not isinstance(payload, dict):
        return Version()
    meta = _mapping(payload.get("meta"))
    links = _mapping(payload.get("links"))
    jsonapi = _mapping(payload.get("jsonapi"))
    specification = jsonapi.get("specficiation")
    if not isinstance(specification, str):
        specification = jsonapi.get("specification")
    return Version(
        title=_optional_str(meta.get("title")),
        version=_optional_str(meta.get("version")),
        documentation=_optional_str(links.get("documentation")),
        jsonapi_version=_optional_str(jsonapi.get("version")),
        jsonapi_specification=specification if isinstance(specification, str) else None,
    )
