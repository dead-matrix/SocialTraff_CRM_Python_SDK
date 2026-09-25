from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from socialtraff_crm import (
    ApiError,
    AuthError,
    ConfigError,
    HttpError,
    NotFoundError,
    SDKError,
    ServiceClient,
    ValidationError,
)
from socialtraff_crm._http import RETRY_AFTER_MAX

BASE_URL = "http://crm.test"
TOKEN = "service-secret"

Handler = Callable[[httpx.Request], httpx.Response]


def make_client(handler: Handler, **kwargs) -> ServiceClient:
    return ServiceClient(BASE_URL, TOKEN, transport=httpx.MockTransport(handler), **kwargs)


def error_body(message: str, code: str) -> dict:
    return {"status": "error", "data": None, "message": message, "code": code}


class Recorder:
    """MockTransport handler that replays queued responses and records requests."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        if isinstance(item, Exception):
            raise item
        return item


async def test_success_envelope_returns_data_and_sends_service_token() -> None:
    rec = Recorder(httpx.Response(200, json={"status": "success", "data": {"plan": "pro"}}))
    async with make_client(rec) as client:
        data = await client._request("GET", "/plans/7")
    assert data == {"plan": "pro"}
    request = rec.requests[0]
    assert request.url == httpx.URL(f"{BASE_URL}/api/internal/plans/7")
    assert request.headers["X-Service-Token"] == TOKEN
    assert request.headers["User-Agent"].startswith("socialtraff-crm-sdk/")


async def test_success_envelope_with_null_data() -> None:
    rec = Recorder(httpx.Response(200, json={"status": "success", "data": None}))
    async with make_client(rec) as client:
        assert await client._request("DELETE", "/identity/accounts/1/members/2") is None


@pytest.mark.parametrize(
    ("status", "code", "error_cls"),
    [
        (401, "unauthorized", AuthError),
        (403, "forbidden", AuthError),
        (404, "not_found", NotFoundError),
        (404, "feature_disabled", NotFoundError),
        (422, "validation_error", ValidationError),
        (409, "conflict", ApiError),
        (500, "internal_error", ApiError),
    ],
)
async def test_error_envelope_mapping(status: int, code: str, error_cls: type[SDKError]) -> None:
    rec = Recorder(httpx.Response(status, json=error_body("boom", code)))
    async with make_client(rec) as client:
        with pytest.raises(error_cls) as info:
            await client._request("GET", "/plans/1")
    assert info.value.status_code == status
    assert info.value.code == code
    assert "boom" in info.value.message
    assert len(rec.requests) == 1


async def test_error_envelope_with_success_status_is_api_error() -> None:
    rec = Recorder(httpx.Response(200, json=error_body("weird", "odd")))
    async with make_client(rec) as client:
        with pytest.raises(ApiError) as info:
            await client._request("GET", "/plans/1")
    assert info.value.code == "odd"


async def test_non_json_response_is_http_error() -> None:
    rec = Recorder(httpx.Response(502, text="<html>Bad Gateway</html>"))
    async with make_client(rec, retries=1) as client:
        with pytest.raises(HttpError) as info:
            await client._request("GET", "/plans/1")
    assert info.value.status_code == 502


async def test_success_without_envelope_is_http_error() -> None:
    rec = Recorder(httpx.Response(200, json={"plan": "pro"}))
    async with make_client(rec) as client:
        with pytest.raises(HttpError):
            await client._request("GET", "/plans/1")


async def test_transport_error_is_http_error_after_retries() -> None:
    rec = Recorder(httpx.ConnectError("refused"))
    async with make_client(rec) as client:
        with pytest.raises(HttpError):
            await client._request("GET", "/plans/1")
    assert len(rec.requests) == 3


async def test_get_retried_on_503_then_succeeds(sleeps: list[float]) -> None:
    rec = Recorder(
        httpx.Response(503, json=error_body("down", "unavailable")),
        httpx.Response(503, json=error_body("down", "unavailable")),
        httpx.Response(200, json={"status": "success", "data": 1}),
    )
    async with make_client(rec) as client:
        assert await client._request("GET", "/plans/1") == 1
    assert len(rec.requests) == 3
    assert len(sleeps) == 2
    assert all(delay > 0 for delay in sleeps)


async def test_get_gives_up_after_three_attempts() -> None:
    rec = Recorder(httpx.Response(503, json=error_body("down", "unavailable")))
    async with make_client(rec) as client:
        with pytest.raises(ApiError) as info:
            await client._request("GET", "/plans/1")
    assert info.value.status_code == 503
    assert len(rec.requests) == 3


async def test_post_with_idempotency_key_is_retried() -> None:
    rec = Recorder(
        httpx.Response(502, json=error_body("gw", "bad_gateway")),
        httpx.Response(200, json={"status": "success", "data": {"ok": True}}),
    )
    async with make_client(rec) as client:
        data = await client._request(
            "POST", "/ai/key/ensure", json={"account_id": 1}, idempotency_key="k-1"
        )
    assert data == {"ok": True}
    assert len(rec.requests) == 2
    assert {r.headers["Idempotency-Key"] for r in rec.requests} == {"k-1"}
    assert json.loads(rec.requests[1].content) == {"account_id": 1}


async def test_post_without_idempotency_key_is_not_retried_on_503() -> None:
    rec = Recorder(httpx.Response(503, json=error_body("down", "unavailable")))
    async with make_client(rec) as client:
        with pytest.raises(ApiError):
            await client._request("POST", "/ai/key/ensure", json={"account_id": 1})
    assert len(rec.requests) == 1


async def test_post_without_idempotency_key_is_not_retried_on_network_error() -> None:
    rec = Recorder(httpx.ReadTimeout("slow"))
    async with make_client(rec) as client:
        with pytest.raises(HttpError):
            await client._request("POST", "/ai/key/ensure", json={"account_id": 1})
    assert len(rec.requests) == 1


async def test_client_errors_are_not_retried() -> None:
    rec = Recorder(httpx.Response(400, json=error_body("bad", "bad_request")))
    async with make_client(rec) as client:
        with pytest.raises(ApiError):
            await client._request("GET", "/plans/1")
    assert len(rec.requests) == 1


async def test_retry_after_is_respected_and_capped(sleeps: list[float]) -> None:
    rec = Recorder(
        httpx.Response(429, headers={"Retry-After": "2"}, json=error_body("slow", "rate")),
        httpx.Response(429, headers={"Retry-After": "3600"}, json=error_body("slow", "rate")),
        httpx.Response(200, json={"status": "success", "data": None}),
    )
    async with make_client(rec) as client:
        await client._request("PUT", "/identity/buyers/5", json={"tg_id": 1})
    assert sleeps == [2.0, RETRY_AFTER_MAX]


def test_config_errors() -> None:
    with pytest.raises(ConfigError):
        ServiceClient(BASE_URL, "")
    with pytest.raises(ConfigError):
        ServiceClient("", TOKEN)
    with pytest.raises(ConfigError):
        ServiceClient(BASE_URL, TOKEN, retries=0)
