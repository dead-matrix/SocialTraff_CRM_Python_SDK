# socialtraff-crm-sdk

Асинхронный Python SDK для CRM SocialTraff. Импорт: `socialtraff_crm`. Python 3.12 и новее.

Состав:

- `ServiceClient`: сервисная плоскость (`X-Service-Token`, `/api/internal/...`), для бэкенда и воркера продукта;
- `CustomerClient`: клиентская плоскость (`X-Customer-Assertion`, `/api/v1/customer/...`), запросы от имени аккаунта;
- `AssertionSigner`: выпуск assertion (JWT EdDSA/Ed25519) на каждый запрос клиентской плоскости;
- `webhooks.verify`: проверка подписи вебхуков CRM → продукт и разбор событий `product.*`.

> Статус: `0.2.0`. Сервисная и клиентская плоскости, assertion и проверка вебхуков готовы;
> формы ответов и событий сверены с контрактными фикстурами CRM (`tests/fixtures/contract/`,
> коммит CRM в `tests/fixtures/contract/CRM_VERSION`). Изменения по версиям: [CHANGELOG.md](CHANGELOG.md).

## Установка

Пакет распространяется git-тегами из приватного репозитория GitHub: для установки нужен доступ
на чтение (deploy key или fine-grained токен только на чтение этого репозитория). В
`pyproject.toml` продукта:

```toml
[project]
dependencies = ["socialtraff-crm-sdk"]

[tool.uv.sources]
socialtraff-crm-sdk = { git = "https://github.com/dead-matrix/SocialTraff_CRM_Python_SDK", tag = "v0.2.0" }
```

Для доступа по SSH (deploy key) источник записывается как
`{ git = "ssh://git@github.com/dead-matrix/SocialTraff_CRM_Python_SDK.git", tag = "v0.2.0" }`.
Затем `uv sync`. Разовая установка: `uv add "socialtraff-crm-sdk @ git+https://github.com/dead-matrix/SocialTraff_CRM_Python_SDK@v0.2.0"`.

## ServiceClient

```python
from socialtraff_crm import ServiceClient

async with ServiceClient(
    "https://crm.socialtraff.com", service_token, timeout=10.0, retries=3
) as crm:
    buyer = await crm.identity.put_buyer(42, tg_id=100500, display_name="Ann")
    await crm.identity.put_account(1042, title="Ann", owner_buyer_id=42, is_personal=True)
    await crm.identity.put_member(1042, 42, "owner")
    customer_id = await crm.identity.issue_customer_id(1042)

    products = await crm.catalog.get()  # витрина без аккаунта (анонимная страница цен)

    plans = await crm.plans.get(1042)
    page = await crm.plans.list_updated(since, limit=100)  # since с часовым поясом

    key = await crm.ai.ensure_key(1042)  # key.secret: живой ключ, в repr не попадает
    stats = await crm.ai.key_stats(1042)
```

Заголовок авторизации `X-Service-Token`, префикс `/api/internal`. `retries` задаёт общее число
попыток, включая первую. Все записи идемпотентны на стороне CRM: повтор с тем же телом отвечает
200 и ничего не меняет. У `identity.import_` и `plans.import_` есть `idempotency_key`: CRM этот
заголовок у импортов не проверяет (импорт идемпотентен по содержимому), SDK по нему только
разрешает себе повторить POST при сетевых сбоях, поэтому любой ключ, например `uuid4()`, безопасен. Даты без часового пояса SDK отвергает (`ValidationError`),
потому что CRM прочла бы их как московское время. В `put_buyer` непереданное поле сохраняется,
а явный `None` стирает значение. Полный список методов: [docs/CONTRACT.md](docs/CONTRACT.md).

## CustomerClient и AssertionSigner

```python
from socialtraff_crm import AssertionSigner, CustomerClient

# iss/aud по умолчанию: socialtraff-bosslink / socialtraff-crm
signer = AssertionSigner(private_key_pem, kid="bosslink-2026-09")

async with CustomerClient(
    "https://crm.socialtraff.com",
    signer,
    account_public_id="3f2b8c1e-8f4a-4d0b-9a57-0c7e6f1d2a90",  # public_customer_id аккаунта
    actor_buyer_id=42,  # buyer_id действующего человека, claim act
) as customer:
    subscription = await customer.billing.subscription()
    balance = await customer.ai.balance()
    key_stats = await customer.ai.key()  # маска и расход ключа AI, без секрета
    referrals = await customer.referrals.get()

    # Промокод до оплаты: скидка ждёт следующего create_payment, бонусные дни - оплаты подписки.
    activation = await customer.promo.activate("SALE15")  # 422 promo_<причина> -> ValidationError
    pending = await customer.promo.pending()  # list[PromoActivation]

    # Свой код партнёра (владелец из act): 409 promo_code_taken, 422 promo_invalid_code.
    partner_code = await customer.referrals.set_code("My_Code")

    # Промокод тем же запросом и оплата подписки реферальным балансом.
    session = await customer.billing.create_payment(
        product_id,
        quantity=1,
        provider="platega",
        payment_method="sbp",
        return_to="https://lk.socialtraff.com/billing",
        promo_code="SALE15",
        use_balance=True,
    )
    if session.status == "paid":
        ...  # баланс покрыл всю цену: pay_url None, открывать нечего
    else:
        ...  # открыть session.pay_url, к оплате amount_rub_kopecks
```

