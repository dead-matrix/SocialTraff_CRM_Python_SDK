# Контракт SDK ↔ CRM

Таблица соответствия методов SDK и ручек CRM. Заполняется на этапе Ф7 (план CRM, §5.2, §5.3, §7.2).
Версия CRM, с которой сверены контрактные фикстуры: _будет указана в Ф7_.

## Service plane (`ServiceClient`, `X-Service-Token`)

| Метод SDK | HTTP | Ручка CRM | Idempotency-Key | Модель ответа |
|---|---|---|---|---|

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
| `referrals.get()` | GET | `/api/v1/customer/referrals` | `referrals:read` | нет | `ReferralSummary` |
| `referrals.withdrawals(cursor, limit)` | GET | `/api/v1/customer/referrals/withdrawals` | `referrals:read` | нет | `WithdrawalPage` |
| `referrals.withdraw(method)` | POST (202) | `/api/v1/customer/referrals/withdraw` | `referrals:write` | да | `WithdrawalRequest` |

Assertion: `alg=EdDSA`, заголовок `kid`, claims `iss`, `aud`, `sub` (`public_customer_id`, UUID в
каноническом виде нижним регистром), `iat`, `exp` (не дольше 120 с), `jti`, `scope`, `act`
(`buyer_id` >= 1) и `token_use="customer_assertion"`. Метод ключа AI появится вместе с ручкой CRM.

## Вебхуки CRM → продукт (`webhooks.verify`)

| `event_type` | Модель SDK | Payload |
|---|---|---|
| `product.plan_changed` | `PlanChangedEvent` | `account_id`, `product`, `plan`, `plan_until`, `version` |
| `product.notify` | `NotifyEvent` | `account_id`, `kind`, `params`, `button` |
| любой другой | `GenericEvent` | без разбора (`dict`) |
