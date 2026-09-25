# socialtraff-crm-sdk

Асинхронный Python SDK для CRM SocialTraff. Импорт: `socialtraff_crm`. Python 3.12 и новее.

Состав:

- `ServiceClient`: сервисная плоскость (`X-Service-Token`, `/api/internal/...`), для бэкенда и воркера продукта;
- `CustomerClient`: клиентская плоскость (`X-Customer-Assertion`, `/api/v1/customer/...`), запросы от имени аккаунта;
- `AssertionSigner`: выпуск assertion (JWT EdDSA/Ed25519) на каждый запрос клиентской плоскости;
- `webhooks.verify`: проверка подписи вебхуков CRM → продукт и разбор событий `product.*`.

> Статус: `0.1.0`. Сервисная и клиентская плоскости, assertion и проверка вебхуков готовы;
> формы ответов и событий сверены с CRM контрактными фикстурами (`tests/fixtures/contract/`).

## Установка

Пакет распространяется git-тегами. В `pyproject.toml` продукта:

```toml
[project]
dependencies = ["socialtraff-crm-sdk"]

[tool.uv.sources]
socialtraff-crm-sdk = { git = "https://github.com/dead-matrix/SocialTraff_CRM_Python_SDK", tag = "v0.1.0" }
```

Затем `uv sync`. Разовая установка: `uv add "socialtraff-crm-sdk @ git+https://github.com/dead-matrix/SocialTraff_CRM_Python_SDK@v0.1.0"`.

## ServiceClient

```python
from socialtraff_crm import ServiceClient

async with ServiceClient(
    "http://crm.socialtraff.com", service_token, timeout=10.0, retries=3
) as crm:
    buyer = await crm.identity.put_buyer(42, tg_id=100500, display_name="Ann")
    await crm.identity.put_account(1042, title="Ann", owner_buyer_id=42, is_personal=True)
    await crm.identity.put_member(1042, 42, "owner")
    customer_id = await crm.identity.issue_customer_id(1042)

    plans = await crm.plans.get(1042)
    page = await crm.plans.list_updated(since, limit=100)  # since с часовым поясом

    key = await crm.ai.ensure_key(1042)  # key.secret: живой ключ, в repr не попадает
    stats = await crm.ai.key_stats(1042)
```

Заголовок авторизации `X-Service-Token`, префикс `/api/internal`. `retries` задаёт общее число
попыток, включая первую. Все записи идемпотентны на стороне CRM: повтор с тем же телом отвечает
200 и ничего не меняет. У `identity.import_` и `plans.import_` есть `idempotency_key`: с ним
POST повторяется при сетевых сбоях. Даты без часового пояса SDK отвергает (`ValidationError`),
потому что CRM прочла бы их как московское время. В `put_buyer` непереданное поле сохраняется,
а явный `None` стирает значение. Полный список методов: [docs/CONTRACT.md](docs/CONTRACT.md).

## CustomerClient и AssertionSigner

```python
from socialtraff_crm import AssertionSigner, CustomerClient

# iss/aud по умолчанию: socialtraff-bosslink / socialtraff-crm
signer = AssertionSigner(private_key_pem, kid="bosslink-2026-09")

async with CustomerClient(
    "http://crm.socialtraff.com",
    signer,
    account_public_id="3f2b8c1e-8f4a-4d0b-9a57-0c7e6f1d2a90",  # public_customer_id аккаунта
    actor_buyer_id=42,  # buyer_id действующего человека, claim act
) as customer:
    subscription = await customer.billing.subscription()
    balance = await customer.ai.balance()
    key_stats = await customer.ai.key()  # маска и расход ключа AI, без секрета
    referrals = await customer.referrals.get()
```

Assertion выпускается заново на каждую попытку запроса: срок 60 с, случайный `jti`, claim `scope`
со скоупами конкретного метода и `token_use="customer_assertion"`. `account_public_id` должен быть
UUID в каноническом виде нижним регистром, иначе CRM отвергнет assertion. Для записей SDK сам ставит `Idempotency-Key`, ключ одинаков для всех
своих ретраев. Если запрос повторяет вызывающий код, ключ нужно передать явно.

