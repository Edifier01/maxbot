# Аудит MAXBOT для запуска на production VPS — 2026-09-24

## Вердикт и границы проверки

**NO-GO для production с реальными действиями в MAX.** Проверен исходный код
`b2f82b739910f4c440c59efbf0d2e191ab744009` и текущее дерево с
незафиксированными изменениями документации. Это не проверка собранного образа
по точному SHA и не разрешение на запуск. Исправления и порядок получения
доказательств приведены в [плане запуска](../PRODUCTION-LAUNCH-PLAN-2026-09-24.md).

Проверка охватила FastAPI и UI, JWT/tenant, кампании и границу MAX, SQLite и
PostgreSQL, шифрование сессий, миграции, Compose/Docker/Caddy, CI/deploy,
backup/restore, документацию и тестовые ворота. Выводы ниже разделяют
подтверждённые статически дефекты, риск при определённом сценарии и
непроведённые проверки. На VPS, с рабочими данными и в MAX ничего не
запускалось.

## Главное внешнее условие

Продукт использует `maxapi-python==2.4.1` и **пользовательские сессии**:
`app/platform_policy.py` допускает только `authorized_user_session`, а
`app/services/max_gateway.py` оборачивает login, join, send и другие действия.
Файл `MAX_PLATFORM_AUTHORIZATION_FILE` содержит заявленную область разрешения,
но сам по себе не доказывает согласование с платформой. Пункт 1.5
[требований MAX](https://dev.max.ru/docs/legal/requirements) запрещает
использовать API или другую интеграцию для перечисленных служебных и массовых
сообщений, кроме случаев, прямо предусмотренных договором с компанией.
Для обработки персональных данных [правила MAX](https://dev.max.ru/docs/legal/rules)
требуют правового основания, уведомления и защиты данных. Нужна проверка
действующего договора применительно к **этому транспорту, типам сообщений,
аккаунтам, адресатам и объёму**; без неё live-этап закрыт. Официальный
[API MAX](https://dev.max.ru/docs-api) описывает токен чат-бота и HTTPS
`platform-api2.max.ru`; он не является готовой заменой пользовательским
сессиям и требует отдельного анализа функций и архитектуры.

## Реестр находок

Приоритет означает влияние на заявленную цель запуска, а не доказательство
эксплуатации уязвимости. `P0` — блокирует маршрут к запуску; `P1` — исправить
до первого live-действия; `P2` — закрыть до общего доступа или явно принять
ограниченный остаточный риск после проверки.

| ID | Приоритет и статус | Находка и доказательство | Критерий закрытия |
| --- | --- | --- | --- |
| A01 | **P0, разрешение подтверждено владельцем вне репозитория** | Пользователь 2026-09-24 подтвердил, что необходимые разрешения имеются. Само разрешение не приложено к репозиторию для проверки; это внешнее подтверждение, а не вывод аудита. `app/platform_policy.py`, `main.py:1939`, требования MAX п. 1.5. | При выпуске сверить scope/срок серверного authorization record и change record с подтверждённым владельцем разрешением; не хранить договор/персональные данные в Git. |
| A02 | **P0, базовый дефект исправлен локально; staging не проверен** | `.github/workflows/deploy.yml` теперь явно передаёт `CANDIDATE_SHA` через `envs`; требуется staging `workflow_dispatch`. [Инструкция action](https://github.com/appleboy/ssh-action/tree/v1.2.5). | Staging checkout ровно выбранного SHA; отрицательная проверка неверного SHA завершается до `docker compose up`. |
| A03 | **P1, исправлено локально** | Compose передаёт фиксированный путь к platform authorization и монтирует каталог хоста read-only; `.env.example` описывает `MAX_PLATFORM_AUTHORIZATION_DIR`. | Compose rendering и fixture-тесты проходят; на staging подтвердить, что фактический record присутствует и соответствует scope. |
| A04 | **P1, исправлено локально** | `app/recovery_hold.py` теперь проверяет record, срок, scope SEND и authorized user-session transport; health/preview fail closed при missing/invalid; проверки добавлены. | Перепроверить проверку `REQUIRE_MAX_ACTIONS=1` на точном staging image и все отрицательные fixture cases. |
| A05 | **P1, исправлено локально** | Скрипт release hold копируется в образ; `/app/control` создаётся и получает владельца при build/deploy. Изолированная сборка образа и fixture проверки прошли. | Staging упражнение release hold с ожидаемой и неверной revision, с сохранением evidence. |
| A06 | **P1, исправлено локально; Linux DR rehearsal открыт** | Backup сохраняет минимальный `auth-state.json`, не копируя hold. До любых изменений restore проверяет snapshot и доступ к control volume; затем увеличивает epoch выше snapshot и текущего epoch до запуска приложения. | Изолированный cross-host DR test с доресторным JWT, malformed snapshot rejection до stop/swap и активным hold после восстановления. |
| A07 | **P1, исправлено локально** | Backup прекращается при plaintext `session.db` в data tree/archive; auth snapshot/архив валидируются; добавлены regression tests. | Изолированный Linux backup/restore failure-injection; старые архивы всё ещё содержат ключевой материал и остаются секретными. |
| A08 | **P1, release evidence неполон** | `docs/audit/release-gate.md` сохраняет вердикт `FIX/PARTIAL`: нет закрытия 365 нормативных случаев, эталонного T30-C02, owner review истории секретов, полной UI/a11y проверки и VPS/live доказательств. Старые PASS привязаны к другим SHA или dirty tree. | Таблица Master T00–T33 закрыта по каждому обязательному случаю; exact-SHA CI, image, staging, DR, performance, UI и owner review приложены к release record. |
| A09 | **P2, исправлено локально** | JWT session validation сверяет текущие `role`/`tenant_id` с claims и повторно проверяет их при попадании в cache. | Регрессионные кейсы по downgrade роли, смене tenant и impersonation проходят. |
| A10 | **P2, исправлено локально** | Logout из impersonation отзывает impersonation JTI и связанный backup admin JTI того же субъекта. | Тест повторного использования обоих токенов проходит. |
| A11 | **P2, исправлено локально** | Runner записывает checksum миграции при первом применении даже если SQL сам создал version row с NULL; последующее изменение SQL ловится. | PostgreSQL integration на точном CI SHA. Применённые SQL не редактировать. |
| A12 | **P2, исправлено локально; старые частичные proxy backfill требуют проверки** | SQLite group destination/proxy columns и backfill обёрнуты savepoint; повторный старт восстанавливает legacy `destination_verified=0` при непустом `max_chat_id`. Состояние пустого `groups.proxy` нельзя автоматически отличить от намеренной настройки. | Linux CI и rehearsal на копии старой базы; перечислить пустые proxy rows с активным profile proxy, проверить вручную до production migration. |
| A13 | **P2, image CVE и secrets** | Последний записанный Docker Scout scan в `docs/audit/release-gate.md` относится к старому image digest и сообщает 29 находок (0 critical, 2 high, 2 medium, 25 low); owner review истории секретов открыт. Это не scan текущего кандидата. | Scan точного production digest, исправление или письменный risk disposition для оставшихся находок; секреты в истории проверены владельцем, при необходимости ротированы. |

## Статус исправлений — 2026-09-24

После исходного аудита изменения сделаны в локальном незакоммиченном дереве.
Они не привязаны к release SHA и не развёрнуты. A02–A07 и A09–A12 исправлены
в коде/configuration и покрыты новыми или обновлёнными regression tests. A08
и A13 остаются открытыми release gates; VPS staging, полное Linux backup/restore,
PostgreSQL CI и точный image scan не проводились. A01 разрешение подтверждено
пользователем как имеющееся вне репозитория; технический record/scope на VPS
этим локально не проверен.

Свежая локальная проверка `.venv` Python 3.12.14 с CI env vars и без
`DATABASE_URL` прошла: **716 passed, 20 skipped** за 32.51 с. Шесть SQLite
fixture handles теперь явно закрываются; WSL-only shell integration test
пропускается на Windows и остаётся Linux CI проверкой. Непосредственно
затронутый Windows набор прошёл **30 passed, 1 skipped**. Новый локальный
recovery hold deploy guard покрыт тремя regression tests. PostgreSQL
integration, browser CI и DR smoke не запускались на точной release-ревизии.

Реальный MAX login/send/join, production data, deploy и restore не запускались.
Deploy entrypoints теперь атомарно включают persistent recovery hold до
backup; GitHub deploy exact-SHA workflow остаётся следующим обязательным
проверочным шагом.

## Что уже есть в проекте

- Единственное приложение FastAPI с tenant isolation, PG для SaaS-учётных
  данных, SQLite для tenant-операций и одним владельцем кампаний; второй
  `app` с тем же data volume останавливает instance lock.
- Gateway проверяет authorization record и recovery hold перед каждым
  обращением к MAX; `send_message` требует provider message ID. Кампания
  сохраняет unknown-send outcome и не повторяет его автоматически.
- Backup останавливает writers, делает WAL checkpoint, проверяет архивы и
  ограничивает права на каталог; restore создаёт recovery hold до подмены
  данных. Эти свойства проверены чтением кода, не заменяют DR rehearsal.
- CI разделяет SQLite suite и PostgreSQL suite, проверяет Compose,
  зависимости, браузерный fixture и DR smoke. Fixture работает с fake MAX;
  это корректная граница безопасности, но не live-доказательство.

## Проверки этой ревизии и пределы

| Проверка | Результат |
| --- | --- |
| Windows Python 3.12, `MAX_TEST=1`, `MAX_SERVER_MODE=1`, тестовый `JWT_SECRET`, без `DATABASE_URL`: `.venv\Scripts\python.exe -m pytest tests/ -q --tb=line` | **685 passed, 20 skipped, 7 failed** за 27.57 s. Шесть отказов `WinError 32` в profile-login fixture: SQLite connection остаётся открытым перед `session.db` unlink. Один shell test не вызвал mock `bash` из-за отказа WSL `E_ACCESSDENIED`. Это портируемость тестов/окружения; успешный Linux exact-SHA прогон ещё нужен. |
| `.venv\Scripts\python.exe -m pip check` | PASS, нарушенных зависимостей нет. |
| `.venv\Scripts\python.exe -m compileall -q main.py antiban_core.py celery_worker.py app tests static` | PASS. |
| `node --check` для `static/js/index.js`, `admin.js`, `auth.js` | PASS. |
| `docker compose --env-file .env.example config -q` | PASS, но runtime не стартовал. |

Docker daemon недоступен из обычного sandbox через npipe (`permission denied`);
отдельный read-only запрос `docker info` подтвердил Engine `29.8.0`, но
изолированный runtime не запускался. Поэтому не выполнены сборка/запуск
точного образа, PostgreSQL E2E, браузерный Playwright и DR smoke.
`node_modules` отсутствует. Ни одна из перечисленных
исторических проверок `docs/audit/` не считается повторным PASS для этого HEAD.

## Решение для запуска

До закрытия A01–A08 и получения exact-SHA доказательств решение — **NO-GO**.
После исправлений требуется отдельный письменный release record с матрицей
PASS/FAIL/NOT RUN, digest образа, временем, владельцами и результатом
ограниченного live-canary. Отсутствие ошибок в `/api/health` или зелёный
локальный pytest отдельно не дают GO.
