"""CRM -> product webhook events (``{event_id, event_type, payload}`` envelope)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Discriminator, Field, Tag, TypeAdapter

from .common import AwareDatetime, CrmModel

__all__ = [
    "EVENT_ADAPTER",
    "CrmEvent",
    "GenericEvent",
    "NotifyButton",
    "NotifyEvent",
    "NotifyPayload",
    "PlanChangedEvent",
    "PlanChangedPayload",
]

PLAN_CHANGED = "product.plan_changed"
NOTIFY = "product.notify"
_GENERIC_TAG = "__generic__"


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
