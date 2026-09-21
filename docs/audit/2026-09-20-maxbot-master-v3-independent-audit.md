# Независимый аудит MAXBOT и сверка с MAXBOT MASTER V3

**Дата:** 2026-09-20

**Проверенный commit:** `0154884cf94d6aeccf65f5390a0f845d783c3c0e`

**Итог по коду:** `FIX`

**Итог для любых реальных MAX-вызовов:** `BLOCKED / NO-GO` до подтверждения разрешения платформы и закрытия обязательных технических ворот

## 1. Что проверено

Основной документ:

- Windows: `C:\Users\Edifi\Documents\MAXBOT_MASTER_V3_EN_2026-09-20.md`;
- WSL: `/mnt/c/Users/Edifi/Documents/MAXBOT_MASTER_V3_EN_2026-09-20.md`;
- SHA-256: `8c7a57092be519ea5df0379abc6030124d1e099867adbc72a06174027c90392d`;
- размер: 8 022 строки, 63 489 слов, 528 118 байт;
- заявленный inherited snapshot: `0154884cf94d6aeccf65f5390a0f845d783c3c0e`.

Текущий `HEAD` репозитория равен этому snapshot. Поэтому ссылки Master V3 на исходники относятся к фактически проверенному коду, а не к другой ревизии.

Аудит выполнен чтением текущего source code, схем, тестов, lock-файлов, CI/deploy/backup-скриптов и исходников реально установленного `maxapi-python==2.4.0`. Реальные SMS, login, send, join, probe, history, read и reaction не выполнялись. Production/VPS, реальные аккаунты, прокси и сессии не изменялись.

Это техническая оценка эксплуатационного риска, а не юридическое заключение.

## 2. Краткий вывод

Master V3 следует оставить нормативной основой. Документ корректно:

- отделяет документацию от реализованного и проверенного состояния;
- сохраняет основную модель продукта: `active / quiet / skip`, существующие диапазоны, одно рабочее направление и постоянный маршрут на аккаунт, персональные дневные планы и переиспользуемую библиотеку сообщений;
- запрещает подмену аккаунта, автоматический join, слепой повтор неизвестного результата, искусственную активность и маскировку;
- связывает 46 замечаний `AUD20-A01..A46`, 12 дополнений `COMP-R01..R12`, задачи `T00..T33` и 365 acceptance cases;
- правильно требует порядок `T15 -> T33 -> T14` и запрещает считать зелёные документы доказательством готовности приложения.

Самостоятельная проверка подтверждает критические выводы Master V3. В текущем коде сохраняются дефекты подтверждения отправки, идемпотентности, crash recovery, тестовой отправки, Start/Stop, proxy/session lifecycle, удаления, restore hold и deploy verification.

Дополнительно обнаружены два release-блокера, которых в Master V3 нет как самостоятельных требований:

1. `SUP-01`: отсутствует доказанный platform-authorization gate для неофициального внутреннего API MAX.
2. `SUP-02`: при каждом создании клиента может генерироваться новый синтетический Android fingerprint, хотя `device_id` частично сохраняется.

Также уточнён `COMP-R05`: искусственная активность не только запрещена как будущая мера — она уже включена по умолчанию и выполняет дополнительные MAX-вызовы перед/вне отправки.

## 3. Сверка с Master V3

| Область | Результат независимой проверки | Статус Master V3 |
| --- | --- | --- |
| `AUD20-A01..A05`, `A07` — outcome, ack, retry, durable operation | Подтверждено source code и контрактом установленного SDK | Оставить P1, не смягчать |
| `AUD20-A08..A10` — test-send, Start/Stop, персональные планы | Подтверждено source code и схемой SQLite | Оставить P1 |
| `AUD20-A14..A15` — proxy/session lifecycle | Подтверждено source code | Оставить P1 |
| `AUD20-A18..A21`, `A23` — destination, deletion, vault, shutdown, data scope | Подтверждено; `A20/A23` остаются условными по фактическим данным/config | Оставить открытыми |
| `AUD20-A34..A36` — backup/restore/deploy | Подтверждено скриптами | Оставить открытыми |
| `COMP-R05` — auxiliary operations | Подтверждено и усилено фактическим поведением | Исправлять до любых live-вызовов |
| `COMP-R12` — consent/destination, no auto-join | Подтверждено: send path способен вызвать `join_group` | Оставить обязательным |
| Остальные `AUD20`/`COMP` | Не обнаружено противоречащего исходного кода; часть требует race/browser/VPS/live evidence | Не закрывать без acceptance evidence |
| 365 acceptance cases | В текущем аудите полностью не прогонялись | Оставить `NOT RUN` |

