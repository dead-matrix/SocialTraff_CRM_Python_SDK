from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx
import pytest

from socialtraff_crm import (
    ApiError,
    AuthError,
    NotFoundError,
    ServiceClient,
    ValidationError,
)

BASE_URL = "http://crm.test"
TOKEN = "svc-token"
PREFIX = "/api/internal"
TS = "2026-09-20T12:00:00+03:00"
MSK = timezone(timedelta(hours=3))
SECRET = "sk-or-v1-very-secret-value"

BUYER = {
    "buyer_id": 7,
    "tg_id": 100,
    "email": None,
    "display_name": "Ann",
    "ref_code": "r7",
    "created_at": TS,
    "updated_at": TS,
    "created": True,
}
ACCOUNT = {
    "account_id": 11,
    "title": "Team",
    "owner_buyer_id": 7,
    "is_personal": False,
    "created_at": TS,
    "updated_at": TS,
    "created": False,
}
MEMBER = {
    "account_id": 11,
    "buyer_id": 7,
    "role": "admin",
    "joined_at": TS,
    "removed_at": None,
    "created": True,
}
PLANS = {
    "account_id": 11,
    "version": 3,
    "updated_at": TS,
    "plans": {"main": {"plan": "pro", "expires_at": TS}, "ai": {"plan": None, "expires_at": None}},
}
STATS = {
    "mask": "sk-or-…abcd",
    "usage_usd": 1.25,
    "limit_usd": None,
    "limit_remaining_usd": None,
    "disabled": False,
}

PRODUCT = {
    "product_id": 1,
    "title": "Cabinet Pro",
    "kind": "subscription",
    "price_rub_kopecks": 29000,
    "price_usd_cents": None,
    "feature_keys": ["cabinet.pro"],
    "billed_per_month": True,
    "ai_tokens": None,
    "ai_functions": None,
}


def ok(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"status": "success", "data": data})


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


def client_for(recorder: Recorder, retries: int = 3) -> ServiceClient:
    return ServiceClient(BASE_URL, TOKEN, retries=retries, transport=httpx.MockTransport(recorder))


def body_of(request: httpx.Request) -> Any:
    return json.loads(request.content) if request.content else None


Call = Callable[[ServiceClient], Awaitable[Any]]

# (call, HTTP method, path under /api/internal, expected JSON body, response data)
ROUTES: list[tuple[str, Call, str, str, Any, Any]] = [
    (
        "identity.put_buyer",
        lambda c: c.identity.put_buyer(7, tg_id=100, display_name="Ann"),
        "PUT",
        "/identity/buyers/7",
        {"tg_id": 100, "display_name": "Ann"},
        BUYER,
    ),
    (
        "identity.put_account",
        lambda c: c.identity.put_account(
            11,
            title="Team",
            owner_buyer_id=7,
            is_personal=False,
            created_at=datetime(2026, 9, 20, 12, tzinfo=MSK),
        ),
        "PUT",
        "/identity/accounts/11",
        {
            "title": "Team",
            "owner_buyer_id": 7,
            "is_personal": False,
            "created_at": "2026-09-20T12:00:00+03:00",
        },
        ACCOUNT,
    ),
    (
        "identity.put_member",
        lambda c: c.identity.put_member(11, 7, "admin"),
        "PUT",
        "/identity/accounts/11/members/7",
        {"role": "admin"},
        MEMBER,
    ),
    (
        "identity.remove_member",
        lambda c: c.identity.remove_member(11, 7),
        "DELETE",
        "/identity/accounts/11/members/7",
        None,
        {"account_id": 11, "buyer_id": 7, "role": None, "removed_at": None},
    ),
    (
        "identity.issue_customer_id",
        lambda c: c.identity.issue_customer_id(11),
        "POST",
        "/identity/accounts/11/customer-id",
        None,
        {"account_id": 11, "public_customer_id": "3f2b8c1e-8f4a-4d0b-9a57-0c7e6f1d2a90"},
    ),
    (
        "identity.import",
        lambda c: c.identity.import_(
            buyers=[{"buyer_id": 7, "email": None}],
            accounts=[
                {
                    "account_id": 11,
                    "title": "Team",
                    "owner_buyer_id": 7,
                    "is_personal": True,
                    "created_at": datetime(2026, 9, 20, 9, tzinfo=UTC),
                }
            ],
            members=[{"account_id": 11, "buyer_id": 7, "role": "owner"}],
        ),
        "POST",
        "/identity/import",
        {
            "buyers": [{"buyer_id": 7, "email": None}],
            "accounts": [
                {
                    "account_id": 11,
                    "title": "Team",
                    "owner_buyer_id": 7,
                    "is_personal": True,
                    "created_at": "2026-09-20T09:00:00+00:00",
                }
            ],
            "members": [{"account_id": 11, "buyer_id": 7, "role": "owner"}],
        },
        {"buyers": 1, "accounts": 1, "members": 1},
    ),
    (
        "plans.import",
        lambda c: c.plans.import_(
            [
                {
                    "account_id": 11,
                    "category": "main",
                    "plan": "pro",
                    "expires_at": datetime(2026, 10, 1, tzinfo=MSK),
                }
            ]
        ),
        "POST",
        "/plans/import",
        {
            "items": [
                {
                    "account_id": 11,
                    "category": "main",
                    "plan": "pro",
                    "expires_at": "2026-10-01T00:00:00+03:00",
                }
            ]
        },
        {"imported": 1, "unchanged": 0},
    ),
    ("plans.get", lambda c: c.plans.get(11), "GET", "/plans/11", None, PLANS),
    (
        "plans.list_updated",
        lambda c: c.plans.list_updated(datetime(2026, 9, 1, tzinfo=UTC)),
        "GET",
        "/plans",
        None,
        {"items": [PLANS], "next_cursor": None},
    ),
    (
        "ai.ensure_key",
        lambda c: c.ai.ensure_key(11),
        "POST",
        "/ai/key/ensure",
        {"account_id": 11, "function": "default"},
        {"secret": SECRET, "key_mode": "own", "source": "minted"},
    ),
    ("ai.key_stats", lambda c: c.ai.key_stats(11), "GET", "/ai/key/11/stats", None, STATS),
    ("catalog.get", lambda c: c.catalog.get(), "GET", "/catalog", None, {"items": [PRODUCT]}),
]


