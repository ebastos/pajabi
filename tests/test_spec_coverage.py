"""The operations the library calls are exactly the operations in the OpenAPI document."""

from __future__ import annotations

from pathlib import Path

import yaml

from tests.catalog import CASES

SPEC = Path(__file__).resolve().parents[1] / "spec" / "openapi.yaml"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def spec_operations() -> set[tuple[str, str]]:
    document = yaml.safe_load(SPEC.read_text())
    found: set[tuple[str, str]] = set()
    for path, item in document["paths"].items():
        for method, operation in item.items():
            if method in HTTP_METHODS and isinstance(operation, dict):
                found.add((method.upper(), path))
    return found


def test_every_spec_operation_is_called() -> None:
    exercised = {(case.method, case.path) for case in CASES}
    documented = spec_operations()
    assert exercised == documented
