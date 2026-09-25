from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import jwt
import pytest

from socialtraff_crm import (
    ApiError,
    AssertionSigner,
    AuthError,
    CustomerClient,
    NotFoundError,
    ValidationError,
)

BASE_URL = "http://crm.test"
ACCOUNT = "3f2b8c1e-8f4a-4d0b-9a57-0c7e6f1d2a90"
PREFIX = "/api/v1/customer"
TS = "2026-09-20T12:00:00+03:00"

PAYMENT_ROW = {
    "payment_public_id": "9d0c3a52-11f0-4b9e-8c21-5b2f6b1a0e77",
    "status": "paid",
    "amount_rub_kopecks": 99000,
    "currency": "RUB",
    "fx_rate_rub_usd": "92.5",
    "description": "Pro",
    "provider": "platega",
    "payment_method": "sbp",
    "items": [{"title": "Pro", "quantity": 1, "price_rub_kopecks": 99000}],
    "created_at": TS,
    "invoiced_at": TS,
    "paid_at": None,
}


def ok(data: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"status": "success", "data": data})


def fail(status: int, code: str, message: str = "x") -> httpx.Response:
    return httpx.Response(
        status, json={"status": "error", "data": None, "message": message, "code": code}
    )


class Recorder:
    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0)


def client_for(private_pem: bytes, recorder: Recorder) -> CustomerClient:
    signer = AssertionSigner(private_pem, kid="k1")
    return CustomerClient(BASE_URL, signer, ACCOUNT, 42, transport=httpx.MockTransport(recorder))


def claims_of(request: httpx.Request, public_pem: bytes) -> dict[str, Any]:
    return jwt.decode(
        request.headers["X-Customer-Assertion"],
        public_pem,
        algorithms=["EdDSA"],
        audience="socialtraff-crm",
    )


Call = Callable[[CustomerClient], Awaitable[Any]]

# (call, HTTP method, path under /api/v1/customer, scope, response data)
ROUTES: list[tuple[str, Call, str, str, str, Any]] = [
    (
        "billing.products",
        lambda c: c.billing.products(),
        "GET",
        "/billing/products",
        "billing:read",
        {"items": []},
    ),
    (
        "billing.subscription",
        lambda c: c.billing.subscription(),
        "GET",
        "/billing/subscription",
        "billing:read",
        {"active": False, "ends_at": None, "frozen": False, "frozen_at": None},
    ),
    (
        "billing.list_payments",
        lambda c: c.billing.list_payments(),
        "GET",
        "/billing/payments",
        "billing:read",
        {"items": [], "next_cursor": None},
    ),
    (
        "billing.get_payment",
        lambda c: c.billing.get_payment("9d0c3a52-11f0-4b9e-8c21-5b2f6b1a0e77"),
        "GET",
        "/billing/payments/9d0c3a52-11f0-4b9e-8c21-5b2f6b1a0e77",
        "billing:read",
        PAYMENT_ROW,
    ),
    (
        "billing.create_payment",
        lambda c: c.billing.create_payment(
            3, quantity=1, provider="platega", payment_method="sbp", return_to="https://w/x"
        ),
        "POST",
        "/billing/payments",
        "billing:write",
        {
            "payment_public_id": "p",
            "checkout_url": None,
            "status": "invoiced",
            "pay_url": "https://pay.example/p",
            "amount_rub_kopecks": 1,
            "return_to": "https://w/x",
        },
    ),
    (
        "ai.balance",
        lambda c: c.ai.balance(),
        "GET",
        "/ai/balance",
        "ai:read",
        {"tokens_per_usd": 1000, "functions": []},
    ),
    (
        "ai.history",
        lambda c: c.ai.history(),
        "GET",
        "/ai/history",
        "ai:read",
        {"items": [], "next_cursor": None},
    ),
    (
        "ai.usage",
        lambda c: c.ai.usage(),
        "GET",
        "/ai/usage",
        "ai:read",
        {"from": "2026-09-01", "to": "2026-09-30", "bucket": "day", "items": []},
    ),
    (
        "ai.key",
        lambda c: c.ai.key(),
        "GET",
        "/ai/key",
        "ai:read",
        {
            "mask": "sk-or-…abcd",
            "usage_usd": 0.0,
            "limit_usd": None,
            "limit_remaining_usd": None,
            "disabled": False,
        },
    ),
    (
        "referrals.withdrawals",
        lambda c: c.referrals.withdrawals(),
        "GET",
        "/referrals/withdrawals",
        "referrals:read",
        {"items": [], "next_cursor": None},
    ),
    (
        "referrals.withdraw",
        lambda c: c.referrals.withdraw("wallet"),
        "POST",
        "/referrals/withdraw",
        "referrals:write",
        {
            "withdrawal_public_id": "w",
            "status": "requested",
            "amount_usd_cents": 1,
            "method": "wallet",
        },
    ),
]