@pytest.mark.parametrize(
    ("call", "method", "path", "body", "data"),
    [route[1:] for route in ROUTES],
    ids=[route[0] for route in ROUTES],
)
async def test_route_path_body_and_token(
    call: Call, method: str, path: str, body: Any, data: Any
) -> None:
    recorder = Recorder(ok(data))
    async with client_for(recorder) as client:
        await call(client)
    request = recorder.requests[0]
    assert request.method == method
    assert request.url.path == PREFIX + path
    assert request.headers["X-Service-Token"] == TOKEN
    assert body_of(request) == body
    # No key was passed: CRM service routes do not require one.
    assert "Idempotency-Key" not in request.headers


async def test_put_buyer_distinguishes_omitted_from_none() -> None:
    recorder = Recorder(ok(BUYER), ok(BUYER))
    async with client_for(recorder) as client:
        await client.identity.put_buyer(7)
        buyer = await client.identity.put_buyer(7, email=None, refer="r1", landing="/l")
    assert body_of(recorder.requests[0]) == {}
    assert body_of(recorder.requests[1]) == {"email": None, "refer": "r1", "landing": "/l"}
    assert buyer.created is True and buyer.ref_code == "r7"
    assert buyer.created_at is not None and buyer.created_at.utcoffset() == timedelta(hours=3)


async def test_ensure_key_returns_secret_and_hides_it_in_repr() -> None:
    data = {"secret": SECRET, "key_mode": "own", "source": "existing"}
    recorder = Recorder(ok(data))
    async with client_for(recorder) as client:
        key = await client.ai.ensure_key(11, function="text")
    assert body_of(recorder.requests[0]) == {"account_id": 11, "function": "text"}
    assert key.secret == SECRET
    assert SECRET not in repr(key) and SECRET not in str(key)
    assert key.key_mode == "own" and key.source == "existing"


async def test_key_stats_parses_nullable_limits() -> None:
    async with client_for(Recorder(ok(dict(STATS, limit_usd=5.0)))) as client:
        stats = await client.ai.key_stats(11)
    assert stats.mask == "sk-or-…abcd" and stats.usage_usd == 1.25
    assert stats.limit_usd == 5.0 and stats.limit_remaining_usd is None
    assert stats.disabled is False


async def test_plans_models_and_list_query() -> None:
    empty = {"account_id": 12, "version": None, "updated_at": None, "plans": {}}
    recorder = Recorder(ok({"items": [PLANS, empty], "next_cursor": "c2"}))
    async with client_for(recorder) as client:
        page = await client.plans.list_updated(
            datetime(2026, 9, 1, 12, tzinfo=MSK), limit=50, cursor="c1"
        )
    assert dict(recorder.requests[0].url.params) == {
        "updated_since": "2026-09-01T12:00:00+03:00",
        "cursor": "c1",
        "limit": "50",
    }
    # "+" in the offset must be percent-encoded or CRM would read it as a space.
    assert b"%2B03%3A00" in recorder.requests[0].url.query
    assert page.next_cursor == "c2"
    first = page.items[0]
    assert first.version == 3 and first.plans["main"].plan == "pro"
    assert first.plans["ai"].plan is None and first.plans["ai"].expires_at is None
    assert page.items[1].version is None and page.items[1].plans == {}


