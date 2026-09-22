# MAXBOT Safe Remediation Addendum Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить отсутствующие platform-authorization и transport-safety gates, обязательно перевести проект на `maxapi-python==2.4.1`, затем выполнить MAXBOT MASTER V3 без изменения основной модели продукта и без увеличения риска ограничения аккаунтов.

**Architecture:** Существующий модульный монолит, FastAPI, tenant SQLite/PostgreSQL и статический frontend сохраняются. Обязательный `ENV-00` сначала создаёт воспроизводимое локальное окружение и подтверждает toolchain без запуска MAX или production services. Перед любой границей MAX вводится fail-closed policy/gateway; искусственные side effects, auto-join и неподтверждённая client identity не допускаются. Версионно-зависимая интеграция PyMax изолируется в одном runtime adapter; задача `S02A` выполняет контролируемую миграцию `2.4.0 -> 2.4.1`, не меняя sender identity или продуктовую семантику. Этот addendum добавляет `ENV-00`, задачи `S00..S05` и `S02A`, но не перенумеровывает и не дублирует нормативные `T00..T33` из Master V3.

**Tech Stack:** Python 3.12, FastAPI, asyncio, SQLite, PostgreSQL, Redis/Celery, pytest, `pip-tools==7.6.1`, `pip-audit==2.10.1`, Docker Compose, vanilla JavaScript, `maxapi-python==2.4.0` только как исходный migration baseline и обязательная целевая версия `maxapi-python==2.4.1` с точным pin.

**Spec:** `docs/audit/2026-09-20-maxbot-master-v3-independent-audit.md`; основной документ `C:\Users\Edifi\Documents\MAXBOT_MASTER_V3_EN_2026-09-20.md`, SHA-256 `8c7a57092be519ea5df0379abc6030124d1e099867adbc72a06174027c90392d`.

## Continuation status (2026-09-22)

The supplemental source work for `ENV-00` and `S00..S03` is present in the
runtime/test candidate `266022fe39a05c978b738565633e714047bc740e`; focused
local evidence and browser/UI extensions are recorded in the audit files.
The normative `T00..T33` / 365-case acceptance, independent platform
authorization, image-CVE metadata review, secret-history ownership review,
and production/VPS/live-MAX gates remain `NOT RUN` or `BLOCKED` and are not
marked complete by this continuation.

## Global Constraints

- `ENV-00` обязан завершиться до первого изменения application code или dependency manifests; system Python не изменяется, все Python packages устанавливаются только в ignored `.venv/`.
- Новые async tests следуют существующему стилю проекта `asyncio.run(...)`; не добавлять `pytest-asyncio` только ради этого плана.
- `ENV-00` не создаёт `.env`, не запускает services и не требует production secrets; Compose syntax проверяется только с явными fixture values.
- Не выполнять реальные SMS, login, send, join, probe, history, read или reaction во время разработки и автоматических тестов.
- Отсутствующий, просроченный, несовпадающий или непроверенный platform-authorization record блокирует все внешние MAX-действия.
- Runtime record хранит только несекретные reference/scope/expiry; договор, токены, OTP, пароли, session cookies и proxy credentials не попадают в Git, логи или evidence.
- Согласие сотрудника и разрешённая закрытая группа проверяются отдельно и не заменяют разрешение MAX на transport.
- Сохранить `active / quiet / skip`, текущие policy values, рабочие окна, warmup/lazy-day, один work group и один постоянный route на аккаунт.
- Сохранить персональные дневные планы и переиспользуемую immutable library; не вводить произвольные caps `3/3/10`, обязательные 180 секунд, depletion библиотеки, proxy reshuffle или sender substitution.
- Не добавлять реакции, idle presence, историю ради маскировки, rotating fingerprint, искусственный engagement или обход ограничений.
- `unknown` никогда не повторяется автоматически и продолжает занимать исходный slot; `accepted` требует provider acknowledgement и не означает delivery/read.
- Preview/GET/WS/readiness не изменяют business state и не обращаются к MAX.
- Не выполнять миграцию на официальный Bot API без отдельного owner-approved product decision: она меняет sender identity и основную семантику.
- Обновить только `maxapi-python` с точного `2.4.0` до точного `2.4.1` в `S02A`; не использовать плавающий `latest`, Git dependency или более новую версию без нового source review и отдельного изменения плана.
- Разрешение на использование PyMax не заменяет action scope: до live-вызова `S00` фиксирует несекретные reference/scope/expiry, а `S01` проверяет разрешение перед каждым внешним действием.
- Не менять остальные production dependencies, production schema или deploy policy без отдельного evidence и требуемого разрешения.
- Каждое изменение поведения начинается с RED regression; обязательный gate с `NOT RUN`, timeout, skipped required suite или `0 tests` не считается PASS.
- Не выполнять commit, push, merge или deploy без отдельного прямого разрешения пользователя.

## Review Focus

1. **Нет record / record просрочен во время уже запущенного процесса:** следующий внешний вызов блокируется, локальный план и `auto_run` intent сохраняются.
2. **Record разрешает send, но не history/join/reaction:** запрещённый auxiliary call не выполняется и не маскируется разрешением send.
3. **Provider принял сообщение, а cleanup/reseal упал:** operation остаётся accepted/held, повтор и второй budget effect невозможны.
4. **Restore вернул старый `auto_run=1`:** внешний recovery hold переживает restore и блокирует scheduler/manual/auxiliary paths до явного release.
5. **Сессия создана в PyMax 2.4.0:** 2.4.1 до первого сетевого вызова один раз сохраняет отсутствующий `user_agent`, один раз заполняет пустой legacy `mt_instance_id` и нормализует только `app_version/build_number` у уже сохранённого user-agent; token, device ID, непустой instance ID, device characteristics и sync-state не меняются, повторный запуск не генерирует новый fingerprint.

---

## Scope and file structure

Этот addendum владеет только следующими новыми границами:

- `app/platform_policy.py` — чистая загрузка и проверка несекретного authorization record.
- `app/services/max_gateway.py` — единственная разрешённая точка вызова MAX adapter и typed provider acknowledgement.
- `app/services/pymax_runtime.py` — единственная версионно-зависимая конфигурация PyMax 2.4.1, one-shot lifecycle и локальная миграция session identity.
- `app/recovery_hold.py` — внешний, не восстанавливаемый из backup operational hold.
- `scripts/release-recovery-hold.py` — отдельная явная команда release с revision/reference.
- `tests/test_platform_policy.py` — missing/expired/scope/action cases.
- `tests/test_max_gateway.py` — guard-before-network и provider acknowledgement.
- `tests/test_pymax_241_contract.py`, `tests/test_pymax_session_migration.py` — exact-version API contract, offline catalog, stable identity и backward-readable session schema.
- `tests/test_no_artificial_presence.py` — отсутствие history/read/reaction/idle/auto-join.
- `tests/test_recovery_hold.py` — restore/start/manual/scheduler fencing.
- `tests/test_external_action_boundaries.py` — архитектурная проверка, что raw SDK methods не вызываются вне gateway.
- `.env.example`, `docker-compose.yml`, `app/config.py`, `app/hooks.py`, `scripts/restore-volumes.sh`, `scripts/verify_deploy.sh`, `docs/PRODUCTION-OPS.md` — operational wiring без изменения business targets.
- `main.py`, `app/campaign_send.py`, `app/campaign_worker.py`, `app/routes_campaign.py`, `app/routes_profiles.py`, `app/routes_groups.py`, `app/routes_settings.py`, `app/settings_scope.py`, `static/index.html`, `static/admin.html`, `static/js/index.js`, `static/js/admin.js` — минимальная интеграция safety boundary; глубокая переработка остаётся у соответствующих Master-задач.

Master V3 остаётся владельцем operation ledger, daily plans, message versions, UI redesign, observability и остальных `T00..T33`. Не создавать конкурирующие таблицы/сервисы с другими именами.

### Task 0: ENV-00 — Воспроизводимое локальное окружение

**Files:**

- Create locally, ignored: `.venv/`
- Read only: `requirements.lock`, `requirements-server.lock`, `requirements-dev.txt`, `.github/workflows/ci.yml`, `docker-compose.yml`, `.env.example`
- Do not create: `.env`
- Do not modify: production dependency manifests, Docker volumes или application code

**Interfaces:**

- Consumes: Python 3.12, network access к PyPI для первой установки, Git, Node.js, Docker CLI/Compose/Buildx и доступный Docker daemon.
- Produces: `ENV_SOURCE_READY=PASS` и `ENV_DOCKER_READY=PASS`; версии инструментов и ограничения среды переносятся в baseline `S04` без secrets.

- [ ] **Step 1: Проверить системный toolchain без установки и запуска services**

Run:

```bash
python3.12 --version
python3.12 -m venv --help
git --version
node --version
docker --version
docker compose version
docker buildx version
openssl version
command -v sha256sum
command -v mktemp
python3.12 -c "import sqlite3; print(sqlite3.sqlite_version)"
```

Expected: все команды завершаются с exit `0`, Python имеет major/minor `3.12`. Отдельные host binaries `sqlite3` и `jq` не требуются: SQLite используется через Python, текущие project scripts не используют `jq`.

- [ ] **Step 2: Создать ignored venv и установить зафиксированные project dependencies и dev tools**

