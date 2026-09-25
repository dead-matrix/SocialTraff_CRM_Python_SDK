# Контракт SDK ↔ CRM

Таблица соответствия методов SDK и ручек CRM. Заполняется на этапе Ф7 (план CRM, §5.2, §5.3, §7.2).
Версия CRM, с которой сверены контрактные фикстуры: _будет указана в Ф7_.

## Service plane (`ServiceClient`, `X-Service-Token`)

| Метод SDK | HTTP | Ручка CRM | Idempotency-Key | Модель ответа |
|---|---|---|---|---|

## Customer plane (`CustomerClient`, `X-Customer-Assertion`)

| Метод SDK | HTTP | Ручка CRM | Скоуп | Idempotency-Key | Модель ответа |
|---|---|---|---|---|---|

## Вебхуки CRM → продукт (`webhooks.verify`)

| `event_type` | Модель SDK | Payload |
|---|---|---|
| `product.plan_changed` | `PlanChangedEvent` | `account_id`, `product`, `plan`, `plan_until`, `version` |
| `product.notify` | `NotifyEvent` | `account_id`, `kind`, `params`, `button` |
| любой другой | `GenericEvent` | без разбора (`dict`) |
