"""Query-string encoding for JSON:API list requests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeAlias

# Values accepted by ``list(..., **filters)`` and by ``include`` / ``fields``.
FilterValue: TypeAlias = str | int | float | bool | Sequence[str] | Sequence[int] | None
Include: TypeAlias = str | Sequence[str]
Fields: TypeAlias = Mapping[str, str | Sequence[str]]


def _stringify(value: str | int | float | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def encode_query(
    *,
    sort: str | None = None,
    include: Include | None = None,
    fields: Fields | None = None,
    page: int | None = None,
    page_size: int | None = None,
    filters: Mapping[str, FilterValue] | None = None,
) -> list[tuple[str, str]]:
    """Build Kajabi query parameters.

    ``include`` may be a comma-separated string or a sequence (``["tags", "customer"]``).
    ``fields`` is a mapping of JSON:API type to field names, for example
    ``{"contacts": ["name", "email"]}``, sent as ``fields[contacts]=name,email``.
    Each filter keyword becomes ``filter[<name>]``. Sequences are repeated as
    ``filter[<name>][]``, which is how ``exclude_product_types`` is expressed.
    """
    params: list[tuple[str, str]] = []
    if sort:
        params.append(("sort", sort))
    if include:
        if isinstance(include, str):
            include_value = include
        else:
            include_value = ",".join(include)
        if include_value:
            params.append(("include", include_value))
    if fields:
        for resource_type, names in fields.items():
            if isinstance(names, str):
                value = names
            else:
                value = ",".join(names)
            if value:
                params.append((f"fields[{resource_type}]", value))
    if page is not None:
        params.append(("page[number]", str(page)))
    if page_size is not None:
        params.append(("page[size]", str(page_size)))
    for name, raw in (filters or {}).items():
        if raw is None:
            continue
        key = f"filter[{name}]"
        if isinstance(raw, (str, int, float, bool)):
            params.append((key, _stringify(raw)))
            continue
        for item in raw:
            params.append((f"{key}[]", _stringify(item)))
    return params


def merge_filters(
    filters: Mapping[str, FilterValue],
    /,
    **explicit: FilterValue,
) -> dict[str, FilterValue]:
    """Combine ``**filters`` with explicit keyword filters, dropping ``None``."""
    merged: dict[str, FilterValue] = {}
    merged.update(explicit)
    merged.update(filters)
    return {key: value for key, value in merged.items() if value is not None}
