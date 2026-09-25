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
    "AssertionSigner",
]

DEFAULT_ISSUER = "socialtraff-bosslink"
DEFAULT_AUDIENCE = "socialtraff-crm"
# CRM rejects assertions that live longer than this.
MAX_LIFETIME_SECONDS = 120
KNOWN_SCOPES = frozenset(
    {"billing:read", "billing:write", "ai:read", "referrals:read", "referrals:write"}
)


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
        if not isinstance(sub, str) or not sub:
            raise ValidationError("sub (public_customer_id) must be a non-empty string")
        if isinstance(actor_buyer_id, bool) or not isinstance(actor_buyer_id, int):
            raise ValidationError("actor_buyer_id must be an int")
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
        }
        return jwt.encode(claims, self._key, algorithm="EdDSA", headers={"kid": self.kid})