Ни одно замечание Master V3 не признано закрытым только на основании существующих unit-тестов или прежнего CI.

## 4. Подтверждённые критические дефекты

### 4.1. Успех отправки фиксируется без использования provider acknowledgement

`app/campaign_send.py:267-291`:

- callback вызывает `await c.send_message(...)`, но отбрасывает возвращённый объект `Message`;
- затем локально вызывает `mark_accepted()`;
- после возврата `_with_client` состояние, отличное от `accepted`, принудительно переводится в `accepted`;
- идентификатор внешнего сообщения не сохраняется.

Установленный `maxapi-python==2.4.0` имеет сигнатуру `Client.send_message(...) -> Message`. Реализация ждёт ответ `MSG_SEND`, валидирует payload как `Message` и возвращает его. Следовательно, проект располагает объектом подтверждения, но не связывает его с долговечной операцией.

**Сверка:** `AUD20-A01` подтверждён.

### 4.2. Acknowledgement, cleanup и локальная фиксация смешаны в одном exception boundary

`main.py:1223-1247` всегда шифрует session в `finally`; `main.py:1342-1355` останавливает client и отменяет task в общем lifecycle. В `app/campaign_send.py:259-347` сетевой вызов, cleanup, запись результата, pacing и метрики находятся в общем `try/except`.

Отдельная ошибка после принятого MAX сообщения способна:

- превратить известное внешнее принятие в `unknown`;
- оставить локальную запись без внешнего ID;
- при тексте ошибки с `wait N seconds` попасть в раннюю ветку `SAFE_TO_RETRY`, потому что `classify_send_exception()` проверяет строковый flood marker до состояния операции.

**Сверка:** `AUD20-A02`, `A03`, `A05` подтверждены.

### 4.3. Нет долговечного operation/attempt ledger

`app/sqlite_backend.py:157-172` хранит только курсоры `queue_state` и строки `send_log`. В схеме нет `operation_id`, `attempt_no`, provider message ID, уникального finalization key или долговечной reservation.

`app/campaign_send.py:167-208` отдельно увеличивает дневной счётчик, вставляет `send_log` и двигает queue cursor. Идемпотентного ограничения на повторную финализацию нет. `SendTracker` живёт только в памяти процесса.

`app/campaign_worker.py:400-479` использует in-memory claim/release path, а `app/campaign_worker.py:740-763` останавливает worker, но ни один из путей не обеспечивает crash-safe владение попыткой. После смерти процесса нельзя надёжно отличить `not_started`, `in_flight`, `accepted`, `unknown`.

**Сверка:** `AUD20-A03`, `A04`, `A07`, `A10`, `A33` подтверждены на уровне архитектурного разрыва.

### 4.4. Test-send и Start/Stop обходят требуемую координацию

`app/routes_campaign.py:111-151` выбирает первый подходящий профиль/группу и напрямую вызывает `_send_with_retry(..., advance_queue=False)`. Долговечный slot/reservation и единый command identity отсутствуют.

`app/routes_campaign.py:18-47` выполняет slow preflight до/вокруг старта worker, а Stop только меняет `auto_run` и вызывает stop. Persisted control generation, которая отсекает уже начатый Start или старый claim, отсутствует.

**Сверка:** `AUD20-A08`, `A09` подтверждены.

### 4.5. Proxy привязан вычислением, а не долговечным назначением

