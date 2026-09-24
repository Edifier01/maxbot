# Core sync — архивная инструкция

Эта процедура больше не применяется. В текущем репозитории одно приложение:
`main.py`, `antiban_core.py`, `app/` и `tests/`. Каталогов `desktop/`, `server/`
и скрипта `scripts/check_core_sync.py` нет. Сверять или копировать код между
двумя деревьями не требуется.

Для изменения общего поведения используйте карту модулей в `agent.md`,
архитектурное описание в `docs/HOW-IT-WORKS.md` и актуальные команды проверок
в `README.md` и `.github/workflows/ci.yml`. Историю решения о разделении
воркера см. в `docs/adr/003-worker-module-extraction-deferred.md`.
