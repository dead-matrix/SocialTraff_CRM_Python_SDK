# socialtraff-crm-sdk

Асинхронный Python SDK для CRM SocialTraff. Импорт: `socialtraff_crm`. Python 3.12 и новее.

Состав:

- `ServiceClient`: сервисная плоскость (`X-Service-Token`, `/api/internal/...`), для бэкенда и воркера продукта;
- `CustomerClient`: клиентская плоскость (`X-Customer-Assertion`, `/api/v1/customer/...`), запросы от имени аккаунта;
- `AssertionSigner`: выпуск assertion (JWT EdDSA/Ed25519) на каждый запрос клиентской плоскости;
- `webhooks.verify`: проверка подписи вебхуков CRM → продукт и разбор событий `product.*`.

> Статус: `0.1.0.dev0`, каркас. Транспорт, ошибки, ретраи, assertion и проверка вебхуков готовы.
> Методы `ServiceClient` и `CustomerClient` **появятся в v0.1.0**.

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
    # появится в v0.1.0:
    # await crm.identity.upsert_buyer(...)
    # await crm.plans.get(account_id)
    # await crm.ai.ensure_key(account_id)
    ...
```

`retries` задаёт общее число попыток, включая первую.

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
    # появится в v0.1.0:
    # await customer.billing.subscription()
    # await customer.ai.balance()
    # await customer.referrals.info()
    ...
```

Assertion выпускается заново на каждую попытку запроса: срок 60 с, случайный `jti`, claim `scope`
со скоупами конкретного метода. Для записей SDK сам ставит `Idempotency-Key`, ключ одинаков для всех
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
