from __future__ import annotations

import httpx
import jwt
import pytest

from socialtraff_crm import AssertionSigner, AuthError, ConfigError, CustomerClient

BASE_URL = "http://crm.test"
ACCOUNT = "3f2b8c1e-8f4a-4d0b-9a57-0c7e6f1d2a90"


def ok(data: object = None) -> httpx.Response:
    return httpx.Response(200, json={"status": "success", "data": data})


def make_client(private_pem: bytes, responses: list[httpx.Response], seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses.pop(0)

    signer = AssertionSigner(private_pem, kid="k1")
    return CustomerClient(BASE_URL, signer, ACCOUNT, 42, transport=httpx.MockTransport(handler))


async def test_get_sends_fresh_assertion_without_idempotency_key(
    ed25519_keys: tuple[bytes, bytes],
) -> None:
    private_pem, public_pem = ed25519_keys
    seen: list[httpx.Request] = []
    async with make_client(private_pem, [ok({"x": 1})], seen) as client:
        data = await client._request("GET", "/billing/subscription", scopes=["billing:read"])
    assert data == {"x": 1}
    request = seen[0]
    assert request.url == httpx.URL(f"{BASE_URL}/api/v1/customer/billing/subscription")
    assert "Idempotency-Key" not in request.headers
    claims = jwt.decode(
        request.headers["X-Customer-Assertion"],
        public_pem,
        algorithms=["EdDSA"],
        audience="socialtraff-crm",
    )
    assert claims["sub"] == ACCOUNT
    assert claims["act"] == 42
    assert claims["scope"] == "billing:read"
    assert claims["token_use"] == "customer_assertion"


async def test_write_retry_keeps_idempotency_key_and_resigns(
    ed25519_keys: tuple[bytes, bytes],
) -> None:
    private_pem, public_pem = ed25519_keys
    seen: list[httpx.Request] = []
    responses = [
        httpx.Response(503, json={"status": "error", "data": None, "message": "x", "code": "u"}),
        ok({"id": 1}),
    ]
    async with make_client(private_pem, responses, seen) as client:
        data = await client._request(
            "POST", "/billing/payments", scopes=["billing:write"], json={"plan": "pro"}
        )
    assert data == {"id": 1}
    assert len(seen) == 2
    keys = {r.headers["Idempotency-Key"] for r in seen}
    assert len(keys) == 1 and keys.pop()
    jtis = {
        jwt.decode(
            r.headers["X-Customer-Assertion"],
            public_pem,
            algorithms=["EdDSA"],
            audience="socialtraff-crm",
        )["jti"]
        for r in seen
    }
    assert len(jtis) == 2


async def test_explicit_idempotency_key_is_used(ed25519_keys: tuple[bytes, bytes]) -> None:
    seen: list[httpx.Request] = []
    async with make_client(ed25519_keys[0], [ok()], seen) as client:
        await client._request(
            "POST", "/referrals/withdraw", scopes=["referrals:write"], idempotency_key="abc"
        )
    assert seen[0].headers["Idempotency-Key"] == "abc"


async def test_expired_assertion_maps_to_auth_error(ed25519_keys: tuple[bytes, bytes]) -> None:
    seen: list[httpx.Request] = []
    body = {"status": "error", "data": None, "message": "expired", "code": "unauthorized"}
    async with make_client(ed25519_keys[0], [httpx.Response(401, json=body)], seen) as client:
        with pytest.raises(AuthError):
            await client._request("GET", "/ai/balance", scopes=["ai:read"])


def test_customer_config_errors(ed25519_keys: tuple[bytes, bytes]) -> None:
    signer = AssertionSigner(ed25519_keys[0], kid="k1")
    with pytest.raises(ConfigError):
        CustomerClient(BASE_URL, signer, "", 1)
    with pytest.raises(ConfigError):
        CustomerClient(BASE_URL, signer, ACCOUNT.upper(), 1)
    with pytest.raises(ConfigError):
        CustomerClient(BASE_URL, signer, ACCOUNT, 0)
    with pytest.raises(ConfigError):
        CustomerClient(BASE_URL, signer, ACCOUNT, True)
    with pytest.raises(ConfigError):
        CustomerClient(BASE_URL, signer, ACCOUNT, "1")  # type: ignore[arg-type]
    with pytest.raises(ConfigError):
        CustomerClient(BASE_URL, object(), ACCOUNT, 1)  # type: ignore[arg-type]
