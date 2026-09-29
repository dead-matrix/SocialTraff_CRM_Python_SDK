# Контракт SDK ↔ CRM

Таблица соответствия методов SDK и ручек CRM (план CRM, §5.2, §5.3, §7.2), версия SDK 0.2.0.
Контрактные фикстуры (`tests/fixtures/contract/*.json`, 38 файлов) - байтовая копия CRM
`tests/contract/*.json` на коммите `79def25` (полный SHA в `tests/fixtures/contract/CRM_VERSION`).
Каждую фикстуру разбирает `tests/test_contract_fixtures.py`; пересинхронизация и проверка для CI:
`scripts/sync_contract_fixtures.py --crm <CRM> [--check]`.

Адрес CRM в проде: `https://crm.socialtraff.com` (только https).

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
| `identity.import_(buyers, accounts, members)` | POST | `/api/internal/identity/import` | не проверяется CRM, см. ниже | `IdentityImportResult` |
| `plans.import_(items)` | POST | `/api/internal/plans/import` | не проверяется CRM, см. ниже | `PlansImportResult` |
| `plans.get(account_id)` | GET | `/api/internal/plans/{account_id}` | нет | `AccountPlans` |
| `plans.list_updated(updated_since, limit, cursor)` | GET | `/api/internal/plans` | нет | `PlansPage` |
| `catalog.get()` | GET | `/api/internal/catalog` | нет | `list[CatalogProduct]` (то же, что `billing.products()`, без аккаунта; `Cache-Control: private, max-age=60`) |
| `ai.ensure_key(account_id, function)` | POST | `/api/internal/ai/key/ensure` | нет | `AiKey` (единственный ответ с секретом) |
| `ai.key_stats(account_id)` | GET | `/api/internal/ai/key/{account_id}/stats` | нет | `AiKeyStats` |

Импорты идемпотентны по содержимому (покупатель, аккаунт и участник по id; тариф по паре
аккаунт + категория), заголовок `Idempotency-Key` CRM у них не читает. Аргумент
`idempotency_key` в SDK нужен только затем, чтобы SDK повторил POST при сетевом сбое или
429/502-504. Пакет: до 1000 элементов в каждом списке; повтор пары (аккаунт, категория) в одном
пакете, `plan="free"`, неизвестный тариф или аккаунт отвергают весь пакет (422 или 404).
`expires_at` обязателен и должен быть с часовым поясом.

Ответы: 401 без `X-Service-Token`, 403 с чужим токеном (`AuthError`), 404 неизвестный аккаунт
(`NotFoundError`), 409 `tg_id` уже у другого покупателя (`ApiError`), 422 (`ValidationError`).

## Customer plane (`CustomerClient`, `X-Customer-Assertion`)

| Метод SDK | HTTP | Ручка CRM | Скоуп | Idempotency-Key | Модель ответа |
|---|---|---|---|---|---|
| `billing.products()` | GET | `/api/v1/customer/billing/products` | `billing:read` | нет | `list[CatalogProduct]` |
| `billing.subscription()` | GET | `/api/v1/customer/billing/subscription` | `billing:read` | нет | `Subscription` |
| `billing.create_payment(..., promo_code, use_balance)` | POST (201) | `/api/v1/customer/billing/payments` | `billing:write` | да | `CheckoutSession` |
| `billing.list_payments(cursor, limit)` | GET | `/api/v1/customer/billing/payments` | `billing:read` | нет | `PaymentPage` |
| `billing.get_payment(id)` | GET | `/api/v1/customer/billing/payments/{payment_public_id}` | `billing:read` | нет | `Payment` |
| `promo.activate(code)` | POST (201) | `/api/v1/customer/promo/activate` | `billing:write` | да | `PromoActivation` |
| `promo.pending()` | GET | `/api/v1/customer/promo` | `billing:read` | нет | `list[PromoActivation]` |
| `ai.balance()` | GET | `/api/v1/customer/ai/balance` | `ai:read` | нет | `AiBalance` |
| `ai.history(function, cursor, limit)` | GET | `/api/v1/customer/ai/history` | `ai:read` | нет | `AiHistoryPage` |
| `ai.usage(date_from, date_to)` | GET | `/api/v1/customer/ai/usage` (`from`, `to`) | `ai:read` | нет | `AiUsage` |
| `ai.key()` | GET | `/api/v1/customer/ai/key` | `ai:read` | нет | `AiKeyStats` |
| `referrals.get()` | GET | `/api/v1/customer/referrals` | `referrals:read` | нет | `ReferralSummary` |
| `referrals.withdrawals(cursor, limit)` | GET | `/api/v1/customer/referrals/withdrawals` | `referrals:read` | нет | `WithdrawalPage` |
| `referrals.withdraw(method)` | POST (202) | `/api/v1/customer/referrals/withdraw` | `referrals:write` | да | `WithdrawalRequest` |
| `referrals.set_code(code)` | PUT | `/api/v1/customer/referrals/code` | `billing:write` | да | `PartnerCode` |