@pytest.mark.parametrize(
    ("call", "method", "path", "scope", "data"),
    [route[1:] for route in ROUTES],
    ids=[route[0] for route in ROUTES],
)
async def test_route_path_scope_and_idempotency(
    ed25519_keys: tuple[bytes, bytes],
    call: Call,
    method: str,
    path: str,
    scope: str,
    data: Any,
) -> None:
    private_pem, public_pem = ed25519_keys
    recorder = Recorder(ok(data, 201 if method == "POST" else 200))
    async with client_for(private_pem, recorder) as client:
        await call(client)
    request = recorder.requests[0]
    assert request.method == method
    assert request.url.path == PREFIX + path
    claims = claims_of(request, public_pem)
    assert claims["scope"] == scope
    assert claims["sub"] == ACCOUNT and claims["act"] == 42
    assert claims["token_use"] == "customer_assertion"
    assert ("Idempotency-Key" in request.headers) == (method == "POST")


async def test_referrals_get_parses_summary(ed25519_keys: tuple[bytes, bytes]) -> None:
    summary = {
        "ref_link": "https://t.me/bot?start=r1",
        "percent": 10,
        "registrations": 3,
        "referred_payments_count": 2,
        "referred_turnover_rub_kopecks": 198000,
        "earned_usd_cents": 500,
        "available_usd_cents": 250,
        "withdrawn_wallet_usd_cents": 0,
        "withdrawn_subscription_usd_cents": 0,
        "min_withdrawal_usd_cents": 1000,
        "withdraw_methods": ["subscription", "wallet"],
    }
    recorder = Recorder(ok(summary))
    async with client_for(ed25519_keys[0], recorder) as client:
        result = await client.referrals.get()
    assert recorder.requests[0].url.path == f"{PREFIX}/referrals"
    assert result.available_usd_cents == 250
    assert result.withdraw_methods == ["subscription", "wallet"]


async def test_create_payment_body_and_explicit_key(ed25519_keys: tuple[bytes, bytes]) -> None:
    data = {
        "payment_public_id": "p1",
        "checkout_url": "https://pay/p1/",
        "status": "draft",
        "amount_rub_kopecks": 50000,
        "return_to": "https://w/back",
        "ai_tokens": 100000,
        "function": "text",
    }
    recorder = Recorder(ok(data, 201))
    async with client_for(ed25519_keys[0], recorder) as client:
        result = await client.billing.create_payment(
            7,
            quantity=1,
            provider="yookassa",
            return_to="https://w/back",
            ai_function="text",
            idempotency_key="key-1",
        )
    request = recorder.requests[0]
    assert request.headers["Idempotency-Key"] == "key-1"
    # payment_method is omitted, not sent as null: CRM rejects it outside platega.
    assert json.loads(request.content) == {
        "product_id": 7,
        "quantity": 1,
        "provider": "yookassa",
        "return_to": "https://w/back",
        "ai_function": "text",
    }
    assert result.ai_tokens == 100000 and result.checkout_url == "https://pay/p1/"


async def test_create_payment_parses_crm_201_shape(ed25519_keys: tuple[bytes, bytes]) -> None:
    # Exact body of CRM customer_billing.create_payment: invoice issued, storefront unset.
    data = {
        "payment_public_id": "0192f3a4-5b6e-7b22-9d33-445566778801",
        "checkout_url": None,
        "status": "invoiced",
        "amount_rub_kopecks": 78300,
        "return_to": "https://lk.socialtraff.com/billing",
        "pay_url": "https://pay.platega.io/0192f3a4",
    }
    recorder = Recorder(ok(data, 201))
    async with client_for(ed25519_keys[0], recorder) as client:
        result = await client.billing.create_payment(
            3, quantity=3, provider="platega", payment_method="sbp", return_to=data["return_to"]
        )
    assert result.status == "invoiced"
    assert result.pay_url == "https://pay.platega.io/0192f3a4"
    assert result.checkout_url is None
    assert result.payment_public_id == data["payment_public_id"]
    assert result.ai_tokens is None


async def test_list_payments_query_and_models(ed25519_keys: tuple[bytes, bytes]) -> None:
    recorder = Recorder(ok({"items": [PAYMENT_ROW], "next_cursor": "c2"}))
    async with client_for(ed25519_keys[0], recorder) as client:
        page = await client.billing.list_payments(cursor="c1", limit=10)
    assert dict(recorder.requests[0].url.params) == {"cursor": "c1", "limit": "10"}
    assert page.next_cursor == "c2"
    payment = page.items[0]
    assert payment.fx_rate_rub_usd == Decimal("92.5")
    assert payment.created_at is not None and payment.created_at.utcoffset() is not None
    assert payment.items[0].price_rub_kopecks == 99000


async def test_products_parse_items(ed25519_keys: tuple[bytes, bytes]) -> None:
    item = {
        "product_id": 5,
        "title": "AI 100k",
        "kind": "ai_tokens",
        "price_rub_kopecks": 50000,
        "price_usd_cents": None,
        "feature_keys": [],
        "billed_per_month": False,
        "ai_tokens": 100000,
        "ai_functions": ["text", "image"],
        "future_field": 1,
    }
    async with client_for(ed25519_keys[0], Recorder(ok({"items": [item]}))) as client:
        products = await client.billing.products()
    assert [p.product_id for p in products] == [5]
    assert products[0].ai_functions == ["text", "image"]