Run:

```bash
python3.12 -m venv .venv
PIP_CACHE_DIR=/tmp/maxbot-pip-cache .venv/bin/python -m pip install --disable-pip-version-check \
  -r requirements.lock \
  -r requirements-server.lock \
  -r requirements-dev.txt
PIP_CACHE_DIR=/tmp/maxbot-pip-cache .venv/bin/python -m pip install --disable-pip-version-check \
  pip-tools==7.6.1 pip-audit==2.10.1
```

Expected: установка выполняется только внутри `.venv/`; network denial означает `BLOCKED` и требует явного разрешения на download, а не fallback на system Python или незапиненный Git dependency. `pip-tools` и `pip-audit` являются execution tooling и не добавляются в production requirements.

- [ ] **Step 3: Подтвердить source/test readiness без MAX network**

Run:

```bash
.venv/bin/python -m pip check
.venv/bin/python -m pytest --version
.venv/bin/python -m piptools --version
.venv/bin/pip-audit --version
.venv/bin/python -c "from importlib.metadata import version; assert version('maxapi-python') == '2.4.0'; assert version('pip-tools') == '7.6.1'; assert version('pip-audit') == '2.10.1'"
env MAX_TEST=1 MAX_SERVER_MODE=1 JWT_SECRET=ci-jwt-secret-at-least-32-characters-long \
  .venv/bin/python -m pytest --collect-only -q
if rg -n '@pytest\.mark\.asyncio' tests; then
  echo "pytest-asyncio style is not allowed by ENV-00" >&2
  exit 1
fi
```

Expected: все команды завершаются с exit `0`; `pip check` PASS, baseline PyMax ровно `2.4.0`, pytest собирает ненулевое число tests без MAX socket/SMS/login, тесты не зависят от `pytest-asyncio`. После этого `ENV_SOURCE_READY=PASS`.

- [ ] **Step 4: Подтвердить Compose и Docker readiness без `.env` и без запуска контейнеров**

Run:

```bash
env \
  DOMAIN=ci.example.com \
  LETSENCRYPT_EMAIL=ci@example.com \
  JWT_SECRET=ci-jwt-secret-at-least-32-characters-long \
  ADMIN_EMAIL=admin@ci.example.com \
  ADMIN_PASSWORD=ci-admin-password \
  POSTGRES_PASSWORD=ci-postgres-password \
  REDIS_PASSWORD=ci-redis-password \
  INTERNAL_SERVICE_TOKEN=ci-internal-service-token \
  docker compose --env-file /dev/null config -q
docker info --format '{{.ServerVersion}}'
git status --short
```

Expected: Compose validation и Docker daemon probe завершаются с exit `0`; `.env`, containers и volumes не создаются, `.venv/` не появляется в `git status`. Если sandbox запрещает Docker socket, результат `BLOCKED` до успешного `docker info` из обычного operator terminal; не выдавать его за PASS. После этого `ENV_DOCKER_READY=PASS`.

### Task 1: S00 — Platform authorization value object и fail-closed parser

**Files:**

- Create: `app/platform_policy.py`
- Create: `tests/test_platform_policy.py`
- Modify: `app/config.py:1-105`
- Modify: `.env.example`
- Modify: `docs/PRODUCTION-OPS.md`

**Interfaces:**

- Consumes: UTC clock и путь `MAX_PLATFORM_AUTHORIZATION_FILE`; секретные значения не принимает.
- Produces: `MaxAction`, `MaxTransport`, `AuthorizationRecord`, `PlatformAuthorizationHold`, `load_authorization_record(path, now)`, `require_action(record, action, transport, now)`.

- [ ] **Step 1: Зафиксировать RED cases для отсутствующего, просроченного и неполного record**

```python
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.platform_policy import (
    MaxAction,
    MaxTransport,
    PlatformAuthorizationHold,
    load_authorization_record,
    require_action,
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def write_record(
    tmp_path: Path,
    *,
    allowed_actions: tuple[str, ...] = ("send",),
    valid_until: str = "2026-09-21T12:00:00Z",
) -> Path:
    path = tmp_path / "platform-authorization.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "reference": "MAX-COMPANY-PERMISSION-2026-001",
                "transport": "authorized_user_session",
                "allowed_actions": list(allowed_actions),
                "valid_from": "2026-09-20T00:00:00Z",
                "valid_until": valid_until,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_missing_record_blocks_send(tmp_path: Path) -> None:
    with pytest.raises(PlatformAuthorizationHold, match="record_missing"):
        load_authorization_record(tmp_path / "missing.json", now=NOW)


def test_expired_record_blocks_every_action(tmp_path: Path) -> None:
    path = write_record(tmp_path, valid_until="2026-09-20T11:59:59Z")
    with pytest.raises(PlatformAuthorizationHold, match="record_expired"):
        load_authorization_record(path, now=NOW)


def test_send_permission_does_not_authorize_join(tmp_path: Path) -> None:
    record = load_authorization_record(
        write_record(tmp_path, allowed_actions=("send",)), now=NOW
    )
    with pytest.raises(PlatformAuthorizationHold, match="action_not_allowed"):
        require_action(
            record,
            MaxAction.JOIN_DESTINATION,
            MaxTransport.AUTHORIZED_USER_SESSION,
            now=NOW,
        )
```

- [ ] **Step 2: Запустить RED test**

Run: `.venv/bin/python -m pytest tests/test_platform_policy.py -q`

Expected: FAIL при импорте `app.platform_policy`.

- [ ] **Step 3: Реализовать строгие типы и parser с ограниченным JSON**

```python
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal


class MaxAction(StrEnum):
    CONNECT = "connect"
    REQUEST_OTP = "request_otp"
    VERIFY_AUTH = "verify_auth"
    RESOLVE_DESTINATION = "resolve_destination"
    CHECK_DESTINATION = "check_destination"
    JOIN_DESTINATION = "join_destination"
    SEND = "send"
    FETCH_HISTORY = "fetch_history"
    MARK_READ = "mark_read"
    ADD_REACTION = "add_reaction"
    PROBE = "probe"


class MaxTransport(StrEnum):
    AUTHORIZED_USER_SESSION = "authorized_user_session"
    FAKE = "fake"


@dataclass(frozen=True, slots=True)
class AuthorizationRecord:
    schema_version: Literal[1]
    reference: str
    transport: MaxTransport
    allowed_actions: frozenset[MaxAction]
    valid_from: datetime
    valid_until: datetime


class PlatformAuthorizationHold(RuntimeError):
    pass


_RECORD_FIELDS = {
    "schema_version",
    "reference",
    "transport",
    "allowed_actions",
    "valid_from",
    "valid_until",
}


def _aware_datetime(raw: object) -> datetime:
    value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise PlatformAuthorizationHold("timestamp_not_aware")
    return value


def load_authorization_record(path: Path, *, now: datetime) -> AuthorizationRecord:
    if not path.is_file():
        raise PlatformAuthorizationHold("record_missing")
    raw = path.read_bytes()
    if len(raw) > 16 * 1024:
        raise PlatformAuthorizationHold("record_too_large")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlatformAuthorizationHold("record_malformed") from exc
    if not isinstance(payload, dict) or set(payload) != _RECORD_FIELDS:
        raise PlatformAuthorizationHold("record_fields_invalid")
    if payload["schema_version"] != 1:
        raise PlatformAuthorizationHold("record_version_invalid")
    reference = str(payload["reference"])
    if not 1 <= len(reference) <= 200 or not reference.isprintable():
        raise PlatformAuthorizationHold("record_reference_invalid")
    if payload["transport"] != MaxTransport.AUTHORIZED_USER_SESSION.value:
        raise PlatformAuthorizationHold("transport_not_supported")
    try:
        actions = frozenset(MaxAction(value) for value in payload["allowed_actions"])
    except (TypeError, ValueError) as exc:
        raise PlatformAuthorizationHold("record_actions_invalid") from exc
    valid_from = _aware_datetime(payload["valid_from"])
    valid_until = _aware_datetime(payload["valid_until"])
    record = AuthorizationRecord(
        schema_version=1,
        reference=reference,
        transport=MaxTransport.AUTHORIZED_USER_SESSION,
        allowed_actions=actions,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    if valid_from >= valid_until:
        raise PlatformAuthorizationHold("record_window_invalid")
    require_action_window(record, now=now)
    return record


def require_action_window(record: AuthorizationRecord, *, now: datetime) -> None:
    if now < record.valid_from or now >= record.valid_until:
        raise PlatformAuthorizationHold("record_expired")


def require_action(
    record: AuthorizationRecord,
    action: MaxAction,
    transport: MaxTransport,
    *,
    now: datetime,
) -> None:
    require_action_window(record, now=now)
    if record.transport is not transport:
        raise PlatformAuthorizationHold("transport_mismatch")
    if action not in record.allowed_actions:
        raise PlatformAuthorizationHold("action_not_allowed")
```

Parser должен:

- читать не более 16 KiB;
- требовать `schema_version == 1`;
- принимать только timezone-aware ISO-8601 timestamps;
- ограничить `reference` 1..200 printable characters;
- запрещать неизвестные поля и неизвестные actions;
- не поддерживать wildcard actions;
- не принимать `fake` из production file; `fake` создаётся только напрямую в fixtures.

