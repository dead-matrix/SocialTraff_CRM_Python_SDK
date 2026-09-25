"""Customer assertion (Ed25519 JWT) issued by the product for the CRM customer plane."""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterable

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .errors import ConfigError, ValidationError

__all__ = [
    "DEFAULT_AUDIENCE",
    "DEFAULT_ISSUER",
    "KNOWN_SCOPES",
    "MAX_LIFETIME_SECONDS",
    "TOKEN_USE",
    "AssertionSigner",
    "is_canonical_customer_id",
    "is_valid_actor",
]

DEFAULT_ISSUER = "socialtraff-bosslink"
DEFAULT_AUDIENCE = "socialtraff-crm"
# CRM rejects assertions that live longer than this.
MAX_LIFETIME_SECONDS = 120
KNOWN_SCOPES = frozenset(
    {"billing:read", "billing:write", "ai:read", "referrals:read", "referrals:write"}
)
# CRM rejects a token without this claim (token_use_mismatch): it keeps the customer
# assertion apart from any other JWT that could be signed with the same key.
TOKEN_USE = "customer_assertion"
_ACT_MAX = 2**63 - 1


def is_canonical_customer_id(value: object) -> bool:
    """True for a lowercase hyphenated non-nil UUID, the only ``sub`` form CRM accepts.

    CRM compares ``public_customer_id`` as a string, so braces, ``urn:uuid:`` or upper case
    would parse to the same UUID yet name a different customer; CRM rejects them outright.
    """
    if not isinstance(value, str) or len(value) != 36 or value != value.lower():
        return False
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return str(parsed) == value and parsed.int != 0


def is_valid_actor(value: object) -> bool:
    """True for a positive ``buyer_id``; ``bool`` is rejected although it subclasses ``int``."""
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= _ACT_MAX


class AssertionSigner:
    """Signs a fresh short-lived assertion for every customer-plane request."""

    def __init__(
        self,
        private_key_pem: str | bytes,
        kid: str,
        issuer: str = DEFAULT_ISSUER,
        audience: str = DEFAULT_AUDIENCE,
        lifetime_seconds: int = 60,
    ) -> None:
        if not kid:
            raise ConfigError("kid must not be empty")
        if not issuer or not audience:
            raise ConfigError("issuer and audience must not be empty")
        if not 0 < lifetime_seconds <= MAX_LIFETIME_SECONDS:
            raise ConfigError(f"lifetime_seconds must be in 1..{MAX_LIFETIME_SECONDS}")
        pem = private_key_pem.encode() if isinstance(private_key_pem, str) else private_key_pem
        try:
            key = serialization.load_pem_private_key(pem, password=None)
        except (ValueError, TypeError) as exc:
            raise ConfigError("private_key_pem is not a valid unencrypted PEM key") from exc
        if not isinstance(key, Ed25519PrivateKey):
            raise ConfigError("private_key_pem must be an Ed25519 private key")
        self._key = key
        self.kid = kid
        self.issuer = issuer
        self.audience = audience
        self.lifetime_seconds = lifetime_seconds

    def sign(self, sub: str, scopes: Iterable[str], actor_buyer_id: int) -> str:
        """Return a compact JWS for account ``sub`` (``public_customer_id``) and actor buyer."""
        if not is_canonical_customer_id(sub):
            raise ValidationError("sub (public_customer_id) must be a lowercase canonical UUID")
        if not is_valid_actor(actor_buyer_id):
            raise ValidationError("actor_buyer_id must be a positive int")
        scope_list: list[str] = []
        for scope in scopes:
            if not isinstance(scope, str) or not scope or any(ch.isspace() for ch in scope):
                raise ValidationError(f"invalid scope: {scope!r}")
            if scope not in scope_list:
                scope_list.append(scope)
        if not scope_list:
            raise ValidationError("at least one scope is required")

        now = int(time.time())
        claims = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": sub,
            "iat": now,
            "exp": now + self.lifetime_seconds,
            "jti": uuid.uuid4().hex,
            "scope": " ".join(scope_list),
            "act": actor_buyer_id,
            "token_use": TOKEN_USE,
        }
        return jwt.encode(claims, self._key, algorithm="EdDSA", headers={"kid": self.kid})
