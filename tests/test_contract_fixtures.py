"""Contract fixtures: CRM-shaped bodies must parse with the SDK as it receives them."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from socialtraff_crm import (
    NotifyEvent,
    PlanChangedEvent,
    ServiceClient,
    SignatureError,
    webhooks,
)
from socialtraff_crm.models import (
    KNOWN_NOTIFY_KINDS,
    AccountPlans,
    AiKeyStats,
    CustomerId,
    PlansPage,
    SubscriptionChangedPayload,
)

FIXTURES = Path(__file__).parent / "fixtures" / "contract"
SECRET = "product-webhook-secret"
BASE_URL = "http://crm.test"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _crm_body(envelope: Any) -> bytes:
    # Same serialization as the CRM product publisher: the HMAC covers exactly these bytes.
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _signed(name: str) -> tuple[bytes, str]:
    body = _crm_body(_load(name))
    return body, webhooks.compute_signature(body, SECRET)


def test_plan_changed_fixture_verifies() -> None:
    body, signature = _signed("plan_changed.json")
    event = webhooks.verify(body, signature, SECRET)
    assert isinstance(event, PlanChangedEvent)
    assert event.payload.product == "cabinet"
    assert event.payload.plan_until is not None
    assert event.payload.plan_until.utcoffset() is not None
    assert event.payload.version == 5817


def test_notify_payment_confirmed_fixture_verifies() -> None:
    body, signature = _signed("notify_payment_confirmed.json")
    event = webhooks.verify(body, signature, SECRET)
    assert isinstance(event, NotifyEvent)
    assert event.payload.kind == "payment_confirmed"
    assert event.payload.button is None
    assert event.payload.params["currency"] == "RUB"


def test_notify_fallback_fixture_verifies() -> None:
    body, signature = _signed("notify_fallback.json")
    event = webhooks.verify(body, signature, SECRET)
    assert isinstance(event, NotifyEvent)
    assert event.payload.kind.endswith("_fallback")
    assert event.payload.button is not None
    assert event.payload.button.text is None
    assert event.payload.button.url.startswith("https://t.me/")


@pytest.mark.parametrize(
    "name", ["plan_changed.json", "notify_payment_confirmed.json", "notify_fallback.json"]
)
def test_webhook_fixture_tampered_body_fails(name: str) -> None:
    body, signature = _signed(name)
    tampered = body.replace(b"1042", b"1043")
    assert tampered != body
    with pytest.raises(SignatureError):
        webhooks.verify(tampered, signature, SECRET)


def test_raw_fixture_bytes_verify_too() -> None:
    # Signature is over whatever bytes arrived, not a canonical form.
    raw = (FIXTURES / "plan_changed.json").read_bytes()
    event = webhooks.verify(raw, webhooks.compute_signature(raw, SECRET), SECRET)
    assert isinstance(event, PlanChangedEvent)


def test_fixture_notify_kinds_are_documented() -> None:
    for name in ("notify_payment_confirmed.json", "notify_fallback.json"):
        assert _load(name)["payload"]["kind"] in KNOWN_NOTIFY_KINDS


def test_subscription_changed_payload_parses() -> None:
    payload = SubscriptionChangedPayload.model_validate(
        {
            "account_id": 1042,
            "user_id": 555000111,
            "has_active_subscription": False,
            "frozen": False,
            "reason": "expired",
        }
    )
    assert payload.reason == "expired"


Call = Callable[[ServiceClient], Awaitable[Any]]


async def _serve(name: str, call: Call) -> Any:
    envelope = _load(name)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope)

    async with ServiceClient(BASE_URL, "svc", transport=httpx.MockTransport(handler)) as crm:
        return await call(crm)


async def test_service_plans_get_fixture() -> None:
    result = await _serve("service_plans_get.json", lambda crm: crm.plans.get(1042))
    assert isinstance(result, AccountPlans)
    assert result.plans["cabinet"].plan == "pro"
    assert result.plans["privetka"].plan is None


async def test_service_plans_list_fixture() -> None:
    since = datetime(2026, 9, 1, tzinfo=UTC)
    result = await _serve("service_plans_list.json", lambda crm: crm.plans.list_updated(since))
    assert isinstance(result, PlansPage)
    assert [item.account_id for item in result.items] == [1042, 1043]
    assert result.items[1].version is None
    assert result.next_cursor


async def test_service_ai_key_stats_fixture() -> None:
    result = await _serve("service_ai_key_stats.json", lambda crm: crm.ai.key_stats(1042))
    assert isinstance(result, AiKeyStats)
    assert result.limit_usd == 10.0
    assert result.disabled is False


async def test_service_customer_id_fixture() -> None:
    result = await _serve(
        "service_customer_id.json", lambda crm: crm.identity.issue_customer_id(1042)
    )
    assert isinstance(result, CustomerId)
    assert result.public_customer_id == "3f2b8c1e-8f4a-4d0b-9a57-0c7e6f1d2a90"
