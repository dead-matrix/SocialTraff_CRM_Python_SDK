"""Contract fixtures: CRM-shaped bodies must parse with the SDK as it receives them.

``tests/fixtures/contract/*.json`` is a byte copy of CRM ``tests/contract/*.json`` (the CRM
commit is in ``CRM_VERSION``). Every fixture must be mapped in ``FIXTURE_CALLS`` below: a new
fixture in CRM fails ``test_every_fixture_is_mapped`` until the SDK learns to parse it, so the
SDK cannot drift from CRM silently. Re-sync: ``python scripts/sync_contract_fixtures.py``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from socialtraff_crm import (
    AssertionSigner,
    CustomerClient,
    GenericEvent,
    NotifyEvent,
    PlanChangedEvent,
    ServiceClient,
    SignatureError,
    webhooks,
)
from socialtraff_crm.models import (
    KNOWN_NOTIFY_KINDS,
    AccessExpiredFollowupParams,
    Account,
    AccountChatsResult,
    AccountPlans,
    AiKey,
    AiKeyStats,
    Buyer,
    CatalogProduct,
    CheckoutSession,
    CustomerId,
    ExpiringParams,
    IdentityImportResult,
    Member,
    PartnerCode,
    Payment,
    PaymentConfirmedParams,
    PaymentExpiredParams,
    PaymentReminderParams,
    PlansImportResult,
    PlansPage,
    PromoActivation,
    ReferralSummary,
    Subscription,
    SubscriptionChangedPayload,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "contract"
SECRET = "product-webhook-secret"
# Secret CRM used to sign ``webhook_product_request.json`` (CRM tests/contract/README.md).
CONTRACT_WEBHOOK_SECRET = "contract-webhook-secret"
BASE_URL = "http://crm.test"
ACCOUNT_PUBLIC_ID = "3f2b8c1e-8f4a-4d0b-9a57-0c7e6f1d2a90"
SINCE = datetime(2026, 9, 1, tzinfo=UTC)


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _fixture_names() -> list[str]:
    return sorted(path.name for path in FIXTURES.glob("*.json"))


def _crm_body(envelope: Any) -> bytes:
    # Same serialization as the CRM product publisher: the HMAC covers exactly these bytes.
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _signed(name: str) -> tuple[bytes, str]:
    body = _crm_body(_load(name))
    return body, webhooks.compute_signature(body, SECRET)


# --------------------------------------------------------------------------- #
# How each fixture is consumed by the SDK
# --------------------------------------------------------------------------- #
ServiceCall = Callable[[ServiceClient], Awaitable[Any]]
CustomerCall = Callable[[CustomerClient], Awaitable[Any]]

SERVICE_CALLS: dict[str, tuple[ServiceCall, type]] = {
    "service_ai_key_ensure.json": (lambda crm: crm.ai.ensure_key(1042), AiKey),
    "service_ai_key_stats.json": (lambda crm: crm.ai.key_stats(1042), AiKeyStats),
    "service_catalog.json": (lambda crm: crm.catalog.get(), list),
    "service_customer_id.json": (lambda crm: crm.identity.issue_customer_id(1042), CustomerId),
    "service_identity_import.json": (
        lambda crm: crm.identity.import_(
            buyers=[{"buyer_id": 8001, "tg_id": 5558001}],
            accounts=[
                {"account_id": 2001, "title": "Team", "owner_buyer_id": 8001, "is_personal": False}
            ],
            members=[{"account_id": 2001, "buyer_id": 8001, "role": "owner"}],
        ),
        IdentityImportResult,
    ),
    "service_identity_put_chats.json": (
        lambda crm: crm.identity.put_account_chats(
            2003,
            [
                {"tg_chat_id": -1001234567890, "type": "supergroup"},
                {"tg_chat_id": 5558001, "type": "private"},
            ],
        ),
        AccountChatsResult,
    ),
    "service_identity_put_account.json": (
        lambda crm: crm.identity.put_account(
            2001, title="Team", owner_buyer_id=8001, is_personal=False
        ),
        Account,
    ),
    "service_identity_put_buyer.json": (
        lambda crm: crm.identity.put_buyer(8001, tg_id=5558001, email="b@example.com"),
        Buyer,
    ),
    "service_identity_put_member.json": (
        lambda crm: crm.identity.put_member(2001, 8001, "owner"),
        Member,
    ),
    "service_identity_remove_member.json": (
        lambda crm: crm.identity.remove_member(2001, 8001),
        Member,
    ),
    "service_plans_get.json": (lambda crm: crm.plans.get(1042), AccountPlans),
    "service_plans_import.json": (
        lambda crm: crm.plans.import_(
            [
                {
                    "account_id": 1042,
                    "category": "cabinet",
                    "plan": "pro",
                    "expires_at": datetime(2026, 10, 25, 20, 59, 59, tzinfo=UTC),
                }
            ]
        ),
        PlansImportResult,
    ),
    "service_plans_list.json": (lambda crm: crm.plans.list_updated(SINCE), PlansPage),
}

PAYMENT_ID = "0192f3a4-5b6c-7d8e-9f01-23456789abcd"
RETURN_TO = "https://app.socialtraff.test/billing/return"

CUSTOMER_CALLS: dict[str, tuple[CustomerCall, type]] = {
    "customer_ai_key.json": (lambda c: c.ai.key(), AiKeyStats),
    "customer_billing_payment_create.json": (
        lambda c: c.billing.create_payment(
            1,
            quantity=1,
            provider="platega",
            return_to=RETURN_TO,
            payment_method="sbp",
        ),
        CheckoutSession,
    ),
    "customer_billing_payment_create_balance.json": (
        lambda c: c.billing.create_payment(
            1, quantity=1, provider="platega", return_to=RETURN_TO, use_balance=True
        ),
        CheckoutSession,
    ),
    "customer_billing_payment_create_balance_partial.json": (
        lambda c: c.billing.create_payment(
            1,
            quantity=1,
            provider="platega",
            return_to=RETURN_TO,
            payment_method="sbp",
            use_balance=True,
        ),
        CheckoutSession,
    ),
    "customer_billing_payment_get.json": (lambda c: c.billing.get_payment(PAYMENT_ID), Payment),
    "customer_billing_payment_get_balance.json": (
        lambda c: c.billing.get_payment(PAYMENT_ID),
        Payment,
    ),
    "customer_billing_products.json": (lambda c: c.billing.products(), list),
    "customer_billing_subscription.json": (lambda c: c.billing.subscription(), Subscription),
    "customer_promo.json": (lambda c: c.promo.pending(), list),
    "customer_promo_activate.json": (lambda c: c.promo.activate("SALE15"), PromoActivation),
    "customer_referrals.json": (lambda c: c.referrals.get(), ReferralSummary),
    "customer_referrals_code.json": (lambda c: c.referrals.set_code("Owner_Promo"), PartnerCode),
}

#: Customer routes CRM answers with 201 Created.
CUSTOMER_CREATED = {
    "customer_billing_payment_create.json",
    "customer_billing_payment_create_balance.json",
    "customer_billing_payment_create_balance_partial.json",
    "customer_promo_activate.json",
}

#: Product webhook events (``webhooks.verify``) and the typed params of each notify kind.
PRODUCT_EVENTS: dict[str, type | None] = {
    "event_plan_changed_expired.json": None,
    "event_plan_changed_manual.json": None,
    "event_plan_changed_payment.json": None,
    "event_notify_payment_confirmed.json": PaymentConfirmedParams,
    "event_notify_expiring_7d.json": ExpiringParams,
    "event_notify_expiring_3d.json": ExpiringParams,
    "event_notify_expiring_1d.json": ExpiringParams,
    "event_notify_access_expired_followup_fallback.json": AccessExpiredFollowupParams,
    "event_notify_payment_reminder_fallback.json": PaymentReminderParams,
    "event_notify_unpaid_invoice_24h_fallback.json": PaymentReminderParams,
    "event_notify_payment_expired_fallback.json": PaymentExpiredParams,
}

#: Messenger-only events: never delivered to the product webhook.
MESSENGER_EVENTS = {
    "event_subscription_changed_expired.json",
    "event_subscription_changed_payment.json",
}

WEBHOOK_REQUESTS = {"webhook_product_request.json"}


def test_every_fixture_is_mapped() -> None:
    mapped = (
        set(SERVICE_CALLS)
        | set(CUSTOMER_CALLS)
        | set(PRODUCT_EVENTS)
        | MESSENGER_EVENTS
        | WEBHOOK_REQUESTS
    )
    present = set(_fixture_names())
    assert present, "no contract fixtures found"
    assert present - mapped == set(), "fixtures the SDK does not parse yet"
    assert mapped - present == set(), "mapped fixtures missing from the copy"


def test_crm_version_is_recorded() -> None:
    lines = (FIXTURES / "CRM_VERSION").read_text(encoding="utf-8").splitlines()
    fields = dict(line.split("=", 1) for line in lines if "=" in line)
    assert len(fields.get("commit", "")) == 40


def _mock(envelope: Any, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=envelope)

    return httpx.MockTransport(handler)


@pytest.mark.parametrize("name", sorted(SERVICE_CALLS))
async def test_service_fixture_parses(name: str) -> None:
    call, model = SERVICE_CALLS[name]
    async with ServiceClient(BASE_URL, "svc", transport=_mock(_load(name))) as crm:
        result = await call(crm)
    assert isinstance(result, model)


@pytest.mark.parametrize("name", sorted(CUSTOMER_CALLS))
async def test_customer_fixture_parses(name: str, ed25519_keys: tuple[bytes, bytes]) -> None:
    call, model = CUSTOMER_CALLS[name]
    signer = AssertionSigner(ed25519_keys[0], kid="test")
    status = 201 if name in CUSTOMER_CREATED else 200
    async with CustomerClient(
        BASE_URL,
        signer,
        account_public_id=ACCOUNT_PUBLIC_ID,
        actor_buyer_id=42,
        transport=_mock(_load(name), status),
    ) as customer:
        result = await call(customer)
    assert isinstance(result, model)


@pytest.mark.parametrize("name", sorted(PRODUCT_EVENTS))
def test_product_event_fixture_verifies(name: str) -> None:
    body, signature = _signed(name)
    event = webhooks.verify(body, signature, SECRET)
    assert not isinstance(event, GenericEvent)
    params_model = PRODUCT_EVENTS[name]
    if isinstance(event, NotifyEvent):
        assert event.payload.kind in KNOWN_NOTIFY_KINDS
        assert params_model is not None
        assert isinstance(event.payload.typed_params(), params_model)
    else:
        assert isinstance(event, PlanChangedEvent)
        assert params_model is None


@pytest.mark.parametrize("name", sorted(PRODUCT_EVENTS))
def test_product_event_tampered_body_fails(name: str) -> None:
    body, signature = _signed(name)
    tampered = body.replace(b'"account_id": 10', b'"account_id": 90', 1)
    assert tampered != body
    with pytest.raises(SignatureError):
        webhooks.verify(tampered, signature, SECRET)


@pytest.mark.parametrize("name", sorted(PRODUCT_EVENTS))
def test_raw_fixture_bytes_verify_too(name: str) -> None:
    # Signature is over whatever bytes arrived, not a canonical form.
    raw = (FIXTURES / name).read_bytes()
    event = webhooks.verify(raw, webhooks.compute_signature(raw, SECRET), SECRET)
    assert not isinstance(event, GenericEvent)


@pytest.mark.parametrize("name", sorted(MESSENGER_EVENTS))
def test_messenger_event_fixture_parses(name: str) -> None:
    envelope = _load(name)
    payload = SubscriptionChangedPayload.model_validate(envelope["payload"])
    assert payload.bot_id == 10
    # Should one ever reach the product webhook, it parses as an unknown type, not an error.
    body = _crm_body(envelope)
    event = webhooks.verify(body, webhooks.compute_signature(body, SECRET), SECRET)
    assert isinstance(event, GenericEvent)


def test_webhook_product_request_signature_matches() -> None:
    request = _load("webhook_product_request.json")
    raw = request["body"].encode("utf-8")
    signature = request["headers"][webhooks.SIGNATURE_HEADER]
    event = webhooks.verify(raw, signature, CONTRACT_WEBHOOK_SECRET)
    assert isinstance(event, PlanChangedEvent)
    assert event.payload.version == 5817
    assert request["method"] == "POST"
    assert request["headers"]["Content-Type"] == "application/json"


def test_known_notify_kinds_all_have_params_models() -> None:
    kinds = {_load(name)["payload"]["kind"] for name, model in PRODUCT_EVENTS.items() if model}
    assert kinds == KNOWN_NOTIFY_KINDS


# --------------------------------------------------------------------------- #
# Field-level checks for the shapes BossLink relies on
# --------------------------------------------------------------------------- #
def _event(name: str) -> Any:
    body, signature = _signed(name)
    return webhooks.verify(body, signature, SECRET)


def test_plan_changed_expired_is_free_without_until() -> None:
    event = _event("event_plan_changed_expired.json")
    assert isinstance(event, PlanChangedEvent)
    assert event.payload.plan == "free" and event.payload.plan_until is None


def test_plan_changed_manual_has_aware_until() -> None:
    event = _event("event_plan_changed_manual.json")
    assert isinstance(event, PlanChangedEvent)
    assert event.payload.plan == "agency"
    assert event.payload.plan_until is not None
    assert event.payload.plan_until.utcoffset() is not None


def test_payment_confirmed_params() -> None:
    event = _event("event_notify_payment_confirmed.json")
    assert isinstance(event, NotifyEvent) and event.payload.button is None
    params = event.payload.typed_params()
    assert isinstance(params, PaymentConfirmedParams)
    assert params.amount_minor == 29000 and params.currency == "RUB"
    assert [(p.product, p.plan, p.months) for p in params.plans] == [("cabinet", "pro", 1)]


def test_expiring_params_modules_are_key_title() -> None:
    event = _event("event_notify_expiring_1d.json")
    assert isinstance(event, NotifyEvent)
    params = event.payload.typed_params()
    assert isinstance(params, ExpiringParams)
    assert params.expires_date == date(2026, 10, 2)
    assert [(m.key, m.title) for m in params.modules] == [("cabinet.pro", "Кабинет Pro")]


def test_fallback_button_leads_to_support_bot() -> None:
    event = _event("event_notify_payment_reminder_fallback.json")
    assert isinstance(event, NotifyEvent)
    assert event.payload.button is not None and event.payload.button.text is None
    assert event.payload.button.url.startswith("https://t.me/socialtraff_support_bot?start=crm_")
    params = event.payload.typed_params()
    assert isinstance(params, PaymentReminderParams)
    assert params.pay_page_url and params.service == "Кабинет Pro"


def test_unknown_notify_kind_has_no_typed_params() -> None:
    envelope = _load("event_notify_expiring_1d.json")
    envelope["payload"]["kind"] = "something_new"
    envelope["payload"]["params"] = {"x": [1, 2]}
    body = _crm_body(envelope)
    event = webhooks.verify(body, webhooks.compute_signature(body, SECRET), SECRET)
    assert isinstance(event, NotifyEvent)
    assert event.payload.typed_params() is None


async def test_ai_key_mask_format() -> None:
    call, _ = SERVICE_CALLS["service_ai_key_stats.json"]
    async with ServiceClient(
        BASE_URL, "svc", transport=_mock(_load("service_ai_key_stats.json"))
    ) as crm:
        stats = await call(crm)
    assert stats.mask == "sk-or-…9f2c"
    assert stats.limit_usd is None and stats.limit_remaining_usd is None


async def test_payment_get_has_fx_rate_and_no_pay_url(ed25519_keys: tuple[bytes, bytes]) -> None:
    call, _ = CUSTOMER_CALLS["customer_billing_payment_get.json"]
    signer = AssertionSigner(ed25519_keys[0], kid="test")
    transport = _mock(_load("customer_billing_payment_get.json"))
    async with CustomerClient(
        BASE_URL, signer, ACCOUNT_PUBLIC_ID, 42, transport=transport
    ) as customer:
        payment = await call(customer)
    assert payment.fx_rate_rub_usd == Decimal("95.5")
    assert payment.web_return_url == "https://app.socialtraff.test/billing/return"
    assert not hasattr(payment, "pay_url")


async def _customer_result(name: str, ed25519_keys: tuple[bytes, bytes]) -> Any:
    call, _ = CUSTOMER_CALLS[name]
    signer = AssertionSigner(ed25519_keys[0], kid="test")
    status = 201 if name in CUSTOMER_CREATED else 200
    transport = _mock(_load(name), status)
    async with CustomerClient(
        BASE_URL, signer, ACCOUNT_PUBLIC_ID, 42, transport=transport
    ) as customer:
        return await call(customer)


async def test_referral_summary_has_bot_link(ed25519_keys: tuple[bytes, bytes]) -> None:
    summary = await _customer_result("customer_referrals.json", ed25519_keys)
    assert summary.ref_bot_link == "https://t.me/socialtraff_robot?start=ref_OWNER1"
    assert summary.ref_link == "https://socialtraff.com/?ref=OWNER1"


async def test_referral_summary_partner_fields(ed25519_keys: tuple[bytes, bytes]) -> None:
    summary = await _customer_result("customer_referrals.json", ed25519_keys)
    assert (summary.first_percent, summary.recurring_percent, summary.hold_days) == (40, 20, 14)
    assert summary.min_withdrawal_usd_cents == 2000
    assert summary.withdraw_methods == ["wallet"]
    assert [(c.code, c.kind) for c in summary.promo_codes] == [("OWNER1", "partner_auto")]
    assert summary.pending_withdrawal is None and summary.recent_accruals == []
    assert summary.on_hold_usd_cents == 0 and summary.spent_on_subscriptions_usd_cents == 0


async def test_partner_code_set(ed25519_keys: tuple[bytes, bytes]) -> None:
    code = await _customer_result("customer_referrals_code.json", ed25519_keys)
    assert (code.code, code.kind) == ("Owner_Promo", "partner_custom")


async def test_promo_activation_and_pending(ed25519_keys: tuple[bytes, bytes]) -> None:
    activation = await _customer_result("customer_promo_activate.json", ed25519_keys)
    assert activation.effect == "discount_percent" and activation.value == 15
    assert activation.first_subscription_only and activation.status == "pending"
    assert activation.created_at is not None and activation.created_at.utcoffset() is not None
    pending = await _customer_result("customer_promo.json", ed25519_keys)
    assert pending == [activation]


async def test_payment_paid_by_balance(ed25519_keys: tuple[bytes, bytes]) -> None:
    session = await _customer_result("customer_billing_payment_create_balance.json", ed25519_keys)
    assert session.status == "paid" and session.amount_rub_kopecks == 0
    assert session.pay_url is None and session.checkout_url is None
    assert (session.balance_spent_rub_kopecks, session.balance_spent_usd_cents) == (29000, 304)
    payment = await _customer_result("customer_billing_payment_get_balance.json", ed25519_keys)
    assert payment.provider == "balance" and payment.payment_method is None
    assert payment.invoiced_at is None and payment.paid_at is not None
    items_total = sum(item.price_rub_kopecks * item.quantity for item in payment.items)
    assert items_total - payment.balance_spent_rub_kopecks == payment.amount_rub_kopecks


async def test_payment_partly_paid_by_balance(ed25519_keys: tuple[bytes, bytes]) -> None:
    name = "customer_billing_payment_create_balance_partial.json"
    session = await _customer_result(name, ed25519_keys)
    assert session.status == "invoiced" and session.pay_url
    assert session.amount_rub_kopecks + session.balance_spent_rub_kopecks == 29000


async def test_products_fixture_items() -> None:
    envelope = _load("customer_billing_products.json")
    items = [CatalogProduct.model_validate(item) for item in envelope["data"]["items"]]
    assert {tuple(item.feature_keys) for item in items} == {("cabinet.pro",), ("privetka.pro",)}


async def test_service_catalog_equals_customer_products() -> None:
    call, _ = SERVICE_CALLS["service_catalog.json"]
    async with ServiceClient(
        BASE_URL, "svc", transport=_mock(_load("service_catalog.json"))
    ) as crm:
        items = await call(crm)
    assert all(isinstance(item, CatalogProduct) for item in items)
    assert _load("service_catalog.json")["data"] == _load("customer_billing_products.json")["data"]


def test_webhook_fixture_url_is_the_bosslink_route() -> None:
    assert _load("webhook_product_request.json")["url"].endswith("/api/v1/crm/webhook")


async def test_identity_import_fixture_counts_chats() -> None:
    call, _ = SERVICE_CALLS["service_identity_import.json"]
    async with ServiceClient(
        BASE_URL, "svc", transport=_mock(_load("service_identity_import.json"))
    ) as crm:
        result = await call(crm)
    assert (result.buyers, result.accounts, result.members, result.chats) == (1, 1, 1, 1)


async def test_put_chats_fixture_counters() -> None:
    call, _ = SERVICE_CALLS["service_identity_put_chats.json"]
    async with ServiceClient(
        BASE_URL, "svc", transport=_mock(_load("service_identity_put_chats.json"))
    ) as crm:
        result = await call(crm)
    assert result.account_id == 2003
    assert (result.active, result.linked, result.reopened) == (2, 2, 0)
    assert (result.unlinked, result.unchanged) == (1, 0)


async def test_plans_get_fixture_free_privetka() -> None:
    call, _ = SERVICE_CALLS["service_plans_get.json"]
    async with ServiceClient(
        BASE_URL, "svc", transport=_mock(_load("service_plans_get.json"))
    ) as crm:
        plans = await call(crm)
    assert plans.plans["cabinet"].plan == "pro"
    assert plans.plans["privetka"].plan is None and plans.plans["privetka"].expires_at is None


# --------------------------------------------------------------------------- #
# Optional: byte comparison with a CRM checkout (CI with CRM_CHECKOUT set)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not os.environ.get("CRM_CHECKOUT"), reason="CRM_CHECKOUT not set")
def test_fixtures_equal_crm_checkout() -> None:
    crm = Path(os.environ["CRM_CHECKOUT"]) / "tests" / "contract"
    theirs = {path.name for path in crm.glob("*.json")}
    assert theirs == set(_fixture_names())
    for name in sorted(theirs):
        ours = (FIXTURES / name).read_bytes().replace(b"\r\n", b"\n")
        assert ours == (crm / name).read_bytes().replace(b"\r\n", b"\n"), name