async def test_catalog_get_returns_products_and_retries_get(sleeps: list[float]) -> None:
    recorder = Recorder(fail(503, "unavailable"), ok({"items": [PRODUCT]}))
    async with client_for(recorder) as client:
        items = await client.catalog.get()
    assert len(recorder.requests) == 2 and len(sleeps) == 1
    assert [item.feature_keys for item in items] == [["cabinet.pro"]]
    assert items[0].price_rub_kopecks == 29000 and items[0].price_usd_cents is None


async def test_catalog_get_bad_token_is_auth_error() -> None:
    async with client_for(Recorder(fail(403, "forbidden"))) as client:
        with pytest.raises(AuthError):
            await client.catalog.get()


async def test_remove_absent_member_parses_nulls() -> None:
    data = {"account_id": 11, "buyer_id": 8, "role": None, "removed_at": None}
    async with client_for(Recorder(ok(data))) as client:
        member = await client.identity.remove_member(11, 8)
    assert member.role is None and member.joined_at is None and member.created is None


async def test_import_with_key_is_sent_and_retried(sleeps: list[float]) -> None:
    recorder = Recorder(fail(503, "unavailable"), ok({"imported": 0, "unchanged": 1}))
    async with client_for(recorder) as client:
        result = await client.plans.import_([], idempotency_key="batch-1")
    assert result.unchanged == 1
    assert len(recorder.requests) == 2 and len(sleeps) == 1
    assert all(r.headers["Idempotency-Key"] == "batch-1" for r in recorder.requests)


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.identity.put_account(
            1, title="t", owner_buyer_id=1, is_personal=True, created_at=datetime(2026, 9, 1)
        ),
        lambda c: c.plans.import_(
            [
                {
                    "account_id": 1,
                    "category": "main",
                    "plan": "pro",
                    "expires_at": datetime(2026, 9, 1),
                }
            ]
        ),
        lambda c: c.identity.import_(
            accounts=[{"account_id": 1, "created_at": datetime(2026, 9, 1)}]
        ),
        lambda c: c.plans.list_updated(datetime(2026, 9, 1)),
    ],
    ids=["put_account", "plans.import", "identity.import", "plans.list_updated"],
)
async def test_naive_datetime_is_rejected_before_request(call: Call) -> None:
    recorder = Recorder()
    async with client_for(recorder) as client:
        with pytest.raises(ValidationError):
            await call(client)
    assert recorder.requests == []


async def test_naive_datetime_in_response_is_rejected() -> None:
    naive = dict(ACCOUNT, created_at="2026-09-20T12:00:00")
    async with client_for(Recorder(ok(naive))) as client:
        with pytest.raises(ValidationError):
            await client.identity.put_account(11, title="Team", owner_buyer_id=7, is_personal=False)


@pytest.mark.parametrize(
    ("call", "response", "error", "code"),
    [
        (lambda c: c.plans.get(11), fail(401, "unauthorized"), AuthError, "unauthorized"),
        (lambda c: c.plans.get(11), fail(403, "forbidden"), AuthError, "forbidden"),
        (lambda c: c.plans.get(99), fail(404, "not_found"), NotFoundError, "not_found"),
        (
            lambda c: c.identity.put_buyer(7, tg_id=5),
            fail(409, "tg_id_taken"),
            ApiError,
            "tg_id_taken",
        ),
        (
            lambda c: c.plans.import_([], idempotency_key=None),
            fail(422, "unknown_plan"),
            ValidationError,
            "unknown_plan",
        ),
        (
            lambda c: c.ai.ensure_key(11),
            fail(502, "internal_error", "ensure_key failed"),
            ApiError,
            "internal_error",
        ),
        (lambda c: c.ai.key_stats(11), fail(404, "not_found"), NotFoundError, "not_found"),
    ],
    ids=["401", "403", "404", "409", "422", "502", "stats-404"],
)
async def test_error_envelopes_map_to_sdk_errors(
    call: Call, response: httpx.Response, error: type[Exception], code: str
) -> None:
    # One attempt: 502 on a GET would otherwise be retried.
    async with client_for(Recorder(response), retries=1) as client:
        with pytest.raises(error) as info:
            await call(client)
    assert getattr(info.value, "code", None) == code


async def test_path_ids_are_escaped() -> None:
    recorder = Recorder(fail(404, "not_found"))
    async with client_for(recorder) as client:
        with pytest.raises(NotFoundError):
            await client.plans.get("../ai")  # type: ignore[arg-type]
    assert recorder.requests[0].url.raw_path == f"{PREFIX}/plans/..%2Fai".encode()
