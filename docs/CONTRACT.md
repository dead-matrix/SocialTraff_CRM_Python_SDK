# Контракт SDK ↔ CRM

Таблица соответствия методов SDK и ручек CRM (план CRM, §5.2, §5.3, §7.2), версия SDK 0.1.0.
Контрактные фикстуры (`tests/fixtures/contract/`) сверены с CRM на коммите `5e4e833`; проверка:
`tests/test_contract_fixtures.py`.

## Service plane (`ServiceClient`, `X-Service-Token`)

Все ручки под `/api/internal`, заголовок `X-Service-Token`. Ответ в конверте
`{"status": "success", "data": ...}`, SDK возвращает разобранный `data`. Записи идемпотентны
на стороне CRM (повтор с тем же телом отвечает 200).

| Метод SDK | HTTP | Ручка CRM | Idempotency-Key | Модель ответа |
|---|---|---|---|---|
| `identity.put_buyer(buyer_id, ...)` | PUT | `/api/internal/identity/buyers/{buyer_id}` | нет | `Buyer` |
| `identity.put_account(account_id, ...)` | PUT | `/api/internal/identity/accounts/{account_id}` | нет | `Account` |
| `identity.put_member(account_id, buyer_id, role)` | PUT | `/api/internal/identity/accounts/{account_id}/members/{buyer_id}` | нет | `Member` |
| `identity.remove_member(account_id, buyer_id)` | DELETE | `/api/internal/identity/accounts/{account_id}/members/{buyer_id}` | нет | `Member` |
| `identity.issue_customer_id(account_id)` | POST | `/api/internal/identity/accounts/{account_id}/customer-id` | нет | `CustomerId` |
| `identity.import_(buyers, accounts, members)` | POST | `/api/internal/identity/import` | по желанию | `IdentityImportResult` |
| `plans.import_(items)` | POST | `/api/internal/plans/import` | по желанию | `PlansImportResult` |
| `plans.get(account_id)` | GET | `/api/internal/plans/{account_id}` | нет | `AccountPlans` |
| `plans.list_updated(updated_since, limit, cursor)` | GET | `/api/internal/plans` | нет | `PlansPage` |
| `ai.ensure_key(account_id, function)` | POST | `/api/internal/ai/key/ensure` | нет | `AiKey` (единственный ответ с секретом) |
| `ai.key_stats(account_id)` | GET | `/api/internal/ai/key/{account_id}/stats` | нет | `AiKeyStats` |

## Customer plane (`CustomerClient`, `X-Customer-Assertion`)

| Метод SDK | HTTP | Ручка CRM | Скоуп | Idempotency-Key | Модель ответа |
|---|---|---|---|---|---|
| `billing.products()` | GET | `/api/v1/customer/billing/products` | `billing:read` | нет | `list[CatalogProduct]` |
| `billing.subscription()` | GET | `/api/v1/customer/billing/subscription` | `billing:read` | нет | `Subscription` |
| `billing.create_payment(...)` | POST (201) | `/api/v1/customer/billing/payments` | `billing:write` | да | `CheckoutSession` |
| `billing.list_payments(cursor, limit)` | GET | `/api/v1/customer/billing/payments` | `billing:read` | нет | `PaymentPage` |
| `billing.get_payment(id)` | GET | `/api/v1/customer/billing/payments/{payment_public_id}` | `billing:read` | нет | `Payment` |
| `ai.balance()` | GET | `/api/v1/customer/ai/balance` | `ai:read` | нет | `AiBalance` |
| `ai.history(function, cursor, limit)` | GET | `/api/v1/customer/ai/history` | `ai:read` | нет | `AiHistoryPage` |
| `ai.usage(date_from, date_to)` | GET | `/api/v1/customer/ai/usage` (`from`, `to`) | `ai:read` | нет | `AiUsage` |
| `ai.key()` | GET | `/api/v1/customer/ai/key` | `ai:read` | нет | `AiKeyStats` |
| `referrals.get()` | GET | `/api/v1/customer/referrals` | `referrals:read` | нет | `ReferralSummary` |
| `referrals.withdrawals(cursor, limit)` | GET | `/api/v1/customer/referrals/withdrawals` | `referrals:read` | нет | `WithdrawalPage` |
| `referrals.withdraw(method)` | POST (202) | `/api/v1/customer/referrals/withdraw` | `referrals:write` | да | `WithdrawalRequest` |

Assertion: `alg=EdDSA`, заголовок `kid`, claims `iss`, `aud`, `sub` (`public_customer_id`, UUID в
каноническом виде нижним регистром), `iat`, `exp` (не дольше 120 с), `jti`, `scope`, `act`
(`buyer_id` >= 1) и `token_use="customer_assertion"`.

## Вебхуки CRM → продукт (`webhooks.verify`)

| `event_type` | Модель SDK | Payload |
|---|---|---|
| `product.plan_changed` | `PlanChangedEvent` | `account_id`, `product`, `plan`, `plan_until`, `version` |
| `product.notify` | `NotifyEvent` | `account_id`, `kind`, `params`, `button` |
| любой другой | `GenericEvent` | без разбора (`dict`) |

Тело: конверт `{event_id, event_type, payload}`. Заголовок `X-CRM-Signature`: HMAC-SHA256 от
сырых байтов тела с `PRODUCT_WEBHOOK_SECRET`, hex нижним регистром.

`plan_until`: ISO 8601 со смещением или `null`. `version` монотонна по аккаунту и продукту.
`button`: `{url, text?}` или `null`.

Значения `product.notify.kind` (`KNOWN_NOTIFY_KINDS`, справочно; в модели `kind: str`):

| `kind` | Источник в CRM | `params` |
|---|---|---|
| `payment_confirmed` | подтверждение оплаты | `payment_uuid`, `amount_minor`, `currency`, `plans[{product, plan, months}]` |
| `expiring_7d`, `expiring_3d`, `expiring_1d` | сканер истечения | `modules`, `expires_date` |
| `<event_type>_fallback` | событие продаж, если у владельца нет чата в мессенджере | payload исходного события; `button.url` ведёт в бот поддержки |

Известные резервные `kind`: `access_expired_followup_fallback`, `payment_reminder_fallback`,
`unpaid_invoice_24h_fallback`, `payment_expired_fallback`.

`subscription_changed` в вебхук продукта не приходит: CRM публикует его только мессенджеру.
Payload (`SubscriptionChangedPayload`): `account_id`, `user_id`, `has_active_subscription`,
`frozen` (сейчас всегда `false`), `reason` из `plan_changed`/`expired`. В `CrmEvent` не входит.
