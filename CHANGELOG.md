# Изменения

## 0.2.1 (2026-09-29)

Синхронизация с контрактом CRM на коммите `8e706ce`.

- `identity.put_account_chats(account_id, chats)` -> `AccountChatsResult`
  (`PUT /api/internal/identity/accounts/{account_id}/chats`): полный набор Telegram-чатов
  аккаунта, пустой список отвязывает все. Ответ: `account_id`, `active`, `linked`, `reopened`,
  `unlinked`, `unchanged`.
- `identity.import_(..., chats=None)`: перенос чатов аккаунтов. Ключ `chats` уходит в тело только
  непустым, поэтому импорт без чатов работает и со старой CRM (она отвечает 422 на этот ключ).
- `IdentityImportResult.chats` (`None` от старой CRM).
- Фикстуры: новая `service_identity_put_chats.json`, обновлена `service_identity_import.json`.
- Фикстуры: новая `customer_referrals_active.json` (CRM `8e706ce`): сводка партнёра с непустыми `recent_accruals` и `pending_withdrawal`.

## 0.2.0 (2026-09-29)

Синхронизация с контрактом CRM на коммите `79def25`.

- `CustomerClient.promo`: `activate(code)` -> `PromoActivation` (`POST /api/v1/customer/promo/activate`,
  201, `billing:write`, любая роль аккаунта) и `pending()` -> `list[PromoActivation]`
  (`GET /api/v1/customer/promo`, `billing:read`). Отказ кода: `ValidationError` с
  `code="promo_<причина>"`.
- `referrals.set_code(code)` -> `PartnerCode` (`PUT /api/v1/customer/referrals/code`,
  `billing:write`, с `Idempotency-Key`): свой код партнёра. Отказы: 422 `promo_invalid_code`,
  409 `promo_code_taken`.
- `billing.create_payment(..., promo_code=None, use_balance=False)`: промокод тем же запросом и
  оплата подписки реферальным балансом. Поля уходят в тело только если заданы, поэтому с CRM без
  промокодов обычный платёж работает как раньше. Ответ может быть `status="paid"` с `pay_url` и
  `checkout_url` `None` (баланс покрыл всю цену).
- `CheckoutSession` и `Payment`: `promo_discount_rub_kopecks`, `balance_spent_rub_kopecks`,
  `balance_spent_usd_cents` (0 от старой CRM). `Payment.provider` может быть `"balance"`.
- `ReferralSummary`: `first_percent`, `recurring_percent`, `hold_days`, `on_hold_usd_cents`,
  `spent_on_subscriptions_usd_cents`, `promo_codes[PartnerCode]`, `paid_referrals_count`,
  `promo_activations_count`, `pending_withdrawal` (`PendingWithdrawal` или `None`),
  `recent_accruals[ReferralAccrual]`. От старой CRM скаляры `None`, списки пустые.
  `withdrawn_subscription_usd_cents` теперь необязателен (0 по умолчанию). `withdraw_methods`
  у CRM теперь `["wallet"]`: баланс на подписку тратится через `use_balance`.
- Фикстуры: 6 новых (`customer_promo*.json`, `customer_referrals_code.json`,
  `customer_billing_payment_*_balance*.json`), 3 обновлены, всего 38 файлов. В
  `customer_referrals.json` `min_withdrawal_usd_cents` теперь 2000 (значение CRM).

Обратная совместимость: только добавления; новые поля ответа необязательны, новые аргументы
именованные со значениями по умолчанию. Минорная версия поднята из-за новых ручек.

## 0.1.3 (2026-09-25)

Синхронизация с контрактом CRM на коммите `55b72c1`.

- `ServiceClient.catalog.get()` -> `list[CatalogProduct]`: витрина без аккаунта,
  `GET /api/internal/catalog` под `X-Service-Token`. Состав и форма те же, что у
  `CustomerClient.billing.products()`; нужна страницам без входа (анонимная страница цен).
  CRM отдаёт `Cache-Control: private, max-age=60`, продукту достаточно кэша в процессе.
- Фикстура `service_catalog.json` (32 файла в копии); тест сверяет её данные с
  `customer_billing_products.json`.
- `webhook_product_request.json`: URL запроса теперь настоящий путь приёмника BossLink
  `/api/v1/crm/webhook` (подпись та же, она от тела).
- README: как брать фикстуры в тесты продукта (в wheel их нет).

Обратная совместимость: только добавления.

## 0.1.2 (2026-09-25)

Синхронизация с контрактом CRM на коммите `02878fa`.

- Контрактные фикстуры заменены байтовой копией CRM `tests/contract/*.json` (31 файл: все
  события `product.*`, `subscription_changed`, запрос вебхука с подписью, ответы сервисной и
  клиентской плоскостей). Коммит CRM записан в `tests/fixtures/contract/CRM_VERSION`.
- Тест `tests/test_contract_fixtures.py` разбирает каждую фикстуру моделями SDK; фикстура без
  разбора валит тесты. Скрипт `scripts/sync_contract_fixtures.py` копирует фикстуры из рабочей
  копии CRM, режим `--check` для CI.
- `NotifyPayload.typed_params()` и модели параметров уведомлений: `PaymentConfirmedParams`
  (`plans[{product, plan, months}]`), `ExpiringParams` и `AccessExpiredFollowupParams`
  (`modules` списком `NotifyModule(key, title)`, `expires_date` датой), `PaymentReminderParams`,
  `PaymentExpiredParams`. `params` по-прежнему словарь, неизвестный `kind` не ломает разбор.
- `ReferralSummary.ref_bot_link` (ссылка `https://t.me/socialtraff_robot?start=ref_<code>`).
- `SubscriptionChangedPayload.bot_id`.
- Документация: формат маски AI-ключа (`sk-or-…XXXX`), `Payment` без `pay_url` (ссылка
  провайдера только в ответе `create_payment`), `fx_rate_rub_usd` в платеже, `Idempotency-Key`
  у импортов CRM не проверяет, установка из приватного репозитория.

Обратная совместимость: новые поля необязательны, существующие имена не менялись.

## 0.1.1

- `CheckoutSession.pay_url` (страница Platega), `checkout_url` стал необязательным.

## 0.1.0

- Сервисный клиент (`identity`, `plans`, AI-ключ), клиентская плоскость (`billing`, `ai`,
  `referrals`), `AssertionSigner`, проверка вебхуков, первые контрактные фикстуры.
