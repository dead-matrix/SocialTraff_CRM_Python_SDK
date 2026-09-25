"""Customer plane namespaces: ``billing``, ``ai`` and ``referrals``.

Each method asks for exactly the scope its CRM route requires, so a leaked assertion
opens one action instead of the whole plane.
"""

from __future__ import annotations

from collections.abc import Awaitable, Iterable, Mapping
from typing import Any, Protocol
from urllib.parse import quote

import pydantic

from .errors import ValidationError
from .models.common import CrmModel
from .models.customer import (
    AiBalance,
    AiHistoryPage,
    AiUsage,
    CatalogProduct,
    CheckoutSession,
    Payment,
    PaymentPage,
    ReferralSummary,
    Subscription,
    WithdrawalPage,
    WithdrawalRequest,
)

__all__ = ["AiApi", "BillingApi", "ReferralsApi"]

SCOPE_BILLING_READ = "billing:read"
SCOPE_BILLING_WRITE = "billing:write"
SCOPE_AI_READ = "ai:read"
SCOPE_REFERRALS_READ = "referrals:read"
SCOPE_REFERRALS_WRITE = "referrals:write"


class _ProductList(CrmModel):
    items: list[CatalogProduct]


class _Requester(Protocol):
    def __call__(
        self,
        method: str,
        path: str,
        *,
        scopes: Iterable[str],
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        idempotency_key: str | None = None,
    ) -> Awaitable[Any]: ...


def _parse[T: pydantic.BaseModel](model: type[T], data: Any, label: str) -> T:
    try:
        return model.model_validate(data)
    except pydantic.ValidationError as exc:
        raise ValidationError(
            f"{label}: unexpected response: {exc.error_count()} error(s)",
            details=exc.errors(include_url=False, include_input=False),
        ) from exc


def _page_params(cursor: str | None, limit: int | None, **extra: Any) -> dict[str, Any]:
    params: dict[str, Any] = {key: value for key, value in extra.items() if value is not None}
    if cursor is not None:
        params["cursor"] = cursor
    if limit is not None:
        params["limit"] = limit
    return params


class _Namespace:
    def __init__(self, request: _Requester) -> None:
        self._request = request


class BillingApi(_Namespace):
    async def products(self) -> list[CatalogProduct]:
        """Storefront catalogue (``billing:read``)."""
        data = await self._request("GET", "/billing/products", scopes=[SCOPE_BILLING_READ])
        return _parse(_ProductList, data, "billing.products").items

    async def subscription(self) -> Subscription:
        """Features and products the account has now (``billing:read``)."""
        data = await self._request("GET", "/billing/subscription", scopes=[SCOPE_BILLING_READ])
        return _parse(Subscription, data, "billing.subscription")

    async def create_payment(
        self,
        product_id: int,
        *,
        quantity: int,
        provider: str,
        return_to: str,
        payment_method: str | None = None,
        ai_function: str | None = None,
        idempotency_key: str | None = None,
    ) -> CheckoutSession:
        """Create a draft payment (``billing:write``, HTTP 201).

        ``payment_method`` is sent only for ``provider="platega"`` and ``ai_function`` only for
        AI token packages: CRM rejects either field where it does not apply.
        """
        body: dict[str, Any] = {
            "product_id": product_id,
            "quantity": quantity,
            "provider": provider,
            "return_to": return_to,
        }
        if payment_method is not None:
            body["payment_method"] = payment_method
        if ai_function is not None:
            body["ai_function"] = ai_function
        data = await self._request(
            "POST",
            "/billing/payments",
            scopes=[SCOPE_BILLING_WRITE],
            json=body,
            idempotency_key=idempotency_key,
        )
        return _parse(CheckoutSession, data, "billing.create_payment")

    async def list_payments(
        self, *, cursor: str | None = None, limit: int | None = None
    ) -> PaymentPage:
        """Payment history, newest first (``billing:read``)."""
        data = await self._request(
            "GET",
            "/billing/payments",
            scopes=[SCOPE_BILLING_READ],
            params=_page_params(cursor, limit),
        )
        return _parse(PaymentPage, data, "billing.list_payments")

    async def get_payment(self, payment_public_id: str) -> Payment:
        """One payment of the account (``billing:read``); a foreign one is ``NotFoundError``."""
        data = await self._request(
            "GET",
            f"/billing/payments/{quote(payment_public_id, safe='')}",
            scopes=[SCOPE_BILLING_READ],
        )
        return _parse(Payment, data, "billing.get_payment")


class AiApi(_Namespace):
    async def balance(self) -> AiBalance:
        """Balance per AI function and key mode (``ai:read``)."""
        data = await self._request("GET", "/ai/balance", scopes=[SCOPE_AI_READ])
        return _parse(AiBalance, data, "ai.balance")

    async def history(
        self,
        *,
        function: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> AiHistoryPage:
        """Debits, newest first; all functions when ``function`` is omitted (``ai:read``)."""
        data = await self._request(
            "GET",
            "/ai/history",
            scopes=[SCOPE_AI_READ],
            params=_page_params(cursor, limit, function=function),
        )
        return _parse(AiHistoryPage, data, "ai.history")

    async def usage(self, *, date_from: str | None = None, date_to: str | None = None) -> AiUsage:
        """Daily AI spending (``ai:read``). Dates are ``YYYY-MM-DD``; CRM defaults to 30 days."""
        data = await self._request(
            "GET",
            "/ai/usage",
            scopes=[SCOPE_AI_READ],
            params={
                key: value
                for key, value in (("from", date_from), ("to", date_to))
                if value is not None
            },
        )
        return _parse(AiUsage, data, "ai.usage")


class ReferralsApi(_Namespace):
    async def get(self) -> ReferralSummary:
        """Referral link, rate, counters and money (``referrals:read``)."""
        data = await self._request("GET", "/referrals", scopes=[SCOPE_REFERRALS_READ])
        return _parse(ReferralSummary, data, "referrals.get")

    async def withdrawals(
        self, *, cursor: str | None = None, limit: int | None = None
    ) -> WithdrawalPage:
        """Withdrawal requests, newest first (``referrals:read``)."""
        data = await self._request(
            "GET",
            "/referrals/withdrawals",
            scopes=[SCOPE_REFERRALS_READ],
            params=_page_params(cursor, limit),
        )
        return _parse(WithdrawalPage, data, "referrals.withdrawals")

    async def withdraw(
        self, method: str, *, idempotency_key: str | None = None
    ) -> WithdrawalRequest:
        """Request payout of the whole available balance (``referrals:write``, HTTP 202).

        CRM takes no amount on purpose: it always withdraws everything available.
        """
        data = await self._request(
            "POST",
            "/referrals/withdraw",
            scopes=[SCOPE_REFERRALS_WRITE],
            json={"method": method},
            idempotency_key=idempotency_key,
        )
        return _parse(WithdrawalRequest, data, "referrals.withdraw")
