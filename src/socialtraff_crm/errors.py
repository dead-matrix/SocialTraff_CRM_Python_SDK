"""SDK exception hierarchy.

Every error raised by the SDK derives from :class:`SDKError`, so callers can catch one type.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ApiError",
    "AuthError",
    "ConfigError",
    "HttpError",
    "NotFoundError",
    "SDKError",
    "SignatureError",
    "ValidationError",
]


class SDKError(Exception):
    """Base class for all SDK errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(message={self.message!r}, "
            f"status_code={self.status_code!r}, code={self.code!r})"
        )


class ConfigError(SDKError):
    """Invalid client configuration (empty token, wrong key type, bad lifetime, ...)."""


class AuthError(SDKError):
    """CRM rejected the credentials (HTTP 401) or the action is forbidden (HTTP 403)."""


class ValidationError(SDKError):
    """HTTP 422 from CRM or client-side validation failure (including naive datetimes)."""


class NotFoundError(SDKError):
    """HTTP 404. ``code`` distinguishes ``not_found`` from ``feature_disabled``."""


class ApiError(SDKError):
    """Any other error envelope returned by CRM."""


class HttpError(SDKError):
    """Transport failure or a response that is not a JSON envelope."""


class SignatureError(SDKError):
    """Webhook signature is missing or does not match the body."""