- [ ] **Step 4: Добавить config getter без import-time I/O**

```python
def platform_authorization_file() -> Path | None:
    raw = os.environ.get("MAX_PLATFORM_AUTHORIZATION_FILE", "").strip()
    return Path(raw) if raw else None
```

Не загружать record при импорте `app.config`: expiry должен проверяться перед каждым новым внешним действием, а tests должны управлять clock.

- [ ] **Step 5: Добавить пример только с несекретными полями**

`.env.example` содержит закомментированный путь, но не фальшивое разрешение:

```dotenv
# Fail closed when unset. File contains a non-secret approval reference/scope only.
# MAX_PLATFORM_AUTHORIZATION_FILE=/app/control/platform-authorization.json
```

В `docs/PRODUCTION-OPS.md` явно записать: операторский JSON не доказывает подлинность договора; reviewer проверяет underlying authorization отдельно, а runtime лишь применяет его declared scope/expiry.

- [ ] **Step 6: Запустить focused tests**

Run: `.venv/bin/python -m pytest tests/test_platform_policy.py -q`

Expected: PASS для missing, malformed, expired, future, transport mismatch, action mismatch и exact allow cases.

- [ ] **Step 7: Проверить diff и остановиться перед commit**

Run: `git diff --check && git status --short`

Expected: только перечисленные файлы; commit выполняется лишь после отдельного разрешения пользователя.

### Task 2: S01 — Guarded MAX gateway и capability gate

**Files:**

- Create: `app/services/max_gateway.py`
- Create: `tests/test_max_gateway.py`
- Create: `tests/test_external_action_boundaries.py`
- Modify: `main.py:1157-1412`
- Modify: `app/campaign_send.py:230-364`
- Modify: `app/routes_profiles.py:122-215`

**Interfaces:**

- Consumes: `AuthorizationRecord`, `MaxAction`, scoped profile/route/destination context, underlying adapter protocol.
- Produces: `TransportCapabilities`, `ProviderAck`, `ProviderContractError`, `GuardedMaxGateway`, `assert_live_transport_ready(capabilities, record)`.

- [ ] **Step 1: Написать RED test — guard срабатывает до network method**

```python
import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.platform_policy import AuthorizationRecord, MaxAction, MaxTransport

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


class FakeAdapter:
    def __init__(self, send_result=None) -> None:
        self.calls: list[tuple[str, object]] = []
        self.send_result = send_result or SimpleNamespace(id="provider-17", chat_id=7)

    async def send_message(self, *, chat_id: int, text: str):
        self.calls.append(("send", {"chat_id": chat_id, "text": text}))
        return self.send_result


def record(*, expires_delta: timedelta) -> AuthorizationRecord:
    return AuthorizationRecord(
        schema_version=1,
        reference="MAX-COMPANY-PERMISSION-2026-001",
        transport=MaxTransport.AUTHORIZED_USER_SESSION,
        allowed_actions=frozenset({MaxAction.SEND}),
        valid_from=NOW - timedelta(hours=1),
        valid_until=NOW + expires_delta,
    )


def test_send_is_blocked_before_adapter_call() -> None:
    async def run() -> None:
        adapter = FakeAdapter()
        gateway = GuardedMaxGateway(
            adapter=adapter,
            record=record(expires_delta=timedelta(seconds=-1)),
            clock=lambda: NOW,
        )

        with pytest.raises(PlatformAuthorizationHold):
            await gateway.send_message(chat_id=7, text="fixture")

        assert adapter.calls == []

    asyncio.run(run())
```

- [ ] **Step 2: Написать RED test — acknowledgement обязан иметь внешний ID**

```python
def test_send_requires_provider_message_id() -> None:
    async def run() -> None:
        adapter = FakeAdapter(send_result=SimpleNamespace(id=None, chat_id=7))
        gateway = GuardedMaxGateway(
            adapter=adapter,
            record=record(expires_delta=timedelta(days=1)),
            clock=lambda: NOW,
        )

        with pytest.raises(ProviderContractError, match="missing_message_id"):
            await gateway.send_message(chat_id=7, text="fixture")

    asyncio.run(run())
```

- [ ] **Step 3: Запустить RED tests**

Run: `.venv/bin/python -m pytest tests/test_max_gateway.py -q`

Expected: FAIL при отсутствии gateway/types.

- [ ] **Step 4: Реализовать typed gateway без fallback на raw success**

```python
from dataclasses import dataclass
from datetime import UTC, datetime

from app.platform_policy import (
    AuthorizationRecord,
    MaxAction,
    MaxTransport,
    require_action,
)


@dataclass(frozen=True, slots=True)
class TransportCapabilities:
    name: str
    official: bool
    stable_identity: bool
    provider_ack_id: bool


@dataclass(frozen=True, slots=True)
class ProviderAck:
    message_id: str
    chat_id: str
    accepted_at: datetime


class ProviderContractError(RuntimeError):
    pass


class GuardedMaxGateway:
    def __init__(self, adapter, record: AuthorizationRecord, *, clock) -> None:
        self._adapter = adapter
        self._record = record
        self._clock = clock

    def _require(self, action: MaxAction) -> None:
        require_action(
            self._record,
            action,
            MaxTransport.AUTHORIZED_USER_SESSION,
            now=self._clock(),
        )

    async def send_message(self, *, chat_id: int, text: str) -> ProviderAck:
        self._require(MaxAction.SEND)
        result = await self._adapter.send_message(chat_id=chat_id, text=text)
        message_id = str(getattr(result, "id", "") or "").strip()
        if not message_id:
            raise ProviderContractError("missing_message_id")
        return ProviderAck(
            message_id=message_id,
            chat_id=str(chat_id),
            accepted_at=self._clock().astimezone(UTC),
        )
```

Каждый gateway method вызывает свой action: connect, OTP, auth verify, resolve, destination check, join, send, history, read, reaction и probe нельзя объединять под одним разрешением `SEND`.

- [ ] **Step 5: Ввести capability gate для live adapter**

```python
def assert_live_transport_ready(
    capabilities: TransportCapabilities,
    record: AuthorizationRecord,
) -> None:
    if record.transport is MaxTransport.AUTHORIZED_USER_SESSION:
        if not capabilities.stable_identity:
            raise PlatformAuthorizationHold("unstable_client_identity")
        if not capabilities.provider_ack_id:
            raise PlatformAuthorizationHold("provider_ack_unverified")
```

Для PyMax adapter `official=False`. Целевая библиотека — только `maxapi-python==2.4.1` после `S02A`; adapter может стать live-ready лишь при проверенном MAX Company authorization reference и после доказательства stable identity/provider ack в `S02A` и Master `T06`. До этого local fake tests работают, live methods остаются held.

- [ ] **Step 6: Заменить прямой send результатом `ProviderAck`**

`app/campaign_send.py` не вызывает `mark_accepted()` до получения `ProviderAck` и не содержит ветку принудительного promotion:

```python
ack = await gateway.send_message(chat_id=chat_id, text=final_text)
tracker.mark_accepted(provider_message_id=ack.message_id)
```

Полная долговечная финализация выполняется Master `T12`; до неё gateway change нельзя выкатывать отдельно как доказательство duplicate safety.

- [ ] **Step 7: Добавить архитектурный test raw boundaries**

`tests/test_external_action_boundaries.py` разбирает Python AST и разрешает raw вызовы `send_message`, `join_group`, `fetch_history`, `read_message`, `add_reaction` только внутри `app/services/max_gateway.py` и test fakes. Строковый поиск не закрывает semantic tests, но предотвращает новый обход gateway.

- [ ] **Step 8: Запустить focused tests и compile check**

Run: `.venv/bin/python -m pytest tests/test_platform_policy.py tests/test_max_gateway.py tests/test_external_action_boundaries.py -q`

Run: `.venv/bin/python -m compileall -q main.py app tests`

Expected: PASS; fake adapter call count подтверждает guard-before-network.

- [ ] **Step 9: Проверить diff и остановиться перед commit**

Run: `git diff --check && git status --short`

Expected: изменения только Task 2 и согласованные Task 1 interfaces.

### Task 3: S02 — Удалить artificial side effects, auto-join и rotating identity с live path

**Files:**

- Create: `tests/test_no_artificial_presence.py`
- Modify: `main.py:158-229,1190-1212,1397-1412,1963-2072`
- Modify: `app/campaign_send.py:267-277`
- Modify: `app/campaign_worker.py:400-430`
- Modify: `app/routes_settings.py:43-129`
- Modify: `app/settings_scope.py:15-70`
- Modify: `static/index.html:865-888`
- Modify: `static/admin.html:474-497`
- Modify: `static/js/index.js:1566-1698`
- Modify: `static/js/admin.js:187-290`

**Interfaces:**

- Consumes: gateway actions from Task 2; Master pacing contract leaves local delays/windows intact.
- Produces: `DestinationAuthorizationError`; no synthetic external presence operations; `resolve_chat_id` is resolve-only; legacy presence settings remain exportable/auditable but inactive.

- [ ] **Step 1: Написать RED tests для send и idle paths**

