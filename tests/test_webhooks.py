from __future__ import annotations

import json
from datetime import timedelta

import pytest

from socialtraff_crm import (
    ConfigError,
    GenericEvent,
    NotifyEvent,
    PlanChangedEvent,
    SignatureError,
    ValidationError,
    webhooks,
)

SECRET = "whsec-test"


def body(event_type: str, payload: dict) -> bytes:
    envelope = {"event_id": "evt-1", "event_type": event_type, "payload": payload}
    return json.dumps(envelope, ensure_ascii=False).encode()


def plan_changed(plan_until: str | None = "2026-10-25T12:00:00+03:00") -> bytes:
    return body(
        "product.plan_changed",
        {
            "account_id": 17,
            "product": "cabinet",
            "plan": "pro",
            "plan_until": plan_until,
            "version": 5,
        },
    )


def signed(raw: bytes) -> str:
    return webhooks.compute_signature(raw, SECRET)


def test_good_signature_parses_plan_changed() -> None:
    raw = plan_changed()
    event = webhooks.verify(raw, signed(raw), SECRET)
    assert isinstance(event, PlanChangedEvent)
    assert event.event_id == "evt-1"
    assert event.payload.account_id == 17
    assert event.payload.plan == "pro"
    assert event.payload.version == 5
    assert event.payload.plan_until is not None
    assert event.payload.plan_until.utcoffset() == timedelta(hours=3)


def test_plan_until_may_be_null() -> None:
    raw = plan_changed(None)
    event = webhooks.verify(raw, signed(raw), SECRET)
    assert isinstance(event, PlanChangedEvent)
    assert event.payload.plan_until is None


def test_notify_event() -> None:
    raw = body(
        "product.notify",
        {
            "account_id": 3,
            "kind": "payment_reminder_fallback",
            "params": {"amount": 990},
            "button": {"text": "Оплатить", "url": "https://t.me/socialtraff_support_bot?start=x"},
        },
    )
    event = webhooks.verify(raw, signed(raw), SECRET)
    assert isinstance(event, NotifyEvent)
    assert event.payload.params == {"amount": 990}
    assert event.payload.button is not None and event.payload.button.text == "Оплатить"


def test_bad_signature_rejected() -> None:
    raw = plan_changed()
    with pytest.raises(SignatureError):
        webhooks.verify(raw, "0" * 64, SECRET)
    with pytest.raises(SignatureError):
        webhooks.verify(raw, "", SECRET)
    with pytest.raises(SignatureError):
        webhooks.verify(raw, signed(raw), "other-secret")


def test_tampered_body_rejected() -> None:
    raw = plan_changed()
    signature = signed(raw)
    tampered = raw.replace(b'"pro"', b'"agency"')
    assert tampered != raw
    with pytest.raises(SignatureError):
        webhooks.verify(tampered, signature, SECRET)


def test_naive_datetime_rejected() -> None:
    raw = plan_changed("2026-10-25T12:00:00")
    with pytest.raises(ValidationError) as info:
        webhooks.verify(raw, signed(raw), SECRET)
    assert info.value.details


def test_unknown_event_type_parses_as_generic() -> None:
    raw = body("product.something_new", {"foo": [1, 2]})
    event = webhooks.verify(raw, signed(raw), SECRET)
    assert isinstance(event, GenericEvent)
    assert event.event_type == "product.something_new"
    assert event.payload == {"foo": [1, 2]}


def test_known_type_with_bad_payload_does_not_fall_back() -> None:
    raw = body("product.plan_changed", {"account_id": 1})
    with pytest.raises(ValidationError):
        webhooks.verify(raw, signed(raw), SECRET)


def test_signed_non_json_body_is_validation_error() -> None:
    raw = b"not json"
    with pytest.raises(ValidationError):
        webhooks.verify(raw, signed(raw), SECRET)


def test_empty_secret_is_config_error() -> None:
    with pytest.raises(ConfigError):
        webhooks.verify(plan_changed(), "00", "")
