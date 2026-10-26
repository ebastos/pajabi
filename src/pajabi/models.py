"""Pydantic models for Kajabi JSON:API resources.

Attribute fields come from the OpenAPI ``*_attributes`` schemas. Every attribute
is optional because sparse fieldsets omit fields. ``extra="allow"`` keeps
attributes the spec does not list yet.

Date-time fields are the properties marked ``format: date-time`` or described as
ISO 8601 date-times. Other timestamp-like strings (``published_at``,
``fulfilled_at``, and similar) stay strings, matching the spec.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator


class ResourceIdentifier(BaseModel):
    """A JSON:API resource identifier (``id`` and ``type`` only)."""

    model_config = ConfigDict(extra="allow")

    id: str
    type: str = ""

    @field_validator("id", "type", mode="before")
    @classmethod
    def _stringify(cls, value: object) -> object:
        if value is None:
            return ""
        return str(value)


class Resource(BaseModel):
    """A JSON:API resource with its attributes flattened onto the model."""

    model_config = ConfigDict(extra="allow")

    id: str
    resource_type: str = ""
    relationships: dict[str, Any] = Field(default_factory=dict)
    links: dict[str, Any] = Field(default_factory=dict)
    _included: dict[tuple[str, str], Resource] = PrivateAttr(default_factory=dict)

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_id(cls, value: object) -> object:
        if value is None:
            return ""
        return str(value)

    def related(
        self, name: str
    ) -> Resource | ResourceIdentifier | list[Resource | ResourceIdentifier] | None:
        """Resolve a relationship to included models, or to identifiers.

        When the response was requested with ``include=``, matching objects from
        the ``included`` array are returned as models. Otherwise the raw
        identifiers are returned. A to-one relationship returns one value; a
        to-many relationship returns a list.
        """
        relationship = self.relationships.get(name)
        data = _relationship_data(relationship)
        if data is None:
            return None
        if isinstance(data, list):
            return [self._resolve(item) for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return self._resolve(data)
        return None

    def relationship_ids(self, name: str) -> list[str]:
        """Ids for a relationship, whether or not the resources were included."""
        related = self.related(name)
        if related is None:
            return []
        if isinstance(related, list):
            return [item.id for item in related]
        return [related.id]

    def _resolve(self, identifier: dict[str, Any]) -> Resource | ResourceIdentifier:
        resource_type = str(identifier.get("type") or "")
        resource_id = str(identifier.get("id") or "")
        found = self._included.get((resource_type, resource_id))
        if isinstance(found, Resource):
            return found
        return ResourceIdentifier(id=resource_id, type=resource_type)


def _relationship_data(relationship: Any) -> Any:
    """Return the identifier or identifier list for a relationship object.

    The spec's own contact example sometimes nests ``data`` under ``links``.
    The schema puts ``data`` on the relationship. Accept both.
    """
    if not isinstance(relationship, dict):
        return None
    if "data" in relationship:
        return relationship.get("data")
    links = relationship.get("links")
    if isinstance(links, dict) and isinstance(links.get("data"), list):
        return links.get("data")
    return None


class Socials(BaseModel):
    """Customer social profile links."""

    model_config = ConfigDict(extra="allow")

    twitter: str | None = None
    facebook: str | None = None
    instagram: str | None = None


class PodcastDirectory(BaseModel):
    """One podcast distribution directory."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    url: str | None = None
    config: dict[str, Any] | None = None


class PayoutTransaction(BaseModel):
    """A transaction nested in a Kajabi Payments payout."""

    model_config = ConfigDict(extra="allow")

    transaction_type: str | None = None
    pricing_type: str | None = None
    sales_tax: float | None = None
    amount: float | None = None
    currency: str | None = None
    fee: float | None = None
    net: float | None = None
    customer_id: int | str | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    offer_ids: list[int | str] | None = None
    offer_titles: list[str] | None = None
    provider: str | None = None
    payment_method: str | None = None
    created_at: datetime | None = None
    coupon_used: str | None = None
    presented_amount: float | None = None
    presented_currency: str | None = None
    exchange_rate: float | None = None
    quantity: int | None = None
    order_number: str | None = None


