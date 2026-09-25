"""Verification of CRM -> product webhooks (``X-CRM-Signature``)."""

from __future__ import annotations

import hashlib
import hmac
import json

import pydantic

from .errors import ConfigError, SignatureError, ValidationError
from .models.events import EVENT_ADAPTER, CrmEvent

__all__ = ["SIGNATURE_HEADER", "compute_signature", "verify"]

SIGNATURE_HEADER = "X-CRM-Signature"


def _secret_bytes(secret: str | bytes) -> bytes:
    if not secret:
        raise ConfigError("webhook secret must not be empty")
    return secret.encode() if isinstance(secret, str) else bytes(secret)


def compute_signature(raw_body: bytes, secret: str | bytes) -> str:
    """Lowercase hex HMAC-SHA256 of the raw body bytes."""
    return hmac.new(_secret_bytes(secret), bytes(raw_body), hashlib.sha256).hexdigest()


def verify(raw_body: bytes, signature: str, secret: str | bytes) -> CrmEvent:
    """Check the signature over the exact received bytes and parse the event.

    Pass the body before any JSON decoding/re-encoding: the HMAC covers raw bytes.
    Raises ``SignatureError`` on a mismatch and ``ValidationError`` on a malformed event.
    """
    if not isinstance(raw_body, bytes | bytearray | memoryview):
        raise TypeError("raw_body must be bytes")
    expected = compute_signature(raw_body, secret)
    provided = (signature or "").strip().lower()
    if not provided or not hmac.compare_digest(expected.encode(), provided.encode()):
        raise SignatureError("webhook signature mismatch")

    try:
        data = json.loads(bytes(raw_body))
    except ValueError as exc:
        raise ValidationError("webhook body is not valid JSON") from exc
    try:
        return EVENT_ADAPTER.validate_python(data)
    except pydantic.ValidationError as exc:
        raise ValidationError(
            f"invalid webhook event: {exc.error_count()} error(s)",
            details=exc.errors(include_url=False, include_input=False),
        ) from exc
