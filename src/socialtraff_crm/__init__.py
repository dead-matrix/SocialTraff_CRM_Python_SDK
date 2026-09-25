"""Async Python SDK for SocialTraff CRM."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("socialtraff-crm-sdk")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0"

from . import webhooks
from .assertion import KNOWN_SCOPES, TOKEN_USE, AssertionSigner
from .customer import CustomerClient
from .errors import (
    ApiError,
    AuthError,
    ConfigError,
    HttpError,
    NotFoundError,
    SDKError,
    SignatureError,
    ValidationError,
)
from .models.events import CrmEvent, GenericEvent, NotifyEvent, PlanChangedEvent
from .service import ServiceClient

__all__ = [
    "KNOWN_SCOPES",
    "TOKEN_USE",
    "ApiError",
    "AssertionSigner",
    "AuthError",
    "ConfigError",
    "CrmEvent",
    "CustomerClient",
    "GenericEvent",
    "HttpError",
    "NotFoundError",
    "NotifyEvent",
    "PlanChangedEvent",
    "SDKError",
    "ServiceClient",
    "SignatureError",
    "ValidationError",
    "__version__",
    "webhooks",
]