class BlogPost(Resource):
    """A blog post."""

    title: str | None = None
    url: str | None = None
    content: str | None = None
    slug: str | None = None
    page_title: str | None = None
    page_description: str | None = None
    published_at: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Contact(Resource):
    """A contact."""

    name: str | None = None
    email: str | None = None
    phone_number: str | None = None
    business_number: str | None = None
    subscribed: bool | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    address_city: str | None = None
    address_state: str | None = None
    address_country: str | None = None
    address_zip: str | None = None
    external_user_id: str | None = None
    custom_1: str | None = None
    custom_2: str | None = None
    custom_3: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ContactTag(Resource):
    """A tag that can be applied to contacts."""

    name: str | None = None


class ContactNote(Resource):
    """A note attached to a contact."""

    body: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CustomField(Resource):
    """A site custom field definition.

    ``type`` is the field's data type (the JSON:API resource type lives on
    ``resource_type``).
    """

    title: str | None = None
    handle: str | None = None
    type: str | None = None
    required: bool | None = None


class Customer(Resource):
    """A customer."""

    name: str | None = None
    email: str | None = None
    avatar: str | None = None
    external_user_id: str | None = None
    public_bio: str | None = None
    public_location: str | None = None
    public_website: str | None = None
    socials: Socials | None = None
    net_revenue: str | None = None
    sign_in_count: int | None = None
    last_request_at: datetime | None = None
    bounced_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("net_revenue", mode="before")
    @classmethod
    def _revenue_as_text(cls, value: object) -> object:
        # The schema says string. One spec example sends an integer.
        if isinstance(value, bool) or value is None or isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return str(value)
        return value


class FormField(Resource):
    """A field belonging to a form (JSON:API type ``fields``)."""

    title: str | None = None
    type: str | None = None
    required: bool | None = None
    handle: str | None = None
    select_options: str | None = None
    editable: bool | None = None


class Form(Resource):
    """A form."""

    title: str | None = None
    default: bool | None = None
    # The schema types this as an object. The documented examples send a URL string.
    webhook_url: dict[str, Any] | str | None = None
    url: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FormSubmission(Resource):
    """A form submission."""

    name: str | None = None
    email: str | None = None
    phone_number: str | None = None
    business_number: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    address_city: str | None = None
    address_state: str | None = None
    address_country: str | None = None
    address_zip: str | None = None
    custom_1: str | None = None
    custom_2: str | None = None
    custom_3: str | None = None


class Hook(Resource):
    """A webhook subscription (JSON:API type ``hooks``)."""

    event: str | None = None
    target_url: str | None = None
    resource_id: int | str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


Webhook = Hook


class LandingPage(Resource):
    """A landing page."""

    title: str | None = None
    url: str | None = None
    publish_at: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Offer(Resource):
    """An offer."""

    title: str | None = None
    description: str | None = None
    internal_title: str | None = None
    currency: str | None = None
    price_in_cents: int | None = None
    payment_type: str | None = None
    token: str | None = None
    payment_method: str | None = None
    price_description: str | None = None
    checkout_url: str | None = None
    recurring_offer: bool | None = None
    subscription: bool | None = None
    one_time: bool | None = None
    single: bool | None = None
    free: bool | None = None
    image_url: str | None = None


class Course(Resource):
    """A course."""

    title: str | None = None
    description: str | None = None
    thumbnail_url: str | None = None
    created_at: datetime | None = None


class CourseModule(Resource):
    """A module inside a course. Returned in ``included`` when requested."""

    title: str | None = None
    description: str | None = None
    position: str | int | None = None
    poster_image_url: str | None = None
    publishing_option: str | None = None


class CourseLesson(Resource):
    """A lesson inside a course. Returned in ``included`` when requested."""

    title: str | None = None
    position: str | int | None = None
    status: str | None = None
    publishing_option: str | None = None


class Media(Resource):
    """Media attached to a lesson. Returned in ``included`` when requested."""

    duration_in_minutes: float | None = None


class Order(Resource):
    """An order."""

    order_number: int | None = None
    currency_code: str | None = None
    fulfilled_at: str | None = None
    created_at: datetime | None = None
    total_price_in_cents: int | None = None
    subtotal_in_cents: int | None = None
    sales_tax_amount_in_cents: int | None = None
    discount_amount_in_cents: int | None = None
    formatted_total_price: str | None = None
    formatted_subtotal: str | None = None
    currency_symbol: str | None = None


