"""Resource namespaces shared by the sync and async clients."""

from pajabi.resources._common import AsyncReadOnly, ReadOnly
from pajabi.resources.commerce import (
    AsyncCustomers,
    AsyncOffers,
    AsyncPayouts,
    AsyncPurchases,
    Customers,
    Offers,
    Payouts,
    Purchases,
)
from pajabi.resources.contacts import (
    AsyncContactNotes,
    AsyncContacts,
    ContactAttributes,
    ContactNotes,
    Contacts,
)
from pajabi.resources.content import (
    AsyncForms,
    AsyncHooks,
    Forms,
    FormSubmissionAttributes,
    Hooks,
)

__all__ = [
    "AsyncContactNotes",
    "AsyncContacts",
    "AsyncCustomers",
    "AsyncForms",
    "AsyncHooks",
    "AsyncOffers",
    "AsyncPayouts",
    "AsyncPurchases",
    "AsyncReadOnly",
    "ContactAttributes",
    "ContactNotes",
    "Contacts",
    "Customers",
    "FormSubmissionAttributes",
    "Forms",
    "Hooks",
    "Offers",
    "Payouts",
    "Purchases",
    "ReadOnly",
]
