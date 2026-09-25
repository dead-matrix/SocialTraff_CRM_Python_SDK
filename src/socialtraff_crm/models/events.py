"""CRM -> product webhook events (``{event_id, event_type, payload}`` envelope)."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

import pydantic
from pydantic import Discriminator, Field, Tag, TypeAdapter

from ..errors import ValidationError
from .common import AwareDatetime, CrmModel

__all__ = [
    "EVENT_ADAPTER",
    "KNOWN_NOTIFY_KINDS",
    "AccessExpiredFollowupParams",
    "CrmEvent",
    "ExpiringParams",
    "GenericEvent",
    "NotifyButton",
    "NotifyEvent",
    "NotifyModule",
    "NotifyParams",
    "NotifyPayload",
    "PaidPlan",
    "PaymentConfirmedParams",
    "PaymentExpiredParams",
    "PaymentReminderParams",
    "PlanChangedEvent",
    "PlanChangedPayload",
    "SubscriptionChangedPayload",
]

PLAN_CHANGED = "product.plan_changed"
NOTIFY = "product.notify"
_GENERIC_TAG = "__generic__"

# Reference list only: ``NotifyPayload.kind`` stays ``str`` so a kind added in CRM does not
# break parsing in an older SDK. Fallback kinds are ``"<messenger event_type>_fallback"``,
# sent when the account owner has no messenger chat; ``params`` then carry that event payload.
KNOWN_NOTIFY_KINDS = frozenset(
    {
        "payment_confirmed",
        "expiring_7d",
        "expiring_3d",
        "expiring_1d",
        "access_expired_followup_fallback",
        "payment_reminder_fallback",
        "unpaid_invoice_24h_fallback",
        "payment_expired_fallback",
    }
)


class PlanChangedPayload(CrmModel):
    account_id: int
    product: Literal["cabinet", "privetka"]
    plan: str
    plan_until: AwareDatetime | None
    # Monotonic per account/product; the consumer must ignore events older than its state.
    version: int


class NotifyButton(CrmModel):
    """Link button. CRM sends only ``url`` today: the caption comes from the product locale."""

    text: str | None = None
    url: str


class NotifyModule(CrmModel):
    """A plan in a notice: ``key`` is ``<product>.<plan>`` (``cabinet.pro``), ``title`` is Russian.

    Localize by ``key``; ``title`` is a fallback for a key the product does not know.
    """

    key: str
    title: str


class PaidPlan(CrmModel):
    product: str
    plan: str
    months: int


class PaymentConfirmedParams(CrmModel):
    """``payment_confirmed``: ``amount_minor`` is kopecks (29000 = 290 RUB)."""

    payment_uuid: str
    amount_minor: int
    currency: str
    plans: list[PaidPlan] = Field(default_factory=list)


class ExpiringParams(CrmModel):
    """``expiring_7d``, ``expiring_3d``, ``expiring_1d``: plans that end on ``expires_date``."""

    modules: list[NotifyModule] = Field(default_factory=list)
    expires_date: date


class AccessExpiredFollowupParams(CrmModel):
    """``access_expired_followup_fallback``; ``kind``: ``expired_after_1d``/``expired_after_3d``."""

    kind: str
    modules: list[NotifyModule] = Field(default_factory=list)
    expires_date: date
    photo_url: str | None = None
    idempotency_key: str | None = None


class PaymentReminderParams(CrmModel):
    """``payment_reminder_fallback`` (2 h) and ``unpaid_invoice_24h_fallback`` (24 h).

    ``service`` is the Russian titles of the invoice lines, ``pay_page_url`` the provider page
    (else the CRM storefront), ``amount_minor`` kopecks.
    """

    amount_minor: int
    service: str | None = None
    pay_page_url: str | None = None
    invoice_uuid: str


class PaymentExpiredParams(CrmModel):
    """``payment_expired_fallback``: no ``service`` and no ``pay_page_url`` (CRM D89)."""

    amount_minor: int
    provider: str | None = None
    invoice_uuid: str


NotifyParams = (
    PaymentConfirmedParams
    | ExpiringParams
    | AccessExpiredFollowupParams
    | PaymentReminderParams
    | PaymentExpiredParams
)

_PARAMS_BY_KIND: dict[str, type[CrmModel]] = {
    "payment_confirmed": PaymentConfirmedParams,
    "expiring_7d": ExpiringParams,
    "expiring_3d": ExpiringParams,
    "expiring_1d": ExpiringParams,
    "access_expired_followup_fallback": AccessExpiredFollowupParams,
    "payment_reminder_fallback": PaymentReminderParams,
    "unpaid_invoice_24h_fallback": PaymentReminderParams,
    "payment_expired_fallback": PaymentExpiredParams,
}


class NotifyPayload(CrmModel):
    account_id: int
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)
    button: NotifyButton | None = None

    def typed_params(self) -> NotifyParams | None:
        """``params`` as the model of a known ``kind``; ``None`` for a kind this SDK does not know.

        ``params`` stays a plain dict on purpose: a new kind or a new key from CRM must not break
        webhook parsing. Raises ``ValidationError`` if a known kind has a wrong shape.
        """
        model = _PARAMS_BY_KIND.get(self.kind)
        if model is None:
            return None
        try:
            parsed: NotifyParams = model.model_validate(self.params)  # type: ignore[assignment]
        except pydantic.ValidationError as exc:
            raise ValidationError(
                f"notify params of kind {self.kind!r}: {exc.error_count()} error(s)",
                details=exc.errors(include_url=False, include_input=False),
            ) from exc
        return parsed


class SubscriptionChangedPayload(CrmModel):
    """Payload of ``subscription_changed``.

    Messenger-only: CRM publishes it to the messenger outbox, never to the product webhook,
    so ``webhooks.verify`` does not parse it and it is not part of ``CrmEvent``.
    """

    account_id: int
    user_id: int
    # Brand bot of the event (10 for SocialTraff); absent in payloads of an older CRM.
    bot_id: int | None = None
    has_active_subscription: bool
    # Always false in CRM today; kept for the shape shared with the Go SDK.
    frozen: bool = False
    reason: Literal["plan_changed", "expired"]


class _EventBase(CrmModel):
    event_id: str
    event_type: str


class PlanChangedEvent(_EventBase):
    event_type: Literal["product.plan_changed"]
    payload: PlanChangedPayload


class NotifyEvent(_EventBase):
    event_type: Literal["product.notify"]
    payload: NotifyPayload


class GenericEvent(_EventBase):
    """Event of a type this SDK version does not know; payload is kept as-is."""

    payload: dict[str, Any]


_KNOWN_TYPES = frozenset({PLAN_CHANGED, NOTIFY})


def _event_tag(value: Any) -> str | None:
    if isinstance(value, dict):
        event_type = value.get("event_type")
    else:
        event_type = getattr(value, "event_type", None)
    if not isinstance(event_type, str):
        return None
    # Known types are validated strictly; anything else falls back to GenericEvent.
    return event_type if event_type in _KNOWN_TYPES else _GENERIC_TAG


CrmEvent = Annotated[
    Annotated[PlanChangedEvent, Tag(PLAN_CHANGED)]
    | Annotated[NotifyEvent, Tag(NOTIFY)]
    | Annotated[GenericEvent, Tag(_GENERIC_TAG)],
    Discriminator(_event_tag),
]

EVENT_ADAPTER: TypeAdapter[PlanChangedEvent | NotifyEvent | GenericEvent] = TypeAdapter(CrmEvent)
