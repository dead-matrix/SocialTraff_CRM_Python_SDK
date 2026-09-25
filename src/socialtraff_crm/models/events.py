"""CRM -> product webhook events (``{event_id, event_type, payload}`` envelope)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Discriminator, Field, Tag, TypeAdapter

from .common import AwareDatetime, CrmModel

__all__ = [
    "EVENT_ADAPTER",
    "KNOWN_NOTIFY_KINDS",
    "CrmEvent",
    "GenericEvent",
    "NotifyButton",
    "NotifyEvent",
    "NotifyPayload",
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
    text: str | None = None
    url: str


class NotifyPayload(CrmModel):
    account_id: int
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)
    button: NotifyButton | None = None


class SubscriptionChangedPayload(CrmModel):
    """Payload of ``subscription_changed``.

    Messenger-only: CRM publishes it to the messenger outbox, never to the product webhook,
    so ``webhooks.verify`` does not parse it and it is not part of ``CrmEvent``.
    """

    account_id: int
    user_id: int
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