```python
import asyncio
from pathlib import Path
import pytest

from main import DestinationAuthorizationError, resolve_chat_id


class ResolveOnlyGateway:
    def __init__(self) -> None:
        self.actions: list[str] = []

    async def resolve_group_by_link(self, link: str):
        self.actions.append("resolve_destination")
        return None


def test_campaign_paths_do_not_call_presence_helpers() -> None:
    send_source = Path("app/campaign_send.py").read_text(encoding="utf-8-sig")
    worker_source = Path("app/campaign_worker.py").read_text(encoding="utf-8-sig")
    assert "_human_presence_before_send(" not in send_source
    assert "_maybe_idle_presence(" not in worker_source


def test_missing_destination_does_not_join() -> None:
    async def run() -> None:
        gateway = ResolveOnlyGateway()
        group = {"max_chat_id": "", "invite_link": "https://max.ru/join/fixture"}
        with pytest.raises(DestinationAuthorizationError):
            await resolve_chat_id(gateway, group)
        assert gateway.actions == ["resolve_destination"]

    asyncio.run(run())
```

В этом же файле semantic gateway test создаёт record только с `SEND`, вызывает `GuardedMaxGateway.send_message()` и проверяет, что fake adapter получил ровно один `send`, без history/read/reaction methods. Source assertion остаётся дополнительным regression shield, а не единственным доказательством.

- [ ] **Step 2: Запустить RED tests**

Run: `.venv/bin/python -m pytest tests/test_no_artificial_presence.py -q`

Expected: FAIL, потому что текущий send вызывает history/read/reaction, worker вызывает idle presence, а resolver способен join.

- [ ] **Step 3: Убрать внешнюю artificial presence, сохранив обычный pacing**

Удалить вызов `_human_presence_before_send()` из send path и `_maybe_idle_presence()` из worker loop. Не заменять их другими сетевыми действиями. `sleep_send_delay`, рабочие окна, server retry-after и персональные deadlines остаются у Master `T13`.

```python
chat_id = await resolve_chat_id(gateway, group)
await gateway.get_chat(chat_id)
ack = await gateway.send_message(chat_id=chat_id, text=final_text)
```

- [ ] **Step 4: Сделать destination resolution fail closed**

```python
from collections.abc import Mapping


async def resolve_chat_id(
    gateway: GuardedMaxGateway,
    group: Mapping[str, object],
) -> str:
    cached = str(group["max_chat_id"] or "").strip()
    if cached:
        return cached
    link = str(group["invite_link"] or "").strip()
    chat = await gateway.resolve_group_by_link(link)
    if chat is None:
        raise DestinationAuthorizationError("membership_or_destination_not_verified")
    return str(chat.id)
```

Отдельный явный join workflow в этом addendum не создаётся. Если продукту он нужен, он получает собственный owner-approved spec, permission, confirmation и audit trail.

- [ ] **Step 5: Сохранить legacy settings без рабочего side effect**

Новые install defaults получают `human_presence_enabled="0"`. Существующие DB values не перезаписываются и доступны в audit/export. API возвращает metadata:

```json
{
  "deprecated_inactive": [
    "human_presence_enabled",
    "presence_history_chance",
    "presence_read_chance",
    "presence_react_chance",
    "presence_reactions",
    "presence_idle_chance"
  ]
}
```

Frontend показывает read-only notice «Искусственное присутствие отключено политикой безопасности» и не отправляет эти поля в `PUT /api/settings`. `human_texts_enabled` и редакционные render/dedupe настройки не смешивать с сетевой presence-группой; их точная семантика остаётся у `T15`.

- [ ] **Step 6: Убрать генерацию identity из каждого client initialization**

Удалить `_prefer_current_max_user_agent()` и `_preferred_max_app_versions()` из live initialization до обновления зависимости. Не считать `user_agent=None` исправлением: capability gate Task 2 остаётся `stable_identity=False`, пока `S02A` не мигрирует legacy session, не докажет повторное использование одной identity и не пройдёт Master `T06`.

Генерация mobile user-agent допускается только один раз для конкретной identity: для legacy session без payload — внутри локальной, выполняемой до сети миграции `S02A`; для новой login-session — один раз штатным PyMax 2.4.1 с последующей проверкой сохранения. Уже сохранённый payload меняет только `app_version/build_number` на pinned catalog values, сохраняя device characteristics. Regression test подтверждает, что обычные connect/send paths получают полную persisted identity явно, не вызывают `generate_user_agent()` повторно и не подменяют её.

- [ ] **Step 7: Запустить backend и frontend focused checks**

Run: `.venv/bin/python -m pytest tests/test_no_artificial_presence.py tests/test_max_gateway.py tests/test_setting_helpers.py -q`

Run: `node --check static/js/index.js && node --check static/js/admin.js`

Expected: PASS; ни один test action log не содержит history/read/reaction/join/idle.

- [ ] **Step 8: Проверить diff и остановиться перед commit**

Run: `git diff --check && git status --short`

Expected: legacy values не удалены миграцией, business pacing values не изменены.

### Task 4: S02A — Обязательная миграция и оптимизация под PyMax 2.4.1

Эта задача обязательна, а не optional upgrade. PyPI package pin меняется только после удаления 2.4.0-specific вызова `generate_user_agent()` в `S02`. Upstream PyMax release `v2.4.1` добавляет `Client.connect()`, version-aware runtime, сохранение user-agent в session и меняет default TCP host на `api2.oneme.ru`; проект обязан использовать эти контракты явно, а не полагаться на незафиксированные defaults. Сообщённое владельцем разрешение на использование PyMax учтено: dependency update не считается заблокированным; реальные MAX-вызовы по-прежнему проходят существующий разрешённый action scope через `S00/S01` и выполняются только отдельной live-командой.