`main.py:2075-2087` выбирает URL из group pool вычислением по `profile_id`. Это не отдельная сохранённая связь `account -> connection`, не фиксированный route revision и не lease попытки. Login, probe и send не доказаны как пользователи одного общего resolver.

**Сверка:** `AUD20-A14` подтверждён.

### 4.6. Обычная ошибка login может удалить рабочую session

`app/routes_profiles.py:159-175` при любой ошибке обычного login повторяет `_login_max(..., fresh=True)`. `main.py:1376-1381` в fresh-ветке вызывает `_clear_session()` до доказанного успешного нового входа.

Сетевая/proxy/SDK ошибка поэтому способна необоснованно уничтожить сохранённую сессию и инициировать новый SMS flow.

**Сверка:** `AUD20-A15` подтверждён.

### 4.7. Изменение invite link не инвалидирует destination

`app/routes_groups.py:147-191` меняет `invite_link`, но не очищает `max_chat_id` и не увеличивает destination revision. `main.py:1397-1412` сначала доверяет сохранённому `max_chat_id`.

Старый chat ID может продолжить использоваться после смены ссылки.

**Сверка:** `AUD20-A18` подтверждён.

### 4.8. Send path способен автоматически присоединиться к группе

`main.py:1397-1412` после неуспешного `resolve_group_by_link` вызывает `client.join_group(link)`. Это внешнее мутирующее действие внутри resolution/send path, не отдельная разрешённая команда.

**Сверка:** `COMP-R12` подтверждён. Исправление — fail closed с явным membership/destination approval, а не более скрытый join.

### 4.9. Удаление session directory не ждёт завершения login task

`app/routes_groups.py:41-49` делает `task.cancel()`, но не `await task`, после чего сразу удаляет directory. Group/profile delete routes вызывают этот cleanup после DB commit (`app/routes_groups.py:325-368`).

Задача может продолжать использовать или заново создавать удаляемые файлы.

**Сверка:** `AUD20-A19` подтверждён.

### 4.10. Legacy vault metadata удаляется до доказанной миграции

`app/vault.py:62-87` при наличии `.app_salt` безусловно удаляет `.app_salt` и `.app_vault`, затем создаёт/читает `.app_key`. Проверки успешной расшифровки и lossless migration всех session-файлов до удаления старого material нет.

**Сверка:** `AUD20-A20` подтверждён как условный дефект для data roots, где legacy metadata ещё существует.

### 4.11. `MAX_DATA` обходит tenant scoping

`main.py:128-136` возвращает `Path(MAX_DATA)` раньше server-mode resolver. При одном общем override несколько tenant contexts способны получить один и тот же уже разрешённый каталог.

**Сверка:** `AUD20-A23` подтверждён как conditional configuration risk. Дефолтный Compose сам по себе не доказывает утечку.

### 4.12. Shutdown не имеет общего проверенного deadline

`app/shutdown.py:53-100` последовательно отменяет background tasks, останавливает все worker и шифрует sessions, но не задаёт общий timeout и не изолирует обязательные cleanup steps от сбоя предыдущего шага. `docker-compose.yml` не задаёт `stop_grace_period` для app/worker.

**Сверка:** `AUD20-A21` подтверждён.

### 4.13. Встроенный SQLite backup — checkpoint + copy

`main.py:2414-2433` выполняет `wal_checkpoint(TRUNCATE)` и `shutil.copy2()` live-файла. Это отличается от maintenance backup scripts, которые останавливают writers, но внутренний backup не использует SQLite Backup API и не проверяет integrity результата.

**Сверка:** `AUD20-A34` подтверждён.

### 4.14. Restore автоматически снимает операционную паузу

`scripts/restore-volumes.sh:93-95` после восстановления сразу выполняет `docker compose up -d`. `main.py:2842-2847` через две секунды запускает auto-resume. Restore возвращает и старое значение `auto_run`, а отдельного внешнего recovery hold нет.

**Сверка:** `AUD20-A35` подтверждён.

