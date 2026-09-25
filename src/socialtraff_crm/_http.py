"""Async HTTP transport: envelope decoding, error mapping and retries."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from .errors import (
    ApiError,
    AuthError,
    ConfigError,
    HttpError,
    NotFoundError,
    SDKError,
    ValidationError,
)

__all__ = ["IDEMPOTENCY_HEADER", "RETRY_STATUSES", "HttpTransport"]

IDEMPOTENCY_HEADER = "Idempotency-Key"
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
RETRY_STATUSES = frozenset({429, 502, 503, 504})

DEFAULT_TIMEOUT = 10.0
DEFAULT_ATTEMPTS = 3
BACKOFF_BASE = 0.5
BACKOFF_MAX = 8.0
RETRY_AFTER_MAX = 30.0

HeaderFactory = Callable[[], Mapping[str, str]]


def _user_agent() -> str:
    from . import __version__

    return f"socialtraff-crm-sdk/{__version__}"


async def _sleep(delay: float) -> None:
    # Module-level indirection so tests can replace the wait without patching asyncio globally.
    await asyncio.sleep(delay)


def _has_idempotency_key(headers: Mapping[str, str]) -> bool:
    target = IDEMPOTENCY_HEADER.lower()
    return any(name.lower() == target and value for name, value in headers.items())


def _is_retryable(method: str, headers: Mapping[str, str]) -> bool:
    if method in IDEMPOTENT_METHODS:
        return True
    # A POST is safe to repeat only when CRM can deduplicate it by Idempotency-Key.
    return method == "POST" and _has_idempotency_key(headers)


def _backoff(attempt: int) -> float:
    ceiling = min(BACKOFF_MAX, BACKOFF_BASE * (2 ** (attempt - 1)))
    return ceiling * random.uniform(0.5, 1.0)


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    try:
        seconds = float(raw)
    except ValueError:
        try:
            moment = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        seconds = (moment - datetime.now(UTC)).total_seconds()
    return min(max(seconds, 0.0), RETRY_AFTER_MAX)


def _error_class(status_code: int) -> type[SDKError]:
    if status_code in (401, 403):
        return AuthError
    if status_code == 404:
        return NotFoundError
    if status_code == 422:
        return ValidationError
    return ApiError


def decode_response(response: httpx.Response) -> Any:
    """Return ``data`` from a success envelope or raise the matching SDK error."""
    status = response.status_code
    is_success = 200 <= status < 300
    label = f"{response.request.method} {response.request.url.path}"

    if not response.content:
        if is_success:
            return None
        raise HttpError(f"{label}: HTTP {status} with empty body", status_code=status)

    try:
        body = response.json()
    except ValueError as exc:
        raise HttpError(
            f"{label}: HTTP {status}, response is not JSON", status_code=status
        ) from exc

    if not isinstance(body, dict):
        raise HttpError(f"{label}: HTTP {status}, unexpected response format", status_code=status)

    envelope_status = body.get("status")
    if is_success and envelope_status == "success":
        return body.get("data")
    if is_success and envelope_status != "error":
        raise HttpError(f"{label}: HTTP {status}, response is not an envelope", status_code=status)

    message = body.get("message") or body.get("detail") or f"HTTP {status}"
    if not isinstance(message, str):
        message = str(message)
    code = body.get("code")
    error_cls = ApiError if is_success else _error_class(status)
    raise error_cls(
        f"{label}: {message}",
        status_code=status,
        code=code if isinstance(code, str) else None,
        details=body.get("data") if body.get("data") is not None else body.get("detail"),
    )


class HttpTransport:
    """Thin wrapper over ``httpx.AsyncClient`` shared by the service and customer clients."""

    def __init__(
        self,
        base_url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_attempts: int = DEFAULT_ATTEMPTS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url or not base_url.strip():
            raise ConfigError("base_url must not be empty")
        if max_attempts < 1:
            raise ConfigError("retries must be >= 1 (total number of attempts)")
        self._max_attempts = max_attempts
        default_headers = {"User-Agent": _user_agent(), "Accept": "application/json"}
        default_headers.update(headers or {})
        self._client = httpx.AsyncClient(
            base_url=base_url.strip().rstrip("/"),
            headers=default_headers,
            timeout=timeout,
            transport=transport,
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        header_factory: HeaderFactory | None = None,
    ) -> Any:
        """Send a request and return envelope ``data``.

        ``header_factory`` is called before every attempt, so short-lived credentials
        (customer assertions) are re-issued on retries instead of being replayed.
        """
        method = method.upper()
        base_headers = dict(headers or {})
        retryable = _is_retryable(method, base_headers)
        attempt = 0
        while True:
            attempt += 1
            send_headers = dict(base_headers)
            if header_factory is not None:
                send_headers.update(header_factory())
            can_retry = retryable and attempt < self._max_attempts
            try:
                response = await self._client.request(
                    method, path, params=params, json=json, headers=send_headers
                )
            except httpx.TransportError as exc:
                if can_retry:
                    await _sleep(_backoff(attempt))
                    continue
                raise HttpError(f"{method} {path}: transport error: {exc!r}") from exc

            if can_retry and response.status_code in RETRY_STATUSES:
                delay = _retry_after(response)
                await _sleep(_backoff(attempt) if delay is None else delay)
                continue
            return decode_response(response)

    async def aclose(self) -> None:
        await self._client.aclose()
