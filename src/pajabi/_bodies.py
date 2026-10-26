"""JSON:API request bodies."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def identifier(resource_id: str, resource_type: str) -> dict[str, str]:
    return {"id": str(resource_id), "type": resource_type}


def to_one(resource_id: str, resource_type: str) -> dict[str, Any]:
    return {"data": identifier(resource_id, resource_type)}


def resource_document(
    *,
    resource_type: str,
    attributes: Mapping[str, Any],
    resource_id: str | None = None,
    relationships: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"type": resource_type, "attributes": dict(attributes)}
    if resource_id is not None:
        data["id"] = str(resource_id)
        # JSON:API update documents put id before type. Keep id first for stable bodies.
        data = {"id": data["id"], "type": resource_type, "attributes": dict(attributes)}
    if relationships:
        data["relationships"] = dict(relationships)
    return {"data": data}


def identifiers_document(
    ids: Sequence[str],
    resource_type: str,
    *,
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"data": [identifier(resource_id, resource_type) for resource_id in ids]}
    if meta:
        body["meta"] = dict(meta)
    return body


def one_or_many(values: str | int | Sequence[str | int]) -> list[str]:
    """Accept one id or a sequence of ids. Strings are not treated as sequences of characters."""
    if isinstance(values, str):
        return [values]
    if isinstance(values, bool):
        raise TypeError("Resource ids must be strings or integers.")
    if isinstance(values, int):
        return [str(values)]
    return [str(value) for value in values]