### 4.15. Deploy verification может принять неуспешний последний health response

`scripts/verify_deploy.sh:22-41` проверяет после цикла только непустоту `health_json`. Если последняя попытка напечатала валидный JSON с `db_ok=false`, Python завершится non-zero, но переменная останется непустой и скрипт пойдёт дальше.

**Сверка:** `AUD20-A36` подтверждён.

## 5. Уточнение риска искусственной активности

Master V3 запрещает добавлять camouflage, artificial engagement и restriction bypass. Текущий код уже содержит такие действия:

- `main.py:210-215`: `human_presence_enabled=1`, history 70%, read 40%, reaction 12%, idle 5%;
- `main.py:1975-2020`: чтение истории, случайное read и reaction перед send;
- `main.py:2022-2072`: случайное открытие чата/history без отправки;
- `app/campaign_worker.py:414-417`: idle presence запускается до claim.

Исключения этих действий в основном логируются и подавляются. Поэтому MAX restriction/flood, полученный на auxiliary call, может не остановить следующий send. Дополнительные вызовы также увеличивают поверхность подозрительной активности, не добавляя бизнес-ценности.

**Вывод:** `COMP-R05` должен отключить эти side effects, а не «улучшить реалистичность». Исторические settings следует сохранить в export/audit для обратимости, но они не должны продолжать инициировать artificial reactions/read/idle. Обычные локальные интервалы, реальные рабочие окна и ограничения остаются частью pacing; маскировка под ручного пользователя — нет.

## 6. Дополнительные находки

### SUP-01 · Release blocker · Нет platform-authorization gate

