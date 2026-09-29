"""Service plane namespaces: ``identity``, ``plans``, ``catalog`` and ``ai``.

Every write here is idempotent on the CRM side (a repeat with the same body answers 200 and
changes nothing), so PUT/DELETE are retried freely and imports become retryable with an
``idempotency_key``.
"""

from __future__ import annotations

import enum
from collections.abc import Awaitable, Iterable, Mapping
from datetime import datetime
from typing import Any, Final, Protocol
from urllib.parse import quote

from ._customer_api import _page_params, _parse, _ProductList
from .errors import ValidationError
from .models.customer import CatalogProduct
from .models.service import (
    Account,
    AccountChatsResult,
    AccountPlans,
    AiKey,
    AiKeyStats,
    Buyer,
    CustomerId,
    IdentityImportResult,
    Member,
    PlansImportResult,
    PlansPage,
)

__all__ = ["UNSET", "CatalogApi", "IdentityApi", "PlansApi", "ServiceAiApi"]


class _Unset(enum.Enum):
    UNSET = "UNSET"

    def __repr__(self) -> str:
        return "UNSET"


# ``put_buyer`` sends only the fields that were passed: CRM keeps an absent field and
# erases one sent as null, so "not passed" and ``None`` must stay distinguishable.
UNSET: Final = _Unset.UNSET


class _Requester(Protocol):
    def __call__(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        idempotency_key: str | None = None,
    ) -> Awaitable[Any]: ...


def _id(value: int) -> str:
    return quote(str(value), safe="")


def _aware_iso(value: datetime, label: str) -> str:
    # CRM reads a naive value as Moscow time; rejecting it here avoids a silent 3-hour shift.
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"{label} must be timezone-aware")
    return value.isoformat()


def _jsonable(item: Mapping[str, Any], label: str) -> dict[str, Any]:
    return {
        key: _aware_iso(value, f"{label}.{key}") if isinstance(value, datetime) else value
        for key, value in item.items()
    }


class _Namespace:
    def __init__(self, request: _Requester) -> None:
        self._request = request


