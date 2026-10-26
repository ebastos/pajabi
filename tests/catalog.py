"""Every library call the request suite exercises, and the HTTP call it must make.

``path`` is the OpenAPI template. Ids used by the calls are ``1``, which the
request test substitutes for ``{id}``, ``{contact_id}``, ``{customer_id}``, and
``{offer_id}``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

READS: tuple[tuple[str, str], ...] = (
    ("blog_posts", "/v1/blog_posts"),
    ("contact_tags", "/v1/contact_tags"),
    ("courses", "/v1/courses"),
    ("custom_fields", "/v1/custom_fields"),
    ("form_submissions", "/v1/form_submissions"),
    ("landing_pages", "/v1/landing_pages"),
    ("order_items", "/v1/order_items"),
    ("orders", "/v1/orders"),
    ("podcasts", "/v1/podcasts"),
    ("products", "/v1/products"),
    ("sites", "/v1/sites"),
    ("transactions", "/v1/transactions"),
    ("website_pages", "/v1/website_pages"),
    ("offers", "/v1/offers"),
    ("purchases", "/v1/purchases"),
    ("contacts", "/v1/contacts"),
    ("contact_notes", "/v1/contact_notes"),
    ("customers", "/v1/customers"),
    ("forms", "/v1/forms"),
    ("hooks", "/v1/hooks"),
)

SAMPLE_EVENTS = (
    "tag_added",
    "tag_removed",
    "form_submission",
    "purchase",
    "payment_succeeded",
    "order_created",
)

CONTACT_CREATE = {
    "data": {
        "type": "contacts",
        "attributes": {"name": "Jane", "email": "jane@example.com"},
        "relationships": {"site": {"data": {"id": "123", "type": "sites"}}},
    }
}
CONTACT_UPDATE = {
    "data": {"id": "1", "type": "contacts", "attributes": {"name": "Janet"}},
    "relationships": {"tags": {"data": [{"id": "5", "type": "contact_tags"}]}},
}
NOTE_CREATE = {
    "data": {
        "type": "contact_notes",
        "attributes": {"body": "Called"},
        "relationships": {"contact": {"data": {"id": "7", "type": "contacts"}}},
    }
}
NOTE_UPDATE = {"data": {"id": "1", "type": "contact_notes", "attributes": {"body": "Updated"}}}
HOOK_CREATE = {
    "data": {
        "type": "hooks",
        "attributes": {"event": "purchase", "target_url": "https://example.com/hooks"},
        "relationships": {"site": {"data": {"id": "4", "type": "sites"}}},
    }
}
FORM_SUBMIT = {
    "data": {
        "type": "form_submissions",
        "attributes": {"name": "Jane", "email": "jane@example.com"},
    }
}
OFFER_IDS = {"data": [{"id": "9", "type": "offers"}]}
OFFER_IDS_QUIET = {
    "data": [{"id": "9", "type": "offers"}],
    "meta": {"send_customer_welcome_email": False},
}
TAG_IDS = {"data": [{"id": "5", "type": "contact_tags"}]}


@dataclass
class Case:
    name: str
    method: str
    path: str
    call: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    json_body: dict[str, Any] | None = None
    empty_body: bool = False
    query: dict[str, str] | None = None
    form: dict[str, str] | None = None
    auth: bool = True
    watch: str = "api"


def _read_cases() -> list[Case]:
    cases: list[Case] = []
    for attr, path in READS:
        cases.append(Case(f"{attr}.list", "GET", path, f"{attr}.list"))
        cases.append(Case(f"{attr}.iter", "GET", path, f"{attr}.iter"))
        cases.append(Case(f"{attr}.get", "GET", f"{path}/{{id}}", f"{attr}.get", args=("1",)))
    return cases


def _relation(
    name: str,
    method: str,
    path: str,
    call: str,
    args: tuple[Any, ...],
    json_body: dict[str, Any] | None = None,
    kwargs: dict[str, Any] | None = None,
) -> Case:
    return Case(
        name,
        method,
        path,
        call,
        args=args,
        kwargs=kwargs or {},
        json_body=json_body,
    )


def build_cases() -> list[Case]:
    offers = "/v1/contacts/{contact_id}/relationships/offers"
    tags = "/v1/contacts/{contact_id}/relationships/tags"
    customer_offers = "/v1/customers/{customer_id}/relationships/offers"
    cases = _read_cases()
    cases.extend(
        [
            Case(
                "contacts.create",
                "POST",
                "/v1/contacts",
                "contacts.create",
                kwargs={"site_id": "123", "name": "Jane", "email": "jane@example.com"},
                json_body=CONTACT_CREATE,
            ),
            Case(
                "contacts.update",
                "PATCH",
                "/v1/contacts/{id}",
                "contacts.update",
                args=("1",),
                kwargs={"name": "Janet", "tags": "5"},
                json_body=CONTACT_UPDATE,
            ),
            Case("contacts.delete", "DELETE", "/v1/contacts/{id}", "contacts.delete", args=("1",)),
            Case(
                "contact_notes.create",
                "POST",
                "/v1/contact_notes",
                "contact_notes.create",
                kwargs={"contact_id": "7", "body": "Called"},
                json_body=NOTE_CREATE,
            ),
            Case(
                "contact_notes.update",
                "PATCH",
                "/v1/contact_notes/{id}",
                "contact_notes.update",
                args=("1",),
                kwargs={"body": "Updated"},
                json_body=NOTE_UPDATE,
            ),
            Case(
                "contact_notes.delete",
                "DELETE",
                "/v1/contact_notes/{id}",
                "contact_notes.delete",
                args=("1",),
            ),
            _relation(
                "contacts.offers.list",
                "GET",
                offers,
                "contacts.offers.list",
                ("1",),
            ),
            _relation(
                "contacts.offers.iter",
                "GET",
                offers,
                "contacts.offers.iter",
                ("1",),
            ),
            _relation(
                "contacts.offers.grant",
                "POST",
                offers,
                "contacts.offers.grant",
                ("1", "9"),
                OFFER_IDS_QUIET,
                {"send_welcome_email": False},
            ),
            _relation(
                "contacts.offers.revoke",
                "DELETE",
                offers,
                "contacts.offers.revoke",
                ("1", "9"),
                OFFER_IDS,
            ),
            _relation(
                "contacts.offers.replace",
                "PATCH",
                offers,
                "contacts.offers.replace",
                ("1", "9"),
                OFFER_IDS,
            ),
            _relation(
                "contacts.tags.list",
                "GET",
                tags,
                "contacts.tags.list",
                ("1",),
            ),
            _relation(
                "contacts.tags.iter",
                "GET",
                tags,
                "contacts.tags.iter",
                ("1",),
            ),
            _relation(
                "contacts.tags.add",
                "POST",
                tags,
                "contacts.tags.add",
                ("1", "5"),
                TAG_IDS,
            ),
            _relation(
                "contacts.tags.remove",
                "DELETE",
                tags,
                "contacts.tags.remove",
                ("1", "5"),
                TAG_IDS,
            ),
            _relation(
                "contacts.tags.replace",
                "PATCH",
                tags,
                "contacts.tags.replace",
                ("1", "5"),
                TAG_IDS,
            ),
            _relation(
                "customers.offers.list",
                "GET",
                customer_offers,
                "customers.offers.list",
                ("1",),
            ),
            _relation(
                "customers.offers.iter",
                "GET",
                customer_offers,
                "customers.offers.iter",
                ("1",),
            ),
            _relation(
                "customers.offers.grant",
                "POST",
                customer_offers,
                "customers.offers.grant",
                ("1", "9"),
                OFFER_IDS,
            ),
            _relation(
                "customers.offers.revoke",
                "DELETE",
                customer_offers,
                "customers.offers.revoke",
                ("1", "9"),
                OFFER_IDS,
            ),
            _relation(
                "customers.offers.replace",
                "PATCH",
                customer_offers,
                "customers.offers.replace",
                ("1", "9"),
                OFFER_IDS,
            ),
            Case(
                "forms.submit",
                "POST",
                "/v1/forms/{id}/submit",
                "forms.submit",
                args=("1",),
                kwargs={"name": "Jane", "email": "jane@example.com"},
                json_body=FORM_SUBMIT,
            ),
            Case(
                "hooks.create",
                "POST",
                "/v1/hooks",
                "hooks.create",
                kwargs={
                    "site_id": "4",
                    "event": "purchase",
                    "target_url": "https://example.com/hooks",
                },
                json_body=HOOK_CREATE,
            ),
            Case("hooks.delete", "DELETE", "/v1/hooks/{id}", "hooks.delete", args=("1",)),
            Case(
                "offers.products",
                "GET",
                "/v1/offers/{offer_id}/relationships/products",
                "offers.products",
                args=("1",),
            ),
            Case(
                "payouts.list",
                "GET",
                "/v1/kajabi_payments_payouts",
                "payouts.list",
                kwargs={"site_id": "3"},
                query={"filter[site_id]": "3"},
            ),
            Case(
                "payouts.iter",
                "GET",
                "/v1/kajabi_payments_payouts",
                "payouts.iter",
                kwargs={"site_id": "3"},
                query={"filter[site_id]": "3"},
            ),
            Case(
                "payouts.get",
                "GET",
                "/v1/kajabi_payments_payouts/{id}",
                "payouts.get",
                args=("1",),
                kwargs={"site_id": "3"},
                query={"filter[site_id]": "3"},
            ),
            Case(
                "purchases.reactivate",
                "POST",
                "/v1/purchases/{id}/reactivate",
                "purchases.reactivate",
                args=("1",),
                empty_body=True,
            ),
            Case(
                "purchases.deactivate",
                "POST",
                "/v1/purchases/{id}/deactivate",
                "purchases.deactivate",
                args=("1",),
                empty_body=True,
            ),
            Case(
                "purchases.cancel_subscription",
                "POST",
                "/v1/purchases/{id}/cancel_subscription",
                "purchases.cancel_subscription",
                args=("1",),
                empty_body=True,
            ),
            Case("me", "GET", "/v1/me", "me"),
            Case("version", "GET", "/v1/version", "version", auth=False),
            Case(
                "oauth.token",
                "POST",
                "/v1/oauth/token",
                "sites.list",
                form={
                    "grant_type": "client_credentials",
                    "client_id": "id",
                    "client_secret": "secret",
                },
                auth=False,
                watch="token",
            ),
            Case(
                "oauth.revoke",
                "POST",
                "/v1/oauth/revoke",
                "revoke_token",
                form={"token": "access-1"},
            ),
        ]
    )
    for event in SAMPLE_EVENTS:
        cases.append(
            Case(
                f"hooks.sample.{event}",
                "GET",
                f"/v1/hooks/{event}_sample",
                "hooks.sample",
                args=(event,),
            )
        )
    return cases


CASES = build_cases()