Проект фиксирует `maxapi-python==2.4.0` и использует `pymax.Client` с пользовательским телефоном/SMS/session. Сам PyMax предупреждает, что работает через неофициальный внутренний API MAX, может нарушать условия сервиса и привести к блокировкам аккаунтов: [PyMax README](https://github.com/MaxApiTeam/PyMax).

Действующее пользовательское соглашение MAX запрещает без специального разрешения Компании автоматизированные скрипты для взаимодействия с сервисом (п. 4.3.7), а также использование сервиса вне предоставленного Компанией интерфейса без отдельного соглашения (п. 4.3.10). Оно отдельно запрещает рассылки без предварительного согласия (п. 4.3.4): [пользовательское соглашение MAX](https://legal.max.ru/ps).

Согласие сотрудников и закрытая группа необходимы, но не заменяют разрешение самой платформы на автоматизированный user-session transport.

Официальный developer API документирован для чат-ботов/мини-приложений, использует bot access token и `platform-api2.max.ru`: [официальный метод отправки MAX](https://dev.max.ru/docs-api/methods/POST/messages). Размещение такого приложения требует действующего лицензионного договора: [правила платформы MAX](https://dev.max.ru/docs/legal/rules).

**Требование:** до любого реального MAX-вызова владелец должен предоставить проверяемую ссылку на специальное разрешение/отдельное соглашение, которое покрывает именно выбранный transport, аккаунты, действия и срок. В репозитории хранится только несекретный reference/scope/expiry, не текст договора и не credentials.

Если такого разрешения нет:

- user-session automation остаётся выключенной;
- локальные fake/fixture tests могут продолжаться;
- переход на официальный Bot API оформляется отдельным product decision, потому что он меняет sender identity и основную бизнес-семантику;
- лимит официального Bot API нельзя механически объявлять «безопасным лимитом» для неофициального userbot transport.

Master V3 требует отдельное разрешение пользователем на live-действия агента и упоминает `MAX authorization`, но не формулирует доказательство специального разрешения Компании как самостоятельный release gate. Поэтому это дополнение, а не опровержение Master.

### SUP-02 · P1 · Случайная смена client fingerprint

`main.py:1190-1212` вызывает `ExtraConfig.generate_user_agent()` и сохраняет только выбранные app version/build. В установленном PyMax 2.4.0 `generate_user_agent()` случайно выбирает Android device model, OS version, screen, architecture, locale и timezone. Проект сохраняет `device_id`/`mt_instance_id`, но не весь generated user-agent.

Повторные подключения одного аккаунта поэтому могут выглядеть как разные устройства. Это противоречит запрету Master V3 на identity rotation/camouflage и может повысить риск challenge/restriction.

**Требование:** не «подбирать более правдоподобный fingerprint». Production transport допускается только с официально поддерживаемой и стабильной client identity, прямо разрешённой договором/официальным API. До подтверждения такой модели capability gate должен блокировать live transport.

## 7. Что нельзя делать ради «антибана»

Не следует:

- добавлять случайные реакции, чтение, online/typing imitation или фоновую историю;
- вращать fingerprint, proxy или sender после ошибки;
- ускорять отправку на основании количества proxy/IP;
- вводить произвольные общие caps `3/3/10` или обязательную паузу 180 секунд вместо фактических настроек и подтверждённых service restrictions;
- повторять `unknown` или подменять аккаунт;
- auto-join группу из send/probe/preview;
- считать `2xx`, отсутствие exception или локальную запись доказательством доставки;
- переносить лимиты официального Bot API на другой transport без официального контракта.

Снижение риска достигается не маскировкой, а разрешённым интерфейсом, явным согласием и destination scope, малым числом внешних операций, стабильной route/session identity, единым sanction controller, точным provider acknowledgement и fail-closed восстановлением.

## 8. Инварианты основной логики, которые план обязан сохранить

1. Роли `active / quiet / skip`, текущая трёхдневная модель и фактические сохранённые policy values.
2. Один work group и один явный постоянный proxy/connection на аккаунт; legacy memberships сохраняются для истории/миграции.
3. Персональный один раз материализованный дневной план, а не общий расходуемый message bag.
4. Переиспользуемая immutable message library; исчерпание дневной выборки не удаляет исходные тексты.
5. Один campaign sender на tenant и честные паузы между всеми внешними операциями.
6. `unknown` занимает исходный slot и не создаёт замену.
7. `accepted` означает только подтверждённое принятие провайдером, не delivery/read.
8. Stop/revocation/restriction действуют до следующего внешнего вызова; увеличение target — только на следующей разрешённой границе.
9. Preview/GET/WS/readiness не создают планы, не расходуют квоту и не обращаются к MAX.
10. Исправления вводятся постепенно в модульном монолите; переписывание frontend/framework не требуется.

## 9. Приоритет исправлений

1. `SUP-01`: platform authorization/transport gate — до любых live-проверок.
2. `SUP-02` + `COMP-R05` + `COMP-R12`: запрет synthetic identity/artificial actions/auto-join.
3. `T00/T01`: воспроизводимый baseline и безопасные fake boundaries.
4. `T02/T03/T06/T12`: scope, typed errors, verified adapter acknowledgement, operation ledger и recovery.
5. `T04/T05/T07/T08/T09/T10/T11/T13`: route/session/vault/restore/destination/sanction lifecycle.
6. Строго `T15 -> T33 -> T14`: library, personal plans, commands.
7. `T16..T30`: UI, observability, security, performance, deploy и полные regressions.
8. `T31` остаётся optional/off; `T32` — независимый release verdict по точному candidate SHA.

Подробный addendum-план: [`docs/superpowers/plans/2026-09-20-maxbot-safe-remediation-addendum.md`](../superpowers/plans/2026-09-20-maxbot-safe-remediation-addendum.md).

## 10. Выполненные проверки и ограничения доказательств

| Проверка | Результат |
| --- | --- |
| `git rev-parse HEAD` | `0154884cf94d6aeccf65f5390a0f845d783c3c0e` |
| Чистота до добавления audit docs | clean, `main...origin/main` |
| `python3 -m compileall -q main.py antiban_core.py celery_worker.py app tests static` | PASS |
| `pytest --collect-only -q` в временном venv | 340 tests collected |
| Focused pytest без зависшего TestClient/thread lifecycle | 43 PASS: 14 + 9 + 20 |
| Полный локальный pytest | NOT COMPLETED: sandbox стабильно не завершает часть TestClient/`asyncio.to_thread` процессов; не трактуется как PASS или доказанный defect проекта |
| `pip-audit` по двум production lock-файлам | PASS на 2026-09-20 для зафиксированных записей (`--disable-pip --no-deps`): известных CVE не найдено; инструмент отдельно предупредил, что этот режим слабее полного hash-pinned resolution |
| Exact-SHA GitHub checks | Историческое evidence: пять jobs для этого SHA были success 2026-08-26; не заменяет текущие 365 cases |
| Реальные MAX/VPS/proxy/SMS/send/join | NOT RUN по границе разрешений |

Локальная среда не дала честно завершить весь pytest, поэтому утверждения «все тесты проходят» нет. Зелёный CI на том же SHA полезен как прежнее evidence инфраструктуры, но не закрывает новые требования и не доказывает production readiness.

## 11. Release gate

Вердикт может стать `GO` только если одновременно:

- platform authorization подтверждено независимым владельцем/reviewer и совпадает с transport/action scope;
- отсутствуют artificial presence, auto-join и rotating synthetic identity на live path;
- все P1 и применимые P2 Master V3 закрыты тестами на точном candidate SHA;
- operation/attempt/ack/recovery semantics выдерживают timeout, cancellation, process death, midnight, restore и concurrent Start/Stop;
- все внешние действия проходят через один authorization/route/quota/sanction controller;
- полный тестовый, browser, dependency, backup/restore, deploy и security gate завершён без `NOT RUN` для обязательных проверок;
- production verification выполняется отдельно и только после явного разрешения.

До этого состояние проекта — `FIX`, а реальная автоматизация MAX — `BLOCKED / NO-GO`.

## 12. Addendum execution snapshot — 2026-09-20

This section is append-only and does not rewrite the historical findings above.
The source audit was verified at SHA-256
`8c7a57092be519ea5df0379abc6030124d1e099867adbc72a06174027c90392d` against
the original `HEAD` `0154884cf94d6aeccf65f5390a0f845d783c3c0e`. The current
working tree is dirty and has no new commit, so the following is local
remediation evidence, not commit-bound or production evidence.

Completed supplemental tasks: `ENV-00` source gate, `S00`, `S01`, `S02`,
`S02A`, and `S03`. The implementation now has a fail-closed authorization
record, one guarded gateway, no artificial presence/auto-join path, and the
exact `maxapi-python==2.4.1` contract with offline session identity migration.
The verified PyMax wheel SHA-256 is
`49c996cebebdcd490b8fc1424c84faad3c33d0b75eff4bb86cf1de9d968d76ea`.

The S03 recovery hold lives outside restored `max_server_data`, fences
scheduler/manual/auxiliary MAX calls, and is released only by an explicit
revision/reference command. Fixture-only Compose validation and source gates
passed. Docker daemon access remains `BLOCKED`, the platform authorization
file is absent in this local run, the Master `T00..T33` waves and production
verification are not complete, and no real MAX action was performed. The
release status therefore remains `FIX/PARTIAL`, not `GO`.

The machine-readable acceptance and verification records are
`verification/supplemental-acceptance-cases.json` and
`docs/audit/verification.md`; the baseline and sandbox limitations are in
`docs/audit/baseline.md`.

## 13. Current Master-source availability correction — 2026-09-21

The canonical standalone Master source is now available locally at
`/mnt/c/Users/Edifi/Documents/MAXBOT_MASTER_V3_EN_2026-09-20.md`. A fresh
SHA-256 check returned
`8c7a57092be519ea5df0379abc6030124d1e099867adbc72a06174027c90392d`, matching
the plan and the audit reference; a parser counted all `365` case headings.
This supersedes only the earlier availability note. It does not execute or
close any case: the normative `T00..T33` waves and the remaining manual/live
evidence stay `NOT RUN` or `BLOCKED` as recorded in the release gate.