Промокоды и баланс: отказ кода в `create_payment` и `promo.activate` - 422 `promo_<причина>`
(`ValidationError`, `field: "code"`); `referrals.set_code` - 422 `promo_invalid_code` или 409
`promo_code_taken`. `create_payment` с `use_balance=True` может ответить `status="paid"` с
`pay_url` и `checkout_url` `null` (баланс покрыл всю цену), такой платёж в чтении приходит с
`provider="balance"`. `CheckoutSession` и `Payment` несут `promo_discount_rub_kopecks`,
`balance_spent_rub_kopecks`, `balance_spent_usd_cents`; сумма позиций минус
`balance_spent_rub_kopecks` равна `amount_rub_kopecks`. 409 `balance_changed` и `promo_changed`
(`ApiError`) повторять с новым ключом.

Поля, которые легко пропустить: `Payment` (ответ `get_payment` и `list_payments`) не несёт
`pay_url`, ссылка провайдера отдаётся только в ответе `create_payment` (`CheckoutSession.pay_url`);
`Payment.fx_rate_rub_usd` - курс рублей за 1 USD, зафиксированный в черновике; `web_return_url`
- проверенный `return_to`, на него Platega возвращает браузер и после оплаты, и после отказа.
`ReferralSummary.ref_bot_link` - ссылка `https://t.me/socialtraff_robot?start=ref_<code>`.
`AiKeyStats.mask` строится CRM как `sk-or-…` + 4 последних символа ключа (например `sk-or-…9f2c`).

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

| `kind` | Источник в CRM | `params` | `typed_params()` |
|---|---|---|---|
| `payment_confirmed` | подтверждение оплаты (Platega, ручная отметка оплаты в админке CRM) | `payment_uuid`, `amount_minor` (копейки), `currency`, `plans[{product, plan, months}]` | `PaymentConfirmedParams` |
| `expiring_7d`, `expiring_3d`, `expiring_1d` | сканер истечения | `modules[{key, title}]`, `expires_date` (`YYYY-MM-DD`) | `ExpiringParams` |
| `access_expired_followup_fallback` | +1 и +3 дня после истечения | `kind` (`expired_after_1d`/`expired_after_3d`), `modules[{key, title}]`, `expires_date`, `photo_url` (`null`), `idempotency_key` | `AccessExpiredFollowupParams` |
| `payment_reminder_fallback`, `unpaid_invoice_24h_fallback` | неоплаченный счёт 2 ч и 24 ч | `amount_minor`, `service`, `pay_page_url`, `invoice_uuid` | `PaymentReminderParams` |
| `payment_expired_fallback` | счёт просрочен | `amount_minor`, `provider`, `invoice_uuid` | `PaymentExpiredParams` |

Резервные `*_fallback` CRM шлёт, когда у владельца аккаунта есть `tg_id`, но он не запускал бот
поддержки; `button.url` = `https://t.me/socialtraff_support_bot?start=crm_<тип>`, `button.text`
отсутствует. У `modules` `key` вида `<product>.<plan>`, `title` по-русски.

`product.plan_changed` приходит при подтверждённой оплате, при ручном изменении доступа
(мессенджер `POST /api/access/manage` и `/api/access/add`, ручная отметка оплаты в админке CRM),
при сторно (D62) и при истечении (тариф `free`, `plan_until: null`, та же `version`, что у строки,
которая дала тариф). Перенос тарифов `plans.import_` событий не порождает.

`subscription_changed` в вебхук продукта не приходит: CRM публикует его только мессенджеру.
Payload (`SubscriptionChangedPayload`): `account_id`, `user_id`, `bot_id` (10), `has_active_subscription`,
`frozen` (сейчас всегда `false`), `reason` из `plan_changed`/`expired`. В `CrmEvent` не входит.