Upstream evidence фиксируется на точной версии: [PyPI 2.4.1](https://pypi.org/project/maxapi-python/2.4.1/), [release notes](https://github.com/MaxApiTeam/PyMax/releases/tag/v2.4.1), [`Client.connect()` и version catalog](https://github.com/MaxApiTeam/PyMax/blob/v2.4.1/src/pymax/client.py), [`ExtraConfig` defaults/signature](https://github.com/MaxApiTeam/PyMax/blob/v2.4.1/src/pymax/config.py), [session schema migration](https://github.com/MaxApiTeam/PyMax/blob/v2.4.1/src/pymax/session/store.py) и [existing-session restore flow](https://github.com/MaxApiTeam/PyMax/blob/v2.4.1/src/pymax/app.py). Main branch или future release не являются доказательством для этой задачи.

Tagged `App.start()` восстанавливает/нормализует user-agent existing session в памяти до handshake, но на этом path не вызывает `save_session()` для полной строки. Поэтому проект не полагается на неявную запись: offline migration сохраняет нормализованную identity до сети, а runtime передаёт её в `ExtraConfig` явно.

«Оптимизация» здесь означает совместимость, предсказуемый one-shot lifecycle, стабильную identity и меньше фоновой активности. Она не повышает concurrency, reconnect/relogin frequency, число сообщений, скорость кампании или число вспомогательных MAX-вызовов.

**Files:**

- Create: `app/services/pymax_runtime.py`
- Create: `tests/test_pymax_241_contract.py`
- Create: `tests/test_pymax_session_migration.py`
- Modify: `requirements.txt:1`
- Regenerate: `requirements.lock`
- Modify: `main.py:854-879,1121-1361,2116-2165`
- Modify: `antiban_core.py:239-245`
- Modify: `tests/test_max_client_version.py`
- Modify: `tests/test_session_send_no_otp.py`
- Modify: `tests/test_wave2_high.py`
- Modify: `tests/test_cloud_password.py`
- Modify: `docs/PRODUCTION-OPS.md`

`requirements-server.lock`, database business schema, sender selection, pacing, daily plans и message library не принадлежат этой задаче и не должны измениться.

**Interfaces:**

- Consumes: `GuardedMaxGateway`/`ProviderAck` из `S01`, отсутствие per-connect identity generation из `S02`, текущие encrypted `session.db.enc` и `_profile_client_lock(profile_id)`.
- Produces: `PYMAX_REQUIRED_VERSION`, `PYMAX_TCP_HOST/PORT`, `PyMaxRuntimeInfo`, `PyMaxSessionIdentity`, `assert_pymax_contract()`, `build_pymax_client(...)`, `ensure_session_identity(...)`, `load_session_identity(...)`, one-shot `Client.connect()` lifecycle и один effective TCP target для client/proxy preflight.
- Invariant: local catalog only (`VersionCatalog(remote=False)`), `reconnect=False`, `relogin=False`, `telemetry=False`, `persist_session=True`; ни один из этих параметров не может молча вернуться к upstream default.

- [ ] **Step 1: Написать RED contract tests для точной версии и API 2.4.1**

```python
from importlib.metadata import version
from inspect import iscoroutinefunction, signature
from typing import get_type_hints

from pymax import Client, ExtraConfig, Message

from app.services.pymax_runtime import (
    PYMAX_REQUIRED_VERSION,
    build_extra_config,
    inspect_pymax_runtime,
)


def test_exact_pymax_241_contract() -> None:
    assert PYMAX_REQUIRED_VERSION == "2.4.1"
    assert version("maxapi-python") == PYMAX_REQUIRED_VERSION
    assert iscoroutinefunction(Client.connect)
    assert tuple(signature(ExtraConfig.generate_user_agent).parameters) == (
        "self",
        "app_version",
        "build_number",
    )
    assert get_type_hints(Client.send_message)["return"] is Message


def test_runtime_policy_is_fixed_and_quiet() -> None:
    info = inspect_pymax_runtime()
    extra = build_extra_config(proxy=None, identity=None)

    assert (info.tcp_host, info.tcp_port) == ("api2.oneme.ru", 443)
    assert info.remote_catalog is False
    assert extra.reconnect is False
    assert extra.relogin is False
    assert extra.telemetry is False
    assert extra.persist_session is True
```

Тест не открывает socket и не создаёт MAX client session. Проверка exact version намеренно падает и при `2.4.0`, и при случайном будущем upgrade.

- [ ] **Step 2: Написать RED test миграции synthetic PyMax 2.4.0 session**

`tests/test_pymax_session_migration.py` создаёт только fixture-token, никогда не копирует реальный `session.db`:

```python
import asyncio
import sqlite3

from app.services.pymax_runtime import build_extra_config, ensure_session_identity


LEGACY_SCHEMA = """
CREATE TABLE sessions (
    token TEXT NOT NULL PRIMARY KEY,
    device_id TEXT NOT NULL,
    phone TEXT NOT NULL,
    mt_instance_id TEXT NOT NULL DEFAULT '',
    chats_sync INTEGER NOT NULL DEFAULT -1,
    contacts_sync INTEGER NOT NULL DEFAULT -1,
    drafts_sync INTEGER NOT NULL DEFAULT -1,
    presence_sync INTEGER NOT NULL DEFAULT -1,
    config_hash TEXT NOT NULL DEFAULT ''
)
"""


def test_v240_session_gets_one_persisted_identity(tmp_path) -> None:
    db = tmp_path / "session.db"
    with sqlite3.connect(db) as conn:
        conn.execute(LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("fixture-token", "device-1", "+70000000000", "instance-1", 4, 5, 6, 7, "cfg"),
        )

    first_identity = asyncio.run(ensure_session_identity(tmp_path, "session.db"))
    assert first_identity.migrated is True
    with sqlite3.connect(db) as conn:
        first = conn.execute(
            "SELECT token, device_id, phone, mt_instance_id, chats_sync, contacts_sync, "
            "drafts_sync, presence_sync, config_hash, user_agent FROM sessions"
        ).fetchone()

    second_identity = asyncio.run(ensure_session_identity(tmp_path, "session.db"))
    assert second_identity.migrated is False
    with sqlite3.connect(db) as conn:
        second = conn.execute(
            "SELECT token, device_id, phone, mt_instance_id, chats_sync, contacts_sync, "
            "drafts_sync, presence_sync, config_hash, user_agent FROM sessions"
        ).fetchone()

    assert first == second
    assert first[:9] == (
        "fixture-token",
        "device-1",
        "+70000000000",
        "instance-1",
        4,
        5,
        6,
        7,
        "cfg",
    )
    assert first[9]
    assert first_identity.user_agent == second_identity.user_agent

    extra = build_extra_config(proxy=None, identity=second_identity)
    assert extra.device_id == "device-1"
    assert extra.mt_instance_id == "instance-1"
    assert extra.user_agent == second_identity.user_agent
```

В том же test module:

- exact 2.4.0 projection (`token..config_hash`, без `user_agent`) читает уже мигрированную таблицу — дополнительная nullable column не ломает старый reader;
- legacy row с пустым `mt_instance_id` получает одно значение из 16 hex-символов и сохраняет его при повторном вызове;
- row с уже сохранённым user-agent сохраняет device type/name, OS, screen, locale, timezone и arch, меняя только `app_version/build_number` на значения pinned local catalog;
- monkeypatch, запрещающий `ExtraConfig.generate_user_agent()`, доказывает, что ordinary existing-session adapter передаёт `PyMaxSessionIdentity` явно и не вызывает генератор при подготовке клиента.

- [ ] **Step 3: Запустить RED tests до dependency/code change**

Run: `.venv/bin/python -m pytest tests/test_pymax_241_contract.py tests/test_pymax_session_migration.py -q`

Expected: FAIL из-за установленного/pinned `2.4.0`, отсутствующего `Client.connect()` или отсутствующего `app.services.pymax_runtime`; socket к MAX не открывается.

- [ ] **Step 4: Зафиксировать wheel 2.4.1 и пересобрать основной lock**

Изменить только первую строку `requirements.txt`:

```text
maxapi-python==2.4.1
```

Перед lock regeneration скачать wheel без dependencies и проверить опубликованный PyPI digest:

```bash
PYMAX_WHEEL_DIR="$(mktemp -d /tmp/maxbot-pymax-241.XXXXXX)"
.venv/bin/python -m pip download --no-deps --only-binary=:all: --dest "$PYMAX_WHEEL_DIR" maxapi-python==2.4.1
sha256sum "$PYMAX_WHEEL_DIR/maxapi_python-2.4.1-py3-none-any.whl"
```

Expected SHA-256: `49c996cebebdcd490b8fc1424c84faad3c33d0b75eff4bb86cf1de9d968d76ea`.

Regenerate с Python 3.12 тем же способом, который записан в header текущего lock:

```bash
.venv/bin/python -m piptools compile --allow-unsafe --output-file=requirements.lock --strip-extras requirements.txt
```

Run: `rg -n '^maxapi-python==' requirements.txt requirements.lock && git diff -- requirements.txt requirements.lock requirements-server.lock`

Expected: оба production inputs фиксируют ровно `2.4.1`; `requirements-server.lock` не меняется. Любое неожиданное изменение transitive dependency сначала проверяется по wheel metadata и не принимается как incidental upgrade.

- [ ] **Step 5: Реализовать единый version/runtime contract**

`app/services/pymax_runtime.py` содержит единственное место создания `ExtraConfig`, `VersionCatalog` и `Client`:

```python
from dataclasses import dataclass
from importlib.metadata import version as package_version

from pymax import Client, ExtraConfig
from pymax.api.session.payloads import MobileUserAgentPayload
from pymax.auth import AuthFlow
from pymax.versions.catalog import VersionCatalog

PYMAX_REQUIRED_VERSION = "2.4.1"
PYMAX_TCP_HOST = "api2.oneme.ru"
PYMAX_TCP_PORT = 443


class PyMaxContractError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PyMaxRuntimeInfo:
    package_version: str
    app_version: str
    tcp_host: str
    tcp_port: int
    remote_catalog: bool


@dataclass(frozen=True, slots=True)
class PyMaxSessionIdentity:
    device_id: str
    mt_instance_id: str
    user_agent: MobileUserAgentPayload
    migrated: bool


def assert_pymax_contract() -> None:
    installed = package_version("maxapi-python")
    if installed != PYMAX_REQUIRED_VERSION:
        raise PyMaxContractError(
            f"maxapi-python {installed} installed; required {PYMAX_REQUIRED_VERSION}"
        )


def build_extra_config(
    *,
    proxy: str | None,
    identity: PyMaxSessionIdentity | None,
) -> ExtraConfig:
    assert_pymax_contract()
    if identity is not None:
        return ExtraConfig(
            host=PYMAX_TCP_HOST,
            port=PYMAX_TCP_PORT,
            use_ssl=True,
            proxy=proxy,
            reconnect=False,
            relogin=False,
            telemetry=False,
            persist_session=True,
            log_level="WARNING",
            device_id=identity.device_id,
            mt_instance_id=identity.mt_instance_id,
            user_agent=identity.user_agent,
        )
    return ExtraConfig(
        host=PYMAX_TCP_HOST,
        port=PYMAX_TCP_PORT,
        use_ssl=True,
        proxy=proxy,
        reconnect=False,
        relogin=False,
        telemetry=False,
        persist_session=True,
        log_level="WARNING",
    )


def inspect_pymax_runtime() -> PyMaxRuntimeInfo:
    extra = build_extra_config(proxy=None, identity=None)
    catalog = VersionCatalog(remote=False)
    return PyMaxRuntimeInfo(
        package_version=PYMAX_REQUIRED_VERSION,
        app_version=VersionCatalog.RECOMMENDED_APP_VERSION,
        tcp_host=extra.host,
        tcp_port=extra.port,
        remote_catalog=catalog.remote,
    )


def build_pymax_client(
    *,
    phone: str,
    work_dir: str,
    session_name: str,
    auth_flow: AuthFlow,
    proxy: str | None,
    identity: PyMaxSessionIdentity | None,
) -> Client:
    return Client(
        phone=phone,
        work_dir=work_dir,
        session_name=session_name,
        auth_flow=auth_flow,
        extra_config=build_extra_config(proxy=proxy, identity=identity),
        app_version=VersionCatalog.RECOMMENDED_APP_VERSION,
        catalog=VersionCatalog(remote=False),
    )
```

Не включать `VersionCatalog(remote=True)`: runtime download меняет handshake inputs вне lock/evidence. Не передавать host, app version или fingerprint из UI/settings. Не сохранять proxy credentials или session values в `PyMaxRuntimeInfo`/logs.

- [ ] **Step 6: Реализовать локальную one-time migration session identity**

До создания клиента, после `_decrypt_session()` и под `_profile_client_lock`, `ensure_session_identity()` использует публичные PyMax session models/store и bundled catalog:

```python
from pathlib import Path
from secrets import token_hex

from pymax.session.models import SessionInfo
from pymax.session.store import SessionStore


class PyMaxSessionMigrationError(RuntimeError):
    pass


def _validated_identity(
    session: SessionInfo,
    *,
    migrated: bool,
) -> PyMaxSessionIdentity:
    catalog = VersionCatalog(remote=False)
    app_version = VersionCatalog.RECOMMENDED_APP_VERSION
    fingerprint = catalog.resolve(app_version)
    if not session.device_id.strip():
        raise PyMaxSessionMigrationError("session_device_id_missing")
    if not session.mt_instance_id.strip():
        raise PyMaxSessionMigrationError("session_instance_id_missing")
    if session.user_agent is None:
        raise PyMaxSessionMigrationError("session_user_agent_missing")
    if (
        session.user_agent.app_version != app_version
        or session.user_agent.build_number != fingerprint.build_number
    ):
        raise PyMaxSessionMigrationError("session_user_agent_version_mismatch")
    return PyMaxSessionIdentity(
        device_id=session.device_id,
        mt_instance_id=session.mt_instance_id,
        user_agent=session.user_agent,
        migrated=migrated,
    )


async def load_session_identity(
    work_dir: Path,
    session_name: str,
) -> PyMaxSessionIdentity:
    store = SessionStore(str(work_dir), session_name)
    try:
        session = await store.load_session()
        if session is None:
            raise PyMaxSessionMigrationError("session_missing")
        return _validated_identity(session, migrated=False)
    finally:
        await store.close()


async def ensure_session_identity(
    work_dir: Path,
    session_name: str,
) -> PyMaxSessionIdentity:
    store = SessionStore(str(work_dir), session_name)
    try:
        session = await store.load_session()
        if session is None:
            raise PyMaxSessionMigrationError("session_missing")
        if not session.device_id.strip():
            raise PyMaxSessionMigrationError("session_device_id_missing")

        catalog = VersionCatalog(remote=False)
        app_version = VersionCatalog.RECOMMENDED_APP_VERSION
        fingerprint = catalog.resolve(app_version)
        mt_instance_id = (
            session.mt_instance_id
            if session.mt_instance_id.strip()
            else token_hex(8)
        )
        user_agent = (
            build_extra_config(proxy=None, identity=None).generate_user_agent(
                app_version,
                fingerprint.build_number,
            )
            if session.user_agent is None
            else session.user_agent.model_copy(
                update={
                    "app_version": app_version,
                    "build_number": fingerprint.build_number,
                }
            )
        )
        protected = (
            session.token,
            session.device_id,
            session.phone,
            session.sync.model_dump(),
        )
        migrated = (
            session.mt_instance_id != mt_instance_id
            or session.user_agent != user_agent
        )
        if migrated:
            await store.save_session(
                session.model_copy(
                    update={
                        "mt_instance_id": mt_instance_id,
                        "user_agent": user_agent,
                    }
                )
            )
        check = await store.load_session()
        if (
            check is None
            or check.mt_instance_id != mt_instance_id
            or check.user_agent != user_agent
        ):
            raise PyMaxSessionMigrationError("session_identity_not_persisted")
        if protected != (
            check.token,
            check.device_id,
            check.phone,
            check.sync.model_dump(),
        ):
            raise PyMaxSessionMigrationError("session_fields_changed")
        if session.mt_instance_id and check.mt_instance_id != session.mt_instance_id:
            raise PyMaxSessionMigrationError("session_instance_id_changed")
        return _validated_identity(check, migrated=migrated)
    finally:
        await store.close()
```

Функции не логируют `protected`/identity и не открывают transport. `ensure_session_identity()` вызывается только до сети: отсутствующий user-agent и пустой legacy instance ID создаются один раз, а существующий user-agent сохраняет все device characteristics. `load_session_identity()` ничего не исправляет и используется после новой авторизации: PyMax 2.4.1 обязан сам сохранить полный current user-agent и instance ID. Любая ошибка миграции/verification оставляет live capability `stable_identity=False` и блокирует send.

- [ ] **Step 7: Перевести client lifecycle на `Client.connect()`**

В `_with_decrypted_client()` удалить callback/background-task схему `on_start() + create_task(client.start()) + client._app.started`. Для существующей session последовательность становится:

```python
session_dir = _session_dir(profile_id)
has_existing_session = _session_db_has_token(profile_id)
if not login_mode and not has_existing_session:
    raise RuntimeError("session_required")
identity = (
    await ensure_session_identity(session_dir, "session.db")
    if has_existing_session
    else None
)

auth_flow = (
    _AppSmsAuthFlow(sms, pwd, profile_id)
    if login_mode
    else _SessionOnlyAuthFlow()
)
client = build_pymax_client(
    phone=phone,
    work_dir=str(session_dir),
    session_name="session.db",
    auth_flow=auth_flow,
    proxy=proxy,
    identity=identity,
)
timeout = auth_timeout if login_mode else connect_timeout
try:
    async with asyncio.timeout(timeout):
        await client.connect()
        result = await fn(client)
finally:
    await _safe_stop(client)
if login_mode:
    await load_session_identity(session_dir, "session.db")
return result
```

Сохранить внешний `try/finally` `_decrypt_session() -> _encrypt_session()` и session-only запрет OTP. Existing-session client, включая повторный явный login, всегда получает `PyMaxSessionIdentity`; `identity=None` разрешён только явной login-сессии без сохранённого token. Удалить более неиспользуемые `_wait_login_done()`, `_session_device_fields()` и обращения к private `client._app`. Timeout/cancellation обязаны дождаться `stop()` и reseal; cleanup exception после provider ack обрабатывается ledger/recovery задачей `T12`, а не повторной отправкой.

- [ ] **Step 8: Синхронизировать proxy preflight с effective PyMax target**

Изменить безопасный default `antiban_core.check_proxy()` на `api2.oneme.ru:443`, а production call передаёт target явно из `inspect_pymax_runtime()`:

```python
runtime = inspect_pymax_runtime()
ok, err = antiban_core.check_proxy(
    proxy_url,
    target_host=runtime.tcp_host,
    target_port=runtime.tcp_port,
)
```

Обновить `tests/test_wave2_high.py`: SOCKS5 payload и HTTP `CONNECT` содержат `api2.oneme.ru`, TLS к HTTPS proxy по-прежнему использует hostname самого proxy. Test only проверяет tunnel negotiation; он не отправляет handshake/login/MAX application data.

- [ ] **Step 9: Связать реальный 2.4.1 send result с `ProviderAck`**

Contract test подтверждает `Client.send_message(...) -> Message`; integration test передаёт объект с непустым `Message.id` через PyMax adapter в `GuardedMaxGateway` и проверяет сохранение точного provider ID. Empty/`None` ID даёт `ProviderContractError` и `unknown`, не `accepted`. Не использовать новые `send_at`, reactions, Voice/VideoNote или другие возможности 2.4.1: они не нужны текущей логике и расширяют внешний action surface.

- [ ] **Step 10: Запустить focused compatibility и safety gates**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_pymax_241_contract.py \
  tests/test_pymax_session_migration.py \
  tests/test_max_client_version.py \
  tests/test_session_send_no_otp.py \
  tests/test_cloud_password.py \
  tests/test_wave2_high.py \
  tests/test_max_gateway.py \
  tests/test_no_artificial_presence.py
.venv/bin/python -m pip check
.venv/bin/pip-audit -r requirements.lock
.venv/bin/python -m compileall -q main.py antiban_core.py app tests
```

Expected: PASS, ненулевое число tests, installed version ровно `2.4.1`, existing-session path явно передаёт persisted device/instance/user-agent и не вызывает генератор, ни один test не открывает MAX socket и session fixture не содержит реальных credentials. Required skip, timeout или отсутствие `pymax` означает `BLOCKED`, не PASS.

- [ ] **Step 11: Зафиксировать deploy/rollback boundary**

В `docs/PRODUCTION-OPS.md` записать:

- перед deploy остановить campaign owner, создать обычный encrypted-volume backup и включить `S03` recovery hold;
- rollback выполняется предыдущим целым image/commit с PyMax 2.4.0, а не заменой одного wheel внутри нового кода, потому что новый lifecycle использует `Client.connect()`;
- nullable `user_agent` column остаётся backward-readable для 2.4.0 и не удаляется при rollback;
- после deploy сначала выполнить offline/session-schema проверки, затем local fake smoke;
- реальный canary login/send не входит в эту задачу и требует отдельного bounded runbook с разрешёнными account/group/action и stop conditions.

- [ ] **Step 12: Проверить итоговый dependency/code diff и остановиться перед commit**

Run:

```bash
git diff --check
git diff -- requirements.txt requirements.lock requirements-server.lock
git status --short
```

Expected: exact pin `2.4.1`, отсутствие изменения `requirements-server.lock`, только перечисленные runtime/tests/docs paths. Не commit/push/deploy и не выполнять live MAX qualification без отдельной команды пользователя.

### Task 5: S03 — Persistent recovery hold и truthful deploy readiness

**Files:**

- Create: `app/recovery_hold.py`
- Create: `scripts/release-recovery-hold.py`
- Create: `tests/test_recovery_hold.py`
- Modify: `docker-compose.yml:1-155`
- Modify: `app/config.py:1-105`
- Modify: `app/hooks.py:9-56`
- Modify: `main.py:2816-2853`
- Modify: `app/routes_campaign.py:18-151`
- Modify: `scripts/restore-volumes.sh:13-97`
- Modify: `scripts/verify_deploy.sh:16-58`
- Modify: `docs/PRODUCTION-OPS.md`

**Interfaces:**

- Consumes: external control path outside restored `max_server_data`, platform policy status, Start/test/scheduler entry points.
- Produces: `RecoveryHold`, `load_recovery_hold()`, `require_recovery_released()`, `require_external_actions_released()`, explicit release command bound to restore revision.

- [ ] **Step 1: Написать RED test — restored `auto_run=1` не запускает внешнюю работу**

```python
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

import main as m


def write_hold(tmp_path: Path, *, revision: str) -> Path:
    path = tmp_path / "recovery-hold.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "revision": revision,
                "reason": "restore",
                "created_at": "2026-09-20T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_restore_hold_fences_auto_resume(tmp_path, monkeypatch) -> None:
    async def run() -> None:
        hold = write_hold(tmp_path, revision="restore-20260920-120000")
        monkeypatch.setenv("MAX_RECOVERY_HOLD_FILE", str(hold))
        start = AsyncMock()
        monkeypatch.setattr(m, "_auto_run_enabled", lambda: True)
        monkeypatch.setattr(m, "_start_worker", start)

        assert await m._try_auto_resume() is False

        start.assert_not_awaited()

    asyncio.run(run())
```

- [ ] **Step 2: Написать RED test — manual send и scheduler используют тот же hold**

```python
from app import recovery_hold
from app import routes_campaign


@pytest.mark.parametrize(
    "entrypoint",
    [routes_campaign.campaign_start, routes_campaign.campaign_test],
)
def test_manual_entrypoints_check_hold_before_preflight(
    entrypoint,
    monkeypatch,
) -> None:
    check = Mock(
        side_effect=recovery_hold.RecoveryHoldActive("recovery_hold_active")
    )
    monkeypatch.setattr(recovery_hold, "require_external_actions_released", check)

    with pytest.raises(recovery_hold.RecoveryHoldActive):
        asyncio.run(entrypoint())

    check.assert_called_once()
```

Gateway tests из Task 2 перед каждым external method вызывают тот же `require_external_actions_released`; scheduler покрывается через `_try_auto_resume`. Так manual, scheduled и auxiliary paths не получают отдельных трактовок hold.

- [ ] **Step 3: Запустить RED tests**

Run: `.venv/bin/python -m pytest tests/test_recovery_hold.py -q`

Expected: FAIL при отсутствии persistent hold.

- [ ] **Step 4: Реализовать hold вне восстанавливаемого data volume**

```python
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Literal

from app.config import recovery_hold_file


@dataclass(frozen=True, slots=True)
class RecoveryHold:
    schema_version: Literal[1]
    revision: str
    reason: str
    created_at: datetime


class RecoveryHoldActive(RuntimeError):
    pass


def load_recovery_hold(path: Path) -> RecoveryHold | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise RecoveryHoldActive("recovery_hold_invalid")
    return RecoveryHold(
        schema_version=1,
        revision=str(payload["revision"]),
        reason=str(payload["reason"]),
        created_at=datetime.fromisoformat(
            str(payload["created_at"]).replace("Z", "+00:00")
        ),
    )


def require_recovery_released(path: Path) -> None:
    if path.is_file():
        raise RecoveryHoldActive("recovery_hold_active")


def require_external_actions_released() -> None:
    path = recovery_hold_file()
    if path is not None:
        require_recovery_released(path)
```

Compose получает отдельный `max_server_control:/app/control` для app/celery. Restore archive не включает этот volume. Перед data swap `restore-volumes.sh` атомарно создаёт `/app/control/recovery-hold.json`; не удаляет его после `pg_restore` или health check.

- [ ] **Step 5: Добавить явный release command с revision match**

```bash
.venv/bin/python scripts/release-recovery-hold.py \
  --expected-revision restore-20260920-120000 \
  --authorization-reference OPS-CHANGE-1234
```

Команда:

- проверяет exact current revision;
- требует непустой несекретный authorization reference;
- пишет append-only release evidence до атомарного удаления hold;
- не меняет `auto_run`;
- не запускает worker сама.

- [ ] **Step 6: Исправить health loop с явным success flag**

```bash
run_internal_health_check() {
  docker compose exec -T app python -c '
import json, sys, urllib.request
r = urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=10)
d = json.loads(r.read())
print(json.dumps(d, ensure_ascii=False))
sys.exit(0 if d.get("db_ok") is True else 1)
'
}

