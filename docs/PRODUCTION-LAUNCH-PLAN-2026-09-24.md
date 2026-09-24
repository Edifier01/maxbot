# План полного запуска MAXBOT на production VPS

Дата плана: 2026-09-24. Цель: веб-панель и кампании с реальными действиями в
MAX на одном VPS. Основа — [аудит текущей ревизии](audit/PROJECT-AUDIT-2026-09-24.md).
Текущий статус **NO-GO для production release**: локальные исправления пока
не имеют точного release SHA, независимого CI/review и staging evidence.
Пользователь 2026-09-24 сообщил, что необходимые MAX-разрешения уже имеются;
их договорный scope и установленный на VPS authorization record локально не
проверялись. Каждая фаза завершается артефактом, проверяемым на
фиксированном commit SHA и image digest; для работ с данными и MAX используется
отдельное операционное задание в соответствии с `agent.md`.

## 0. Зафиксировать разрешённый продукт и владельцев

1. **Статус от владельца:** пользователь подтвердил, что необходимые
   разрешения уже есть. Для release record сохранить у владельца ссылку/номер
   и scope для текущего `authorized_user_session` транспорта и нужных действий: login,
   resolve/check/join, send, history/read/reaction/probe. Для массовых и
   рекламных/маркетинговых сообщений требуется прямой договорный охват по
   [п. 1.5 требований MAX](https://dev.max.ru/docs/legal/requirements).
   Зафиксировать разрешённые аккаунты, получателей/группы, типы сообщений,
   ограничения и срок. Сам JSON authorization record не является доказательством.
2. **Владелец продукта/юрист:** применить имеющееся разрешение к правилам
   получения согласий,
   основания обработки и удаления данных, пользовательские условия, контакты
   поддержки и политику хранения по
   [правилам MAX](https://dev.max.ru/docs/legal/rules).
3. **Технический владелец:** перед staging/live сверить record и разрешённый
   scope; если они не совпадают, остановить ветку user-session. Сделать gap analysis для
   [официального bot API](https://dev.max.ru/docs-api): identity, членство в
   чатах, права бота, список адресатов, отправка, ACK, ограничения скорости,
   UI и миграция данных. Только после него перепланировать реализацию.

**Выход фазы:** owner reference/scope для уже имеющегося разрешения и
спецификация live-canary. В репозитории остаются только reference и проверенный
технический record, без договора и персональных данных.

## 1. Исправить блокеры исходного кода и runbook

| Порядок | Работа | Проверяемый результат |
| --- | --- | --- |
| 1.1–1.8 | **Исправлено локально:** workflow SHA transfer; readonly authorization mount и fail-closed readiness; recovery hold create/release and image/permissions; backup JWT epoch/plaintext guard; JWT claim checks and impersonation revoke; transactional migration checksum and SQLite backfill. Повторный старт чинит старые неполные destination markers; пустой legacy group proxy надо проверить вручную. | Regression tests проходят локально. Нужны exact-SHA CI, staging workflow/release-hold test, PostgreSQL integration, isolated Linux DR rehearsal и просмотр legacy SQLite proxy candidates. |
| 1.9 | Windows fixtures явно закрывают SQLite handles; WSL launcher shell integration test пропускается на Windows. Recovery hold создаётся атомарно обеими deploy entrypoints до backup и остаётся активным. | Полный CI-env Python suite локально: 716 passed, 20 skipped; exact-SHA GitHub workflow ещё требуется. |

**Выход фазы:** отдельные коммиты/PR с regression tests и независимым review
для auth, миграций и операций. Документы и `.env.example` обновлены; новые
миграции — только добавочные.

## 2. Закрыть точные release-ворота

1. Выбрать immutable release SHA и собрать образ из него. Записать SHA,
   image digest, hashes lock-файлов и версию Compose в release record.
2. На этом SHA получить успешные CI jobs: Linux Python suite без
   `DATABASE_URL`, отдельные PostgreSQL skipif/E2E, browser-e2e,
   compose-config, dependency-audit и backup-restore-smoke. Повторить
   Windows suite после 1.9. Выполнить `pip check`, compileall, shell/JS
   syntax и миграции на копиях реальных схем.
3. Закрыть [Master T00–T33](audit/release-gate.md): каждому из 365 нормативных
   случаев дать evidence/результат; нельзя переносить PASS с другого SHA.
   Приоритет — auth/tenant, кампания и dedupe/unknown-send, stop/restart,
   ограничения темпа и отказ MAX, подписка, backup/restore.
4. Выполнить T30-C02 на согласованном dataset (10 tenant, 100 синтетических
   аккаунтов на tenant, 10 подписчиков, две вкладки, WebSocket outage/hidden
   tab), пять повторов baseline и candidate. Записать p50/p95, SQL counts,
   CPU/RSS, event-loop lag и критерии регрессии в
   [performance evidence](audit/performance.md).
5. Провести полный ручной UI/a11y review в реальном браузере: 200% zoom,
   keyboard/focus, контраст, loading/stale/permission/stop-pending, мобильная
   клавиатура и admin dialogs. Внести screenshot/evidence matrix по
   [UI review](audit/ui-review.md).
6. Просканировать **точный** image digest на CVE, определить судьбу 2 high из
   исторического scan, провести owner review истории секретов и ротацию при
   обнаружении. Ограничить передачу артефактов scanner согласно политике
   владельца. Закрыть замечания или явно оформить risk acceptance.

**Выход фазы:** новый release-gate документ для точного SHA с `PASS` по
обязательным воротам и review; непроведённые проверки помечены `NOT RUN` и
сохраняют `NO-GO`.

## 3. Подготовить VPS и изолированный staging

1. Выбрать VPS/домен с запасом CPU/RAM/диска по T30-C02, настроить доступ по
   SSH key, обновления ОС, firewall (публично только 80/443 и ограниченный
   SSH), Docker/Compose, DNS A/AAAA и TLS через Caddy. Один `app` владеет
   кампаниями; Celery остаётся trigger-only.
2. Создать секреты вне Git: `JWT_SECRET`, пароли PostgreSQL/Redis/admin,
   `INTERNAL_SERVICE_TOKEN`, ключи backup, опциональные alert credentials.
   Права `.env` 0600, доступ только операторам. Проверить TRUSTED_PROXY_CIDRS,
   WEBHOOK_ALLOWED_HOSTS, регистрацию и реальный `DOMAIN`.
3. Разместить подтверждённый authorization record в отдельном каталоге VPS,
   указанном через `MAX_PLATFORM_AUTHORIZATION_DIR`; Compose монтирует его
   read-only по `/app/authorization`. Scope и срок должны совпадать с
   разрешением. До live-canary держать recovery hold активным. Наличие record
   не выпускает hold автоматически.
4. Настроить ежедневный согласованный backup PG/SQLite/control, off-site
   копию, срок хранения, шифрование/контроль доступа, alert при отказе и
   проверку восстановления. Зафиксировать RPO/RTO и ответственного.
5. На staging без реальных MAX-действий пройти первый deploy, HTTPS/login,
   tenant isolation, rate limits, subscription, health/metrics/alerts,
   миграции, restart, downgrade/rollback и cross-host DR. Проверять не только
   HTTP 200, но содержимое readiness и отсутствие auto-resume при hold.

**Выход фазы:** staging report с точным SHA/digest, измеренными RPO/RTO и
работающими runbook, monitoring и restore; fixture secrets не переходят в
production.

## 4. Ограниченный production запуск

1. Открыть change window. Зафиксировать release SHA/digest, ответственных,
   свежий off-site backup и путь rollback. Развернуть VPS с закрытыми
   регистрацией/доступом для широких пользователей и активным recovery hold.
2. Выполнить `deploy.sh` и `verify_deploy.sh`; вручную сверить digest, PG/SQLite
   состояние, HTTPS, readiness, метрики, alarms, доступ администратора и
   tenant isolation. Ошибка любого обязательного пункта означает stop.
3. В отдельном разрешённом операционном задании проверить дату/область договора
   и record, затем выпустить hold проверенной командой. Сохранить evidence.
4. Провести live-canary только на явно разрешённых аккаунте, группе и
   получателях: минимальные login/check/send действия, одна кампания с
   минимальной скоростью и объёмом. Наблюдать provider ACK, send_log,
   отсутствие дублей/unknown replay, блокировки/429, stop/pause и alerts.
   Условия остановки заранее численно зафиксировать в canary runbook.
5. Если canary и 15–60 минут наблюдения успешны, расширять доступ партиями
   с журналом объёма, ошибок и решений; до этого общий запуск закрыт.

**GO подписывают** владелец продукта/договора, security/данные и технический
владелец по одному release record. Ошибка разрешения MAX, миграции, данных,
дубликатов, delivery ACK, backup или мониторинга даёт **NO-GO/STOP**.

## Rollback и после запуска

- При угрозе MAX или неверной доставке: остановить кампании и вернуть recovery
  hold до любых повторных send. Unknown outcomes вручную сверять с provider;
  автоматически не переотправлять.
- При дефекте релиза: остановить writers, сохранить диагностические данные,
  восстановить предыдущий **совместимый** image/commit. Data restore выполнять
  только согласованной процедурой PG + SQLite + control с новым hold; проверить
  JWT invalidation и владельца данных до release hold.
- В первые сутки дежурный наблюдает health, queue depth, ошибки MAX, dedupe,
  tenant boundaries, backup result, свободное место и сроки record/договора.
  Затем проводит ежедневный просмотр и плановую DR rehearsal.

## Текущее ближайшее действие

Локальные пункты 1.1–1.9 исправлены и тесты пройдены; далее опубликовать
candidate SHA, получить exact-SHA GitHub workflow evidence и пройти deploy
workflow с активным recovery hold. С staging evidence и остальными release
gates фазы 2 по-прежнему работать до снятия hold. Пользователь подтвердил
наличие разрешения MAX; его scope и установленный VPS authorization record
нужно сверить до live-canary.
