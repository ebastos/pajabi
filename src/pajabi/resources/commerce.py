"""Customers, offers, payouts, and purchases."""

from __future__ import annotations

from pajabi._query import Fields, FilterValue, Include
from pajabi.models import Customer, Offer, Payout, Purchase, ResourceIdentifier
from pajabi.pagination import AsyncPage, Page
from pajabi.resources._common import (
    AsyncAPI,
    AsyncOfferGrants,
    AsyncReadOnly,
    OfferGrants,
    ReadOnly,
    SyncAPI,
    _apages,
    _AsyncIdentifierRelation,
    _IdentifierRelation,
    _pages,
    item_path,
)


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
        return _IdentifierRelation(self._api, "offers", "products").list(
            offer_id,
            sort=sort,
            include=include,
            fields=fields,
            page=page,
            page_size=page_size,
            **filters,
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
        return await _AsyncIdentifierRelation(self._api, "offers", "products").list(
            offer_id,
            sort=sort,
            include=include,
            fields=fields,
            page=page,
            page_size=page_size,
            **filters,
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
