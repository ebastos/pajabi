"""Models flatten JSON:API attributes and resolve included resources."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pajabi._parsing import parse_collection, parse_one, parse_version
from pajabi.models import (
    MODEL_TYPES,
    Contact,
    ContactTag,
    Course,
    CourseModule,
    Customer,
    Resource,
    ResourceIdentifier,
)

SPEC = Path(__file__).resolve().parents[1] / "spec" / "openapi.yaml"


def test_attributes_datetimes_includes_and_relationship_quirk() -> None:
    payload = {
        "data": {
            "id": 7,
            "type": "contacts",
            "attributes": {
                "name": "Jane",
                "email": "jane@example.com",
                "created_at": "2024-01-15T10:30:00Z",
            },
            "relationships": {
                "tags": {"data": [{"id": "5", "type": "contact_tags"}]},
                "offers": {"links": {"data": [{"id": "9", "type": "offers"}]}},
            },
        },
        "included": [
            {"id": "5", "type": "contact_tags", "attributes": {"name": "VIP"}},
        ],
    }
    contact = parse_one(payload, Contact)
    assert contact.id == "7"
    assert contact.email == "jane@example.com"
    assert contact.created_at == datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
    tags = contact.related("tags")
    assert isinstance(tags, list)
    assert isinstance(tags[0], ContactTag)
    assert tags[0].name == "VIP"
    offers = contact.related("offers")
    assert isinstance(offers, list)
    assert isinstance(offers[0], ResourceIdentifier)
    assert offers[0].id == "9"
    assert contact.relationship_ids("tags") == ["5"]
    assert contact.relationship_ids("offers") == ["9"]


def test_sparse_fieldset_leaves_attributes_empty() -> None:
    contact = parse_one({"data": {"id": "1", "type": "contacts"}}, Contact)
    assert contact.email is None
    assert contact.name is None


def test_unknown_attribute_is_kept() -> None:
    contact = parse_one(
        {"data": {"id": "1", "type": "contacts", "attributes": {"nickname": "JJ"}}},
        Contact,
    )
    assert contact.model_extra is not None
    assert contact.model_extra["nickname"] == "JJ"


def test_nested_included_and_version_typo() -> None:
    payload = {
        "data": {
            "id": "4",
            "type": "courses",
            "attributes": {"title": "Intro"},
            "relationships": {"modules": {"data": [{"id": "8", "type": "modules"}]}},
            "included": [
                {"id": "8", "type": "modules", "attributes": {"title": "Week 1", "position": 1}},
            ],
        }
    }
    course = parse_one(payload, Course)
    modules = course.related("modules")
    assert isinstance(modules, list)
    assert isinstance(modules[0], CourseModule)
    assert modules[0].title == "Week 1"
    assert modules[0].position == 1
    version = parse_version(
        {
            "meta": {"title": "Kajabi API", "version": "1.0"},
            "links": {"documentation": "https://developers.kajabi.com"},
            "jsonapi": {"version": "1.0", "specficiation": "https://jsonapi.org/format/1.0/"},
        }
    )
    assert version.version == "1.0"
    assert version.jsonapi_specification == "https://jsonapi.org/format/1.0/"


def test_customer_revenue_integer_from_the_spec_example() -> None:
    customer = parse_one(
        {"data": {"id": "1", "type": "customers", "attributes": {"net_revenue": 10000}}},
        Customer,
    )
    assert customer.net_revenue == "10000"


def test_spec_example_payloads_parse() -> None:
    text = SPEC.read_text()
    blocks = re.findall(r"```json\n(.*?)```", text, re.S)
    parsed = 0
    for block in blocks:
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or "data" not in payload:
            continue
        data = payload["data"]
        if isinstance(data, list):
            if data and isinstance(data[0], dict):
                resource_type = str(data[0].get("type") or "")
                parse_collection(payload, MODEL_TYPES.get(resource_type, Resource))
                parsed += 1
            continue
        if isinstance(data, dict):
            resource_type = str(data.get("type") or "")
            parse_one(payload, MODEL_TYPES.get(resource_type, Resource))
            parsed += 1
    assert parsed >= 100