class OrderItem(Resource):
    """A line item on an order."""

    quantity: int | None = None
    currency_code: str | None = None
    item_type: str | None = None
    item_id: int | None = None
    title: str | None = None
    fulfilled_at: str | None = None
    created_at: datetime | None = None
    total_price_in_cents: int | None = None
    subtotal_in_cents: int | None = None
    sales_tax_amount_in_cents: int | None = None
    discount_amount_in_cents: int | None = None
    formatted_total_price: str | None = None
    formatted_subtotal: str | None = None
    currency_symbol: str | None = None


class Product(Resource):
    """A product."""

    title: str | None = None
    description: str | None = None
    status: str | None = None
    members_aggregate_count: int | None = None
    product_type_name: str | None = None
    product_type_id: int | None = None
    publish_status: str | None = None
    thumbnail_url: str | None = None
    url: str | None = None
    created_at: datetime | None = None


class Purchase(Resource):
    """A purchase."""

    amount_in_cents: int | None = None
    payment_type: str | None = None
    multipay_payments_made: int | None = None
    opt_in: bool | None = None
    raw_extra_contact_information: dict[str, Any] | None = None
    currency: str | None = None
    effective_start_at: str | None = None
    cardholder_name: str | None = None
    billing_address_zip: str | None = None
    deactivated_at: str | None = None
    deactivation_reason: str | None = None
    coupon_code: str | None = None
    source: str | None = None
    referrer: str | None = None
    quantity: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Site(Resource):
    """A Kajabi site."""

    title: str | None = None
    subdomain: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Transaction(Resource):
    """A payment transaction."""

    action: str | None = None
    state: str | None = None
    payment_type: str | None = None
    amount_in_cents: int | None = None
    sales_tax_in_cents: int | None = None
    currency: str | None = None
    currency_symbol: str | None = None
    formatted_amount: str | None = None
    created_at: datetime | None = None


class WebsitePage(Resource):
    """A page on a Kajabi website."""

    title: str | None = None
    url: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Podcast(Resource):
    """A podcast."""

    title: str | None = None
    description: str | None = None
    language: str | None = None
    owner_email: str | None = None
    author: str | None = None
    status: str | None = None
    show_type: str | None = None
    thumbnail_url: str | None = None
    cover_art_url: str | None = None
    categories: list[str] | None = None
    directories: list[PodcastDirectory] | None = None
    migrated_to_url: str | None = None
    migrated: bool | None = None
    public: bool | None = None
    ready: bool | None = None
    distribution_ready: bool | None = None
    url: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Payout(Resource):
    """A Kajabi Payments payout (JSON:API type ``kajabi_payments_payouts``)."""

    status: str | None = None
    amount: float | None = None
    currency: str | None = None
    initiated_date: datetime | None = None
    estimated_arrival_date: datetime | None = None
    bank_account: str | None = None
    transactions: list[PayoutTransaction] | None = None


class User(Resource):
    """The authenticated user returned by ``GET /v1/me``."""

    initials: str | None = None
    name: str | None = None
    email: str | None = None
    role_level: str | None = None


class Version(BaseModel):
    """Response from ``GET /v1/version``.

    The spec spells the JSON:API spec link ``specficiation``. Both that key and
    ``specification`` are accepted.
    """

    model_config = ConfigDict(extra="allow")

    title: str | None = None
    version: str | None = None
    documentation: str | None = None
    jsonapi_version: str | None = None
    jsonapi_specification: str | None = None


MODEL_TYPES: dict[str, type[Resource]] = {
    "blog_posts": BlogPost,
    "contacts": Contact,
    "contact_tags": ContactTag,
    "contact_notes": ContactNote,
    "custom_fields": CustomField,
    "customers": Customer,
    "fields": FormField,
    "forms": Form,
    "form_submissions": FormSubmission,
    "hooks": Hook,
    "landing_pages": LandingPage,
    "offers": Offer,
    "courses": Course,
    "modules": CourseModule,
    "lessons": CourseLesson,
    "media": Media,
    "orders": Order,
    "order_items": OrderItem,
    "products": Product,
    "purchases": Purchase,
    "sites": Site,
    "transactions": Transaction,
    "website_pages": WebsitePage,
    "podcasts": Podcast,
    "kajabi_payments_payouts": Payout,
    "users": User,
}