health_ok=0
health_json=""
for i in $(seq 1 30); do
  if health_json=$(run_internal_health_check); then
    health_ok=1
    break
  fi
  sleep 3
done
if [[ "$health_ok" != "1" ]]; then
  echo "FAIL: readiness check did not succeed" >&2
  exit 1
fi
```

Health JSON отдельно показывает `max_external_actions: held|authorized` и `recovery_hold: true|false`. Базовая UI/DB readiness может быть green при held actions; production-send gate с `REQUIRE_MAX_ACTIONS=1` обязан завершаться non-zero при любом hold.

- [ ] **Step 7: Проверить restore и verify scripts без live services**

Run: `.venv/bin/python -m pytest tests/test_recovery_hold.py tests/test_backup_scripts.py -q`

Run: `bash -n scripts/restore-volumes.sh scripts/verify_deploy.sh`

Run: `DOMAIN=ci.example.com LETSENCRYPT_EMAIL=ci@example.com JWT_SECRET=ci-jwt-secret-at-least-32-characters-long ADMIN_EMAIL=admin@ci.example.com ADMIN_PASSWORD=ci-admin-password POSTGRES_PASSWORD=ci-postgres-password REDIS_PASSWORD=ci-redis-password INTERNAL_SERVICE_TOKEN=ci-internal-service-token docker compose config -q`

Expected: PASS; тест явно проверяет непустой `db_ok=false` как failure и наличие hold после успешного restore fixture.

- [ ] **Step 8: Проверить diff и остановиться перед commit**

Run: `git diff --check && git status --short`

Expected: восстановленный `auto_run` сохранён как intent, но ни один path не обходит hold.

### Task 6: S04 — Связать addendum с Master V3 evidence и task graph

**Files:**

- Create: `docs/audit/baseline.md`
- Create: `docs/audit/verification.md`
- Create: `verification/supplemental-acceptance-cases.json`
- Modify: `docs/audit/2026-09-20-maxbot-master-v3-independent-audit.md`

**Interfaces:**

- Consumes: `ENV-00`, `S00`, `S01`, `S02`, `S02A`, `S03`, Master `T00..T33`, exact candidate SHA и команды/evidence.
- Produces: однозначная матрица `requirement -> owner task -> test -> result -> evidence`, не меняющая исходные ID Master.

- [ ] **Step 1: Создать acceptance manifest с новыми IDs**

```json
{
  "schema_version": 1,
  "source_master_sha256": "8c7a57092be519ea5df0379abc6030124d1e099867adbc72a06174027c90392d",
  "cases": [
    {"id": "SUP-01-C01", "owner": "S00", "test": "tests/test_platform_policy.py", "status": "NOT_RUN"},
    {"id": "SUP-01-C02", "owner": "S01", "test": "tests/test_external_action_boundaries.py", "status": "NOT_RUN"},
    {"id": "SUP-02-C01", "owner": "S02", "test": "tests/test_no_artificial_presence.py", "status": "NOT_RUN"},
    {"id": "PYMAX-241-C01", "owner": "S02A", "test": "tests/test_pymax_241_contract.py", "status": "NOT_RUN"},
    {"id": "PYMAX-241-C02", "owner": "S02A", "test": "tests/test_pymax_session_migration.py", "status": "NOT_RUN"},
    {"id": "SUP-03-C01", "owner": "S03", "test": "tests/test_recovery_hold.py", "status": "NOT_RUN"}
  ]
}
```

- [ ] **Step 2: Записать baseline без optimistic status**

`docs/audit/baseline.md` содержит:

- current `HEAD`, dirty state и startup modes;
- `ENV_SOURCE_READY/ENV_DOCKER_READY`, Python/pytest/pip-tools/pip-audit/Node/Docker/Compose/Buildx versions и ограничения sandbox;
- installed dependency versions и inspected SDK signatures, включая exact `maxapi-python==2.4.1`, wheel SHA-256 и effective host/catalog/telemetry policy;
- применимость `AUD20-A01..A46`, `COMP-R01..R12`, `SUP-01..SUP-02`;
- platform authorization state `PRESENT/ABSENT/EXPIRED/SCOPE_MISMATCH`, без содержимого договора;
- live verification `BLOCKED`, пока нет отдельного разрешения;
- known local test-harness limitations.

- [ ] **Step 3: Записать verification schema**

Каждая строка `docs/audit/verification.md` использует поля:

```text
case_id | candidate_sha | command | environment | started_at | exit_code | result | evidence_ref | limitation
```

Допустимые результаты: `PASS`, `FAIL`, `BLOCKED`, `NOT RUN`. Timeout и skipped mandatory case — не PASS.

- [ ] **Step 4: Вставить addendum в существующий task graph**

Зафиксировать порядок:

```text
ENV-00 -> S00
S00 -> T00/T01
T01/T02 -> S01
S01 -> S02 -> S02A
S02A -> T03/T06/T12
S02 integrates with T11/T13
S03 integrates with T10/T14/T28
T15 -> T33 -> T14 remains unchanged
S04 -> T29/T30
S05 -> T32
```

- [ ] **Step 5: Проверить JSON и ссылки**

Run: `.venv/bin/python -m json.tool verification/supplemental-acceptance-cases.json >/dev/null`

Run: `rg -n "ENV-00|SUP-01|SUP-02|PYMAX-241|S00|S01|S02|S02A|S03|S04|S05" docs/audit docs/superpowers/plans verification`

Expected: у каждого supplemental case один primary owner; исходные IDs Master не перенумерованы.

- [ ] **Step 6: Проверить diff и остановиться перед commit**

Run: `git diff --check && git status --short`

Expected: evidence не содержит secrets, raw account/session/proxy data или ложных PASS.

### Task 7: Выполнить нормативные Master-задачи в безопасных волнах

**Files:**

- Modify/Create: только paths, перечисленные внутри соответствующей `Txx` секции Master V3.
- Test: acceptance cases, принадлежащие этой `Txx`, плюс все ранее пройденные negative regressions.

**Interfaces:**

- Consumes: environment gates `ENV_SOURCE_READY/ENV_DOCKER_READY`, platform/gateway/PyMax/hold contracts `S00`, `S01`, `S02`, `S02A`, `S03`, `S04` и resolved contracts Master.
- Produces: по одной independently reviewable волне; следующая волна не начинается при незакрытом mandatory gate предыдущей.

- [ ] **Step 1: Волна A — baseline и безопасные границы**

Выполнить `T00`, `T01`, затем `T02`, `T03`. Зафиксировать current source, fake MAX harness, data scopes и typed errors. Не выполнять live calls для проверки adapter.

Gate: `ENV_SOURCE_READY=PASS`; все acceptance cases этих задач, `SUP-01-C01/C02` и `PYMAX-241-C01/C02` имеют evidence; platform state может оставаться `BLOCKED`, но обхода нет.

- [ ] **Step 2: Волна B — connection/session/storage foundation**

Выполнить `T04`, `T05`, `T06`, `T07`, `T08`, `T09`, `T10`, `T11` с интеграцией `S01`, `S02`, `S02A`, `S03`.

Gate:

- один persisted route per account во всех client paths;
- installed/locked `maxapi-python` равен ровно `2.4.1`, lifecycle использует `Client.connect()`, а proxy preflight проверяет effective `api2.oneme.ru:443`;
- telemetry и remote version catalog выключены, legacy session имеет persisted device ID, непустой instance ID и полный current user-agent; existing-session runtime передаёт их явно и не вращает device characteristics;
- ordinary failure не удаляет session;
- delete/shutdown cancel-and-await bounded;
- vault migration lossless;
- restore остаётся held;
- destination change invalidates cached resolution;
- no auto-join;
- разрешённый adapter имеет доказанные stable identity и provider acknowledgement, иначе live state остаётся held.

- [ ] **Step 3: Волна C — durable operation semantics**

Выполнить `T12`, затем `T13`. RED tests обязаны включать cleanup-after-ack, persistence failure, cancellation, process death, retry-after, midnight и auxiliary sanction.

Gate: одна operation identity, numbered attempts, unique idempotent finalization, durable reservation, `unknown` occupancy и один sanction controller для всех разрешённых external actions.

- [ ] **Step 4: Волна D — library, personal plans и commands**

Выполнить строго `T15`, затем `T33`, затем `T14`.

Gate:

- library immutable/reusable;
- один account/day plan и личные slots;
- short pool использует отдельные личные passes без удаления source;
- manual test получает/исполняет реальный slot;
- Stop сначала сохраняет intent/control generation;
- preview не пишет и не вызывает MAX.

- [ ] **Step 5: Волна E — UI, status, performance и operations**

Выполнить `T16..T30` в зависимостях Master. UI не предлагает presence/auto-join/слепой resend. Browser evidence выполняется на 390/768/1440, с keyboard, console и failed network checks.

Gate: `ENV_DOCKER_READY=PASS`; обязательные security/dependency/DR/Compose/browser/full-regression проверки относятся к exact candidate SHA.

- [ ] **Step 6: Оставить T31 выключенным по умолчанию**

Исследование bounded client reuse не включает feature enablement. Нельзя обменивать устойчивость session/identity на большее число подключений или отправок.

- [ ] **Step 7: Передать exact candidate в S05/T32**

Run: `git status --short && git rev-parse HEAD`

Expected: candidate SHA зафиксирован; dirty-run evidence не выдаётся за commit-bound acceptance.

### Task 8: S05 — Полная проверка и release verdict

**Files:**

- Modify: `docs/audit/verification.md`
- Modify: `verification/supplemental-acceptance-cases.json`
- Modify: release evidence paths, определённые Master `T32`

**Interfaces:**

- Consumes: exact candidate SHA, все mandatory Master/supplemental cases, platform authorization review.
- Produces: только `GO` или `FIX`; production/live evidence остаётся отдельным gate.

- [ ] **Step 1: Запустить source/format/static gates**

Run:

```bash
.venv/bin/python -m compileall -q main.py antiban_core.py celery_worker.py app tests static
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -c "from importlib.metadata import version; assert version('maxapi-python') == '2.4.1'"
node --check static/js/index.js
node --check static/js/admin.js
git diff --check
```

Expected: exit 0, ненулевое число tests, нет required skips/timeouts. Если локальная среда снова не завершает thread/TestClient lifecycle, результат `BLOCKED`, а не PASS; воспроизводимый CI на exact candidate нужен отдельно.

- [ ] **Step 2: Запустить dependency, Compose и DR gates**

Run:

```bash
.venv/bin/pip-audit -r requirements.lock
.venv/bin/pip-audit -r requirements-server.lock
docker compose config -q
bash scripts/dr-smoke.sh
```

Expected: exit 0; DR проверяет два tenant scope, encrypted session/key material, known/unknown operations и active recovery hold, а не только marker files.

- [ ] **Step 3: Запустить browser gates без MAX network**

Проверить 390/768/1440 CSS px, console, failed requests, keyboard/focus, offline/auth expiry и held-action states. Fixtures используют fake gateway; browser test не должен иметь route к реальному MAX host.

- [ ] **Step 4: Выполнить независимую проверку platform authorization**

Reviewer сравнивает:

- reference и срок с underlying разрешением Компании;
- разрешённый transport с фактическим adapter/host/protocol;
- allowed actions с gateway action inventory;
- account/destination consent с Master `T11`;
- capability evidence stable identity/provider acknowledgement.

Самоподписанный JSON без underlying evidence даёт `FIX`, не `GO`.

- [ ] **Step 5: Выполнить adversarial recovery review**

Fault injection обязательно покрывает:

- смерть процесса до send, во время send и после provider ack;
- cleanup/reseal failure после ack;
- restart с abandoned in-flight;
- одновременные Start/Stop/test-send;
- midnight;
- restore старого backup с `auto_run=1`;
- expiry/revocation platform record между двумя действиями;
- sanction на любом разрешённом auxiliary call.

- [ ] **Step 6: Выдать commit-bound verdict**

`GO` допустим только при `ENV_SOURCE_READY=PASS`, `ENV_DOCKER_READY=PASS`, полном обязательном evidence и отдельном разрешении на production verification. Любой незакрытый P1, required `NOT RUN/BLOCKED`, версия PyMax не ровно `2.4.1`, transport/host mismatch, включённые telemetry/remote catalog, artificial call, unstable identity или missing authorization означает `FIX`.

- [ ] **Step 7: Остановиться перед production и Git mutations**

Не commit/push/merge/deploy и не выполнять live MAX qualification без отдельной прямой команды пользователя. Перед live qualification подготовить отдельный bounded runbook с exact accounts, groups, actions, stop conditions и evidence redaction.

## Self-review notes

- Spec coverage: обязательный `ENV-00`, `SUP-01`, `SUP-02`, `PYMAX-241-C01/C02`, усиленный `COMP-R05`, `COMP-R12`, `AUD20-A35/A36` имеют owner tasks и gates/tests; остальные требования остаются у исходных `T00..T33`.
- Type consistency: `MaxAction`, `MaxTransport`, `AuthorizationRecord`, `ProviderAck`, `TransportCapabilities`, `PyMaxRuntimeInfo`, `PyMaxContractError`, `PyMaxSessionMigrationError` и `RecoveryHold` определены до первого потребителя.
- Core behavior: role rotation, targets, windows, library, personal plans, one-sender rule и legacy export не заменены новым продуктом.
- Ban-risk direction: план только сокращает неразрешённые/искусственные внешние действия, фиксирует одну session identity и исключает runtime dependency/catalog drift; он не обещает отсутствие блокировок и не предлагает обход detection.
- Execution boundary: официальный Bot API не внедряется скрыто; при отсутствии разрешения user-session live path остаётся held.
