"""Customer plane client (``X-Customer-Assertion``, ``/api/v1/customer/...``)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from types import TracebackType
from typing import Any, Self

import httpx

from ._customer_api import AiApi, BillingApi, ReferralsApi
from ._http import DEFAULT_ATTEMPTS, DEFAULT_TIMEOUT, IDEMPOTENCY_HEADER, HttpTransport
from .assertion import AssertionSigner, is_canonical_customer_id, is_valid_actor
from .errors import ConfigError

__all__ = ["ASSERTION_HEADER", "CustomerClient"]

ASSERTION_HEADER = "X-Customer-Assertion"
BASE_PATH = "/api/v1/customer"
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class CustomerClient:
    """Client acting on behalf of one account and one actor buyer.

    Methods live in the ``billing``, ``ai`` and ``referrals`` namespaces.
    ``retries`` is the total number of attempts, including the first one.
    """

    def __init__(
        self,
        base_url: str,
        signer: AssertionSigner,
        account_public_id: str,
        actor_buyer_id: int,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_ATTEMPTS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not isinstance(signer, AssertionSigner):
            raise ConfigError("signer must be an AssertionSigner")
        if not is_canonical_customer_id(account_public_id):
            raise ConfigError("account_public_id must be a lowercase canonical UUID")
        if not is_valid_actor(actor_buyer_id):
            raise ConfigError("actor_buyer_id must be a positive int")
        self._signer = signer
        self.account_public_id = account_public_id
        self.actor_buyer_id = actor_buyer_id
        self._http = HttpTransport(
            base_url, timeout=timeout, max_attempts=retries, transport=transport
        )
        self.billing = BillingApi(self._request)
        self.ai = AiApi(self._request)
        self.referrals = ReferralsApi(self._request)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        scopes: Iterable[str],
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        idempotency_key: str | None = None,
    ) -> Any:
        method = method.upper()
        scope_list = list(scopes)
        headers: dict[str, str] = {}
        if method not in _READ_METHODS:
            # CRM requires Idempotency-Key on every write. The key stays fixed across the
            # SDK's own retries; pass it explicitly to deduplicate retries done by the caller.
            headers[IDEMPOTENCY_HEADER] = idempotency_key or str(uuid.uuid4())

        def assertion_header() -> dict[str, str]:
            token = self._signer.sign(self.account_public_id, scope_list, self.actor_buyer_id)
            return {ASSERTION_HEADER: token}

        return await self._http.request(
            method,
            BASE_PATH + path,
            params=params,
            json=json,
            headers=headers,
            header_factory=assertion_header,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
