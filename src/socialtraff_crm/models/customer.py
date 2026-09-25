"""Customer plane responses (``/api/v1/customer/...``).

Money fields keep CRM units in their names: ``_rub_kopecks``, ``_usd_cents``, ``_usd_micro``.
Rouble turnover and dollar commissions are different currencies and must not be summed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import Field

from .common import AwareDatetime, CrmModel

__all__ = [
    "AiBalance",
    "AiFunctionBalance",
    "AiHistoryItem",
    "AiHistoryPage",
    "AiUsage",
    "AiUsageItem",
    "CatalogProduct",
    "CheckoutSession",
    "Payment",
    "PaymentItem",
    "PaymentPage",
    "ReferralSummary",
    "Subscription",
    "SubscriptionFeature",
    "Withdrawal",
    "WithdrawalPage",
    "WithdrawalRequest",
]


class CatalogProduct(CrmModel):
    product_id: int
    title: str
    kind: str
    price_rub_kopecks: int
    price_usd_cents: int | None = None
    feature_keys: list[str] = Field(default_factory=list)
    billed_per_month: bool
    ai_tokens: int | None = None
    # Present only for AI token packages: ``create_payment`` then requires one of them.
    ai_functions: list[str] | None = None


class SubscriptionFeature(CrmModel):
    key: str
    title: str
    ends_at: AwareDatetime | None = None


class Subscription(CrmModel):
    """No subscription is a normal answer (``active=False``), not a 404."""

    active: bool
    ends_at: AwareDatetime | None = None
    frozen: bool = False
    frozen_at: AwareDatetime | None = None
    features: list[SubscriptionFeature] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)


class CheckoutSession(CrmModel):
    """Payment with its provider invoice already issued (CRM answers ``status="invoiced"``).

    Send the buyer to ``pay_url`` (the provider page). ``checkout_url`` is the optional CRM
    storefront and is ``None`` when the storefront is not configured.
    """

    payment_public_id: str
    status: str
    pay_url: str | None = None
    checkout_url: str | None = None
    amount_rub_kopecks: int
    return_to: str
    ai_tokens: int | None = None
    function: str | None = None


class PaymentItem(CrmModel):
    title: str
    quantity: int
    price_rub_kopecks: int


class Payment(CrmModel):
    payment_public_id: str
    status: str
    amount_rub_kopecks: int
    currency: str
    fx_rate_rub_usd: Decimal | None = None
    description: str | None = None
    provider: str | None = None
    payment_method: str | None = None
    items: list[PaymentItem] = Field(default_factory=list)
    created_at: AwareDatetime | None = None
    invoiced_at: AwareDatetime | None = None
    paid_at: AwareDatetime | None = None
    # Only ``billing.get_payment`` returns these two.
    web_return_url: str | None = None
    checkout_url: str | None = None


class PaymentPage(CrmModel):
    items: list[Payment]
    next_cursor: str | None = None


class AiFunctionBalance(CrmModel):
    function: str
    title: str
    # When true, ``balance_tokens`` is a placeholder and should be shown as "unlimited".
    unlimited: bool
    balance_usd_micro: int
    balance_tokens: int
    base_remaining_tokens: int
    package_remaining_tokens: int
    overdraft_tokens: int
    est_generations: int
    est_tokens_per_gen: int
    key_mode: str


class AiBalance(CrmModel):
    tokens_per_usd: int
    functions: list[AiFunctionBalance]


class AiHistoryItem(CrmModel):
    at: AwareDatetime | None = None
    function: str
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd_micro: int
    charged_usd_micro: int
    charged_tokens: int
    source: str | None = None


class AiHistoryPage(CrmModel):
    items: list[AiHistoryItem]
    next_cursor: str | None = None


class AiUsageItem(CrmModel):
    day: date
    function: str
    cost_usd_micro: int
    charged_usd_micro: int
    # Raw provider tokens, not the balance "tokens" unit.
    tokens: int
    generations: int


class AiUsage(CrmModel):
    """Sparse daily series: days without spending are omitted, both bounds inclusive."""

    date_from: date = Field(alias="from")
    date_to: date = Field(alias="to")
    bucket: str
    items: list[AiUsageItem]


class ReferralSummary(CrmModel):
    ref_link: str
    percent: int
    registrations: int
    referred_payments_count: int
    referred_turnover_rub_kopecks: int
    earned_usd_cents: int
    available_usd_cents: int
    withdrawn_wallet_usd_cents: int
    withdrawn_subscription_usd_cents: int
    min_withdrawal_usd_cents: int
    withdraw_methods: list[str]


class Withdrawal(CrmModel):
    withdrawal_public_id: str
    status: str
    method: str | None = None
    requested_usd_cents: int
    paid_usd_cents: int
    created_at: AwareDatetime | None = None
    processed_at: AwareDatetime | None = None


class WithdrawalPage(CrmModel):
    items: list[Withdrawal]
    next_cursor: str | None = None


class WithdrawalRequest(CrmModel):
    """Accepted request (HTTP 202): staff pays it out later, the whole available balance."""

    withdrawal_public_id: str
    status: str
    amount_usd_cents: int
    method: str
