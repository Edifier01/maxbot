# Документация MAXBOT

## Действующие инструкции

| Задача | Документ |
| --- | --- |
| Запуск и проверка | [`../README.md`](../README.md), [CI](../.github/workflows/ci.yml) |
| Правила работы с кодом | [`../agent.md`](../agent.md) |
| Архитектура и пользовательские потоки | [`HOW-IT-WORKS.md`](HOW-IT-WORKS.md) |
| Развёртывание, backup/restore, recovery hold | [`PRODUCTION-OPS.md`](PRODUCTION-OPS.md) |
| PostgreSQL-миграции | [`../migrations/README.md`](../migrations/README.md) |
| Безопасные ошибки UI | [`ui-ux-contract.md`](ui-ux-contract.md) |
| Последний датированный журнал ворот выпуска | [`audit/release-gate.md`](audit/release-gate.md) |
| Аудит production VPS и текущие блокеры | [`audit/PROJECT-AUDIT-2026-09-24.md`](audit/PROJECT-AUDIT-2026-09-24.md) |
| Порядок полного запуска с реальными MAX-действиями | [`PRODUCTION-LAUNCH-PLAN-2026-09-24.md`](PRODUCTION-LAUNCH-PLAN-2026-09-24.md) |

`docs/adr/` хранит архитектурные решения. Дата и статус ADR описывают момент
принятия решения; для исполнения всегда сверяйте его с текущим кодом и более
новыми ADR. В ADR 007 и 008 есть примечания о поздних изменениях.

## Исторические материалы

`CODEBASE-AUDIT.md`, `FINAL-PRODUCTION-AUDIT-2026-08-21.md`,
`PROJECT_PLAN.md`, `CORE-SYNC.md`, `superpowers/` и большинство файлов
`audit/` фиксируют состояние, план или доказательства на конкретную дату
и ревизию. Команды, пути, результаты тестов и выводы о готовности из них не
переносятся автоматически на текущий HEAD. В частности, `CORE-SYNC.md`
описывает упразднённую структуру двух деревьев.

Аудит документации от 2026-09-24: [`DOCUMENTATION-AUDIT-2026-09-24.md`](DOCUMENTATION-AUDIT-2026-09-24.md).