async def test_ai_history_and_usage_params(ed25519_keys: tuple[bytes, bytes]) -> None:
    history_item = {
        "at": TS,
        "function": "text",
        "model": "gpt",
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "total_tokens": 3,
        "cost_usd_micro": 10,
        "charged_usd_micro": 12,
        "charged_tokens": 12,
        "source": "bot",
    }
    usage = {
        "from": "2026-09-01",
        "to": "2026-09-30",
        "bucket": "day",
        "items": [
            {
                "day": "2026-09-02",
                "function": "text",
                "cost_usd_micro": 1,
                "charged_usd_micro": 2,
                "tokens": 3,
                "generations": 1,
            }
        ],
    }
    recorder = Recorder(ok({"items": [history_item], "next_cursor": None}), ok(usage))
    async with client_for(ed25519_keys[0], recorder) as client:
        history = await client.ai.history(function="text", limit=5)
        result = await client.ai.usage(date_from="2026-09-01", date_to="2026-09-30")
    assert dict(recorder.requests[0].url.params) == {"function": "text", "limit": "5"}
    assert dict(recorder.requests[1].url.params) == {"from": "2026-09-01", "to": "2026-09-30"}
    assert history.items[0].charged_tokens == 12
    assert result.date_from == date(2026, 9, 1) and result.items[0].generations == 1


async def test_naive_datetime_is_rejected(ed25519_keys: tuple[bytes, bytes]) -> None:
    naive = dict(PAYMENT_ROW, created_at="2026-09-20T12:00:00")
    async with client_for(ed25519_keys[0], Recorder(ok(naive))) as client:
        with pytest.raises(ValidationError):
            await client.billing.get_payment("9d0c3a52-11f0-4b9e-8c21-5b2f6b1a0e77")


async def test_malformed_payload_is_validation_error(ed25519_keys: tuple[bytes, bytes]) -> None:
    async with client_for(ed25519_keys[0], Recorder(ok({"unexpected": True}))) as client:
        with pytest.raises(ValidationError):
            await client.billing.products()


@pytest.mark.parametrize(
    ("response", "error", "code"),
    [
        (fail(401, "unauthorized"), AuthError, "unauthorized"),
        (fail(403, "insufficient_scope"), AuthError, "insufficient_scope"),
        (fail(404, "not_found"), NotFoundError, "not_found"),
        (fail(422, "validation_failed"), ValidationError, "validation_failed"),
        (fail(409, "withdrawal_already_pending"), ApiError, "withdrawal_already_pending"),
    ],
)
async def test_error_envelopes_map_to_sdk_errors(
    ed25519_keys: tuple[bytes, bytes],
    response: httpx.Response,
    error: type[Exception],
    code: str,
) -> None:
    async with client_for(ed25519_keys[0], Recorder(response)) as client:
        with pytest.raises(error) as info:
            await client.referrals.withdraw("wallet", idempotency_key="k")
    assert getattr(info.value, "code", None) == code


async def test_ai_key_parses_stats(ed25519_keys: tuple[bytes, bytes]) -> None:
    stats = {
        "mask": "sk-or-…abcd",
        "usage_usd": 2.5,
        "limit_usd": 10.0,
        "limit_remaining_usd": 7.5,
        "disabled": True,
    }
    async with client_for(ed25519_keys[0], Recorder(ok(stats))) as client:
        result = await client.ai.key()
    assert result.mask == "sk-or-…abcd" and result.usage_usd == 2.5
    assert result.limit_remaining_usd == 7.5 and result.disabled is True


@pytest.mark.parametrize(
    ("response", "error", "code"),
    [
        (fail(404, "not_found"), NotFoundError, "not_found"),
        (fail(503, "upstream_unavailable"), ApiError, "upstream_unavailable"),
    ],
)
async def test_ai_key_errors(
    ed25519_keys: tuple[bytes, bytes],
    response: httpx.Response,
    error: type[Exception],
    code: str,
) -> None:
    recorder = Recorder(response)
    async with CustomerClient(
        BASE_URL,
        AssertionSigner(ed25519_keys[0], kid="k1"),
        ACCOUNT,
        42,
        retries=1,
        transport=httpx.MockTransport(recorder),
    ) as client:
        with pytest.raises(error) as info:
            await client.ai.key()
    assert getattr(info.value, "code", None) == code
    assert len(recorder.requests) == 1


async def test_get_payment_escapes_path(ed25519_keys: tuple[bytes, bytes]) -> None:
    recorder = Recorder(fail(404, "not_found"))
    async with client_for(ed25519_keys[0], recorder) as client:
        with pytest.raises(NotFoundError):
            await client.billing.get_payment("../ai/balance")
    expected = f"{PREFIX}/billing/payments/..%2Fai%2Fbalance".encode()
    assert recorder.requests[0].url.raw_path == expected
