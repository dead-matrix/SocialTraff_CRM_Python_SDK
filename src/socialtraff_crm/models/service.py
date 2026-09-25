"""Service plane responses (``/api/internal/...``).

``AiKeyStats`` is also returned by the customer plane (``GET /api/v1/customer/ai/key``):
both routes serve the same CRM view, so there is one model for both.
"""

from __future__ import annotations

from pydantic import Field

from .common import AwareDatetime, CrmModel

__all__ = [
    "Account",
    "AccountPlans",
    "AiKey",
    "AiKeyStats",
    "Buyer",
    "CustomerId",
    "IdentityImportResult",
    "Member",
    "PlanSlot",
    "PlansImportResult",
    "PlansPage",
]


class Buyer(CrmModel):
    buyer_id: int
    tg_id: int | None = None
    email: str | None = None
    display_name: str | None = None
    ref_code: str | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    # True when this call inserted the buyer, False when it updated or matched an existing one.
    created: bool


class Account(CrmModel):
    account_id: int
    title: str
    owner_buyer_id: int
    is_personal: bool
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    created: bool


class Member(CrmModel):
    """Membership row.

    ``remove_member`` on a membership CRM never had answers with ``role=None`` and no
    ``joined_at``/``created``: removal is idempotent and not an error.
    """

    account_id: int
    buyer_id: int
    role: str | None = None
    joined_at: AwareDatetime | None = None
    removed_at: AwareDatetime | None = None
    created: bool | None = None


class CustomerId(CrmModel):
    account_id: int
    public_customer_id: str


class IdentityImportResult(CrmModel):
    buyers: int
    accounts: int
    members: int


class PlanSlot(CrmModel):
    """Current plan of one category; ``plan=None`` means free."""

    plan: str | None = None
    expires_at: AwareDatetime | None = None


class AccountPlans(CrmModel):
    account_id: int
    # ``version`` and ``updated_at`` are None for an account that never had a plan row.
    version: int | None = None
    updated_at: AwareDatetime | None = None
    plans: dict[str, PlanSlot] = Field(default_factory=dict)


class PlansPage(CrmModel):
    items: list[AccountPlans]
    next_cursor: str | None = None


class PlansImportResult(CrmModel):
    imported: int
    unchanged: int


class AiKey(CrmModel):
    # The provider key is a live credential: keep it out of repr, logs and tracebacks.
    secret: str = Field(repr=False)
    key_mode: str
    source: str


class AiKeyStats(CrmModel):
    """Mask and spending of the account AI key; the secret itself is never returned here."""

    mask: str
    usage_usd: float
    # None means the key has no spending limit, not a zero limit.
    limit_usd: float | None = None
    limit_remaining_usd: float | None = None
    disabled: bool