Скидка промокода уже заложена в цены позиций; `amount_rub_kopecks` = сумма позиций минус
`balance_spent_rub_kopecks`. Платёж, оплаченный балансом целиком, в `get_payment` и
`list_payments` приходит с `provider="balance"`. Смена баланса или скидки между расчётом и записью:
`ApiError` 409 `balance_changed` или `promo_changed`, повторять с новым ключом.

Assertion выпускается заново на каждую попытку запроса: срок 60 с, случайный `jti`, claim `scope`
со скоупами конкретного метода и `token_use="customer_assertion"`. `account_public_id` должен быть
UUID в каноническом виде нижним регистром, иначе CRM отвергнет assertion. Для записей SDK сам ставит `Idempotency-Key`, ключ одинаков для всех
своих ретраев. Если запрос повторяет вызывающий код, ключ нужно передать явно.

Скоупы: `billing:read`, `billing:write`, `ai:read`, `referrals:read`, `referrals:write`.
Для `billing.create_payment` продукт до подписи проверяет роль owner или admin; `promo.activate`
разрешён любой роли аккаунта, `referrals.set_code` личный (покупатель из `act`), хотя все три
подписываются скоупом `billing:write`.

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
        # 400: CRM помечает событие failed без повторов; на 422 и прочие 4xx она повторяет бесконечно
        raise HTTPException(400)

    # дедупликация по event.event_id на стороне продукта
    match event:
        case PlanChangedEvent():
            ...  # применить, только если event.payload.version >= сохранённой
        case NotifyEvent():
            ...
        case GenericEvent():
            ...  # неизвестный тип: залогировать и ответить 200
    return {"status": "success", "data": None}
```

События:

- `product.plan_changed` (`PlanChangedEvent`): `account_id`, `product` (`cabinet` или `privetka`),
  `plan`, `plan_until` (ISO с поясом или `null`), `version`. `version` не убывает по аккаунту и
  продукту: применять событие, если `version` >= сохранённой (истечение доступа приходит с той же
  `version`, что и последняя оплата), событие с меньшей версией отбросить.
- `product.notify` (`NotifyEvent`): `account_id`, `kind`, `params`, `button` (`{url, text?}` или
  `null`). Известные `kind` перечислены в `socialtraff_crm.models.KNOWN_NOTIFY_KINDS`:
  `payment_confirmed`, `expiring_7d`, `expiring_3d`, `expiring_1d` и резервные
  `<тип события мессенджера>_fallback` (например `payment_reminder_fallback`), которые CRM шлёт,
  когда у владельца аккаунта нет чата в мессенджере. Поле `kind` остаётся строкой, `params`
  словарём: новый `kind` из CRM не ломает разбор, его нужно просто пропустить.
  `event.payload.typed_params()` отдаёт модель известного `kind` (`PaymentConfirmedParams`,
  `ExpiringParams`, `AccessExpiredFollowupParams`, `PaymentReminderParams`,
  `PaymentExpiredParams`) или `None` для неизвестного. Суммы `amount_minor` в копейках,
  `expires_date` дата (`date`), `modules` список `NotifyModule(key, title)`: локализовать по
  `key` (`cabinet.pro`), `title` приходит по-русски.
- Любой другой тип разбирается как `GenericEvent`.

`subscription_changed` в вебхук продукта не приходит: CRM отправляет его только мессенджеру.
Модель `SubscriptionChangedPayload` (`account_id`, `user_id`, `bot_id`, `has_active_subscription`,
`frozen`, `reason` из `plan_changed`/`expired`) есть в SDK для потребителей этой очереди.

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
uv run ruff format --check
```

Контрактные фикстуры (`tests/fixtures/contract/*.json`) - байтовая копия CRM
`tests/contract/*.json`, коммит CRM записан в `tests/fixtures/contract/CRM_VERSION`. Каждая
фикстура обязана быть разобрана моделями SDK (`tests/test_contract_fixtures.py`): новая фикстура
CRM без разбора в SDK валит тесты. Пересинхронизация из рабочей копии CRM и проверка для CI:

```sh
python scripts/sync_contract_fixtures.py --crm ../CRM          # скопировать и записать коммит
python scripts/sync_contract_fixtures.py --crm ../CRM --check  # CI: код 1 при расхождении
CRM_CHECKOUT=../CRM uv run pytest tests/test_contract_fixtures.py  # то же тестом
```

Фикстуры лежат только в репозитории SDK (`tests/fixtures/contract/`) и в wheel не попадают. Для
тестов продукта их копируют к себе (например, в `tests/fixtures/crm/`) из тега той версии SDK,
что стоит в зависимостях, и держат рядом файл с тегом; обновляют вместе с тегом SDK:

```sh
git -C <SDK> archive v0.2.0 tests/fixtures/contract | tar -x --strip-components=3 -C tests/fixtures/crm
```

Порядок при изменении контракта CRM: CRM коммитит фикстуры, SDK синхронизирует их, правит
модели, выпускает тег, и только потом CRM выкатывается (правило в CRM `tests/contract/README.md`).

Соответствие методов SDK и ручек CRM: [docs/CONTRACT.md](docs/CONTRACT.md).