class IdentityApi(_Namespace):
    async def put_buyer(
        self,
        buyer_id: int,
        *,
        tg_id: int | _Unset | None = UNSET,
        email: str | _Unset | None = UNSET,
        display_name: str | _Unset | None = UNSET,
        refer: str | _Unset | None = UNSET,
        landing: str | _Unset | None = UNSET,
    ) -> Buyer:
        """Create or update a buyer. Omitted fields are kept, an explicit ``None`` erases."""
        values = {
            "tg_id": tg_id,
            "email": email,
            "display_name": display_name,
            "refer": refer,
            "landing": landing,
        }
        body = {key: value for key, value in values.items() if value is not UNSET}
        data = await self._request("PUT", f"/identity/buyers/{_id(buyer_id)}", json=body)
        return _parse(Buyer, data, "identity.put_buyer")

    async def put_account(
        self,
        account_id: int,
        *,
        title: str,
        owner_buyer_id: int,
        is_personal: bool,
        created_at: datetime | None = None,
    ) -> Account:
        """Create or update an account; ``created_at`` must be timezone-aware."""
        body: dict[str, Any] = {
            "title": title,
            "owner_buyer_id": owner_buyer_id,
            "is_personal": is_personal,
        }
        if created_at is not None:
            body["created_at"] = _aware_iso(created_at, "created_at")
        data = await self._request("PUT", f"/identity/accounts/{_id(account_id)}", json=body)
        return _parse(Account, data, "identity.put_account")

    async def put_member(self, account_id: int, buyer_id: int, role: str) -> Member:
        """Add a buyer to an account or change the role; restores a removed membership."""
        data = await self._request(
            "PUT",
            f"/identity/accounts/{_id(account_id)}/members/{_id(buyer_id)}",
            json={"role": role},
        )
        return _parse(Member, data, "identity.put_member")

    async def remove_member(self, account_id: int, buyer_id: int) -> Member:
        """Soft-remove a membership; an absent one answers 200 as well."""
        data = await self._request(
            "DELETE", f"/identity/accounts/{_id(account_id)}/members/{_id(buyer_id)}"
        )
        return _parse(Member, data, "identity.remove_member")

    async def put_account_chats(
        self, account_id: int, chats: Iterable[Mapping[str, Any]]
    ) -> AccountChatsResult:
        """Replace the set of Telegram chats linked to an account.

        Items are ``{tg_chat_id, type, linked_at?}``; ``linked_at`` must be timezone-aware.
        The list is the full desired state: chats missing from it are unlinked, so an empty
        list unlinks all of them.
        """
        body = {"chats": [_jsonable(item, "chats") for item in chats]}
        data = await self._request("PUT", f"/identity/accounts/{_id(account_id)}/chats", json=body)
        return _parse(AccountChatsResult, data, "identity.put_account_chats")

    async def issue_customer_id(self, account_id: int) -> CustomerId:
        """Public customer id of the account, issued on the first call and stable after."""
        data = await self._request("POST", f"/identity/accounts/{_id(account_id)}/customer-id")
        return _parse(CustomerId, data, "identity.issue_customer_id")

    async def import_(
        self,
        buyers: Iterable[Mapping[str, Any]] = (),
        accounts: Iterable[Mapping[str, Any]] = (),
        members: Iterable[Mapping[str, Any]] = (),
        chats: Iterable[Mapping[str, Any]] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> IdentityImportResult:
        """Bulk upsert in one CRM transaction.

        Items use the fields of ``put_buyer``/``put_account``/``put_member`` plus their ids
        (``buyer_id``, ``account_id``); datetimes must be timezone-aware. ``chats`` items are
        ``{account_id, tg_chat_id, type, linked_at, unlinked_at?}``.

        ``chats`` goes into the body only when it is passed and non-empty: a CRM without
        account chats answers 422 to the key, and an empty import list carries nothing anyway.
        """
        body = {
            "buyers": [_jsonable(item, "buyers") for item in buyers],
            "accounts": [_jsonable(item, "accounts") for item in accounts],
            "members": [_jsonable(item, "members") for item in members],
        }
        chat_items = [_jsonable(item, "chats") for item in chats or ()]
        if chat_items:
            body["chats"] = chat_items
        data = await self._request(
            "POST", "/identity/import", json=body, idempotency_key=idempotency_key
        )
        return _parse(IdentityImportResult, data, "identity.import")


class PlansApi(_Namespace):
    async def import_(
        self, items: Iterable[Mapping[str, Any]], *, idempotency_key: str | None = None
    ) -> PlansImportResult:
        """Import plan states: ``{account_id, category, plan, expires_at}`` per item.

        ``expires_at`` must be timezone-aware: without an offset the plan end is ambiguous.
        """
        body = {"items": [_jsonable(item, "items") for item in items]}
        data = await self._request(
            "POST", "/plans/import", json=body, idempotency_key=idempotency_key
        )
        return _parse(PlansImportResult, data, "plans.import")

    async def get(self, account_id: int) -> AccountPlans:
        """Current plans of one account; an unknown account is ``NotFoundError``."""
        data = await self._request("GET", f"/plans/{_id(account_id)}")
        return _parse(AccountPlans, data, "plans.get")

    async def list_updated(
        self,
        updated_since: datetime,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> PlansPage:
        """Accounts whose plans changed since ``updated_since`` (timezone-aware)."""
        data = await self._request(
            "GET",
            "/plans",
            params=_page_params(
                cursor, limit, updated_since=_aware_iso(updated_since, "updated_since")
            ),
        )
        return _parse(PlansPage, data, "plans.list_updated")


class CatalogApi(_Namespace):
    async def get(self) -> list[CatalogProduct]:
        """Storefront catalogue without an account (``GET /api/internal/catalog``).

        Same items and shape as ``CustomerClient.billing.products()``, for pages that have no
        signed-in account (an anonymous pricing page). Read-only: purchases still go through
        the customer plane. CRM marks the answer cacheable for 60 seconds
        (``Cache-Control: private, max-age=60``); keep a short in-process cache.
        """
        data = await self._request("GET", "/catalog")
        return _parse(_ProductList, data, "catalog.get").items


class ServiceAiApi(_Namespace):
    async def ensure_key(self, account_id: int, function: str = "default") -> AiKey:
        """Return the account AI key, minting it on first use. The only call exposing the secret."""
        data = await self._request(
            "POST", "/ai/key/ensure", json={"account_id": account_id, "function": function}
        )
        return _parse(AiKey, data, "ai.ensure_key")

    async def key_stats(self, account_id: int) -> AiKeyStats:
        """Mask and spending of the account key; no key yet is ``NotFoundError``."""
        data = await self._request("GET", f"/ai/key/{_id(account_id)}/stats")
        return _parse(AiKeyStats, data, "ai.key_stats")
