# Изменения

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
