"""Typed Python client for the Kajabi Public API."""

from pajabi._version import __version__
from pajabi.client import AsyncKajabi, Kajabi
from pajabi.errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    KajabiError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from pajabi.pagination import AsyncPage, Page
from pajabi.resources import ContactAttributes, FormSubmissionAttributes

__all__ = [
    "APIConnectionError",
    "APIError",
    "APITimeoutError",
    "AsyncKajabi",
    "AsyncPage",
    "AuthenticationError",
    "BadRequestError",
    "ContactAttributes",
    "FormSubmissionAttributes",
    "InternalServerError",
    "Kajabi",
    "KajabiError",
    "NotFoundError",
    "Page",
    "PermissionDeniedError",
    "RateLimitError",
    "UnprocessableEntityError",
    "__version__",
]