Скоупы: `billing:read`, `billing:write`, `ai:read`, `referrals:read`, `referrals:write`.
`billing:write` выдаётся только ролям owner и admin: это проверяет продукт до подписи.

## Проверка вебхука

Подпись `X-CRM-Signature` считается по сырым байтам тела, поэтому тело нужно брать до разбора JSON.

```python
from fastapi import FastAPI, HTTPException, Request
from socialtraff_crm import (
    GenericEvent,
    NotifyEvent,
    PlanChangedEvent,
    SignatureError,
    ValidationError,
    webhooks,
)

app = FastAPI()


@app.post("/api/v1/crm/webhook")
async def crm_webhook(request: Request) -> dict:
    raw = await request.body()
    try:
        event = webhooks.verify(
            raw, request.headers.get(webhooks.SIGNATURE_HEADER, ""), CRM_WEBHOOK_SECRET
        )
    except SignatureError:
        raise HTTPException(401)
    except ValidationError:
        raise HTTPException(422)

    # дедупликация по event.event_id на стороне продукта
    match event:
        case PlanChangedEvent():
            ...  # применить, только если event.payload.version новее текущего
        case NotifyEvent():
            ...
        case GenericEvent():
            ...  # неизвестный тип: залогировать и ответить 200
    return {"status": "success", "data": None}
```

События:

- `product.plan_changed` (`PlanChangedEvent`): `account_id`, `product` (`cabinet` или `privetka`),
  `plan`, `plan_until` (ISO с поясом или `null`), `version`. `version` монотонна по аккаунту и
  продукту: событие со старой версией нужно отбросить.
- `product.notify` (`NotifyEvent`): `account_id`, `kind`, `params`, `button` (`{url, text?}` или
  `null`). Известные `kind` перечислены в `socialtraff_crm.models.KNOWN_NOTIFY_KINDS`:
  `payment_confirmed`, `expiring_7d`, `expiring_3d`, `expiring_1d` и резервные
  `<тип события мессенджера>_fallback` (например `payment_reminder_fallback`), которые CRM шлёт,
  когда у владельца аккаунта нет чата в мессенджере. Поле `kind` остаётся строкой: новый `kind`
  из CRM не ломает разбор, его нужно просто пропустить.
- Любой другой тип разбирается как `GenericEvent`.

`subscription_changed` в вебхук продукта не приходит: CRM отправляет его только мессенджеру.
Модель `SubscriptionChangedPayload` (`account_id`, `user_id`, `has_active_subscription`, `frozen`,
`reason` из `plan_changed`/`expired`) есть в SDK для потребителей этой очереди.

## Ошибки

Все ошибки наследуют `SDKError` (поля `message`, `status_code`, `code`, `details`):

| Класс | Когда |
|---|---|
| `AuthError` | HTTP 401 (плохие или протухшие учётные данные), 403 |
| `NotFoundError` | HTTP 404; `code` отличает `not_found` от `feature_disabled` |
| `ValidationError` | HTTP 422 и проверки на стороне SDK, в том числе дата без смещения |
| `ApiError` | прочие ответы-ошибки CRM, есть `code` и `status_code` |
| `HttpError` | сетевая ошибка или ответ не в формате конверта |
| `SignatureError` | неверная подпись вебхука |
| `ConfigError` | неверная настройка клиента |

Ретраи: до 3 попыток с экспоненциальной задержкой и джиттером при сетевых ошибках и HTTP
429/502/503/504. Повторяются только GET/PUT/DELETE и POST с `Idempotency-Key`. `Retry-After`
учитывается, но не больше 30 с.

## Разработка

```sh
uv venv --python 3.12
uv pip install -e ".[dev]"
uv run pytest -v
uv run ruff check
```

Соответствие методов SDK и ручек CRM: [docs/CONTRACT.md](docs/CONTRACT.md).
