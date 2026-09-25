"""Service plane client (``X-Service-Token``, ``/api/internal/...``)."""

from __future__ import annotations

from collections.abc import Mapping
from types import TracebackType
from typing import Any, Self

import httpx

from ._http import DEFAULT_ATTEMPTS, DEFAULT_TIMEOUT, IDEMPOTENCY_HEADER, HttpTransport
from ._service_api import CatalogApi, IdentityApi, PlansApi, ServiceAiApi
from .errors import ConfigError

__all__ = ["SERVICE_TOKEN_HEADER", "ServiceClient"]

SERVICE_TOKEN_HEADER = "X-Service-Token"
BASE_PATH = "/api/internal"


class ServiceClient:
    """Product backend -> CRM client.

    Methods live in the ``identity``, ``plans``, ``catalog`` and ``ai`` namespaces.
    ``retries`` is the total number of attempts, including the first one.
    """

    def __init__(
        self,
        base_url: str,
        service_token: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_ATTEMPTS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not service_token:
            raise ConfigError("service_token must not be empty")
        self._http = HttpTransport(
            base_url,
            headers={SERVICE_TOKEN_HEADER: service_token},
            timeout=timeout,
            max_attempts=retries,
            transport=transport,
        )
        self.identity = IdentityApi(self._request)
        self.plans = PlansApi(self._request)
        self.catalog = CatalogApi(self._request)
        self.ai = ServiceAiApi(self._request)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        idempotency_key: str | None = None,
    ) -> Any:
        headers = {IDEMPOTENCY_HEADER: idempotency_key} if idempotency_key else None
        return await self._http.request(
            method, BASE_PATH + path, params=params, json=json, headers=headers
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
