---
name: ponytail-review
description: Review the current diff for overengineering only — unused abstractions, extra deps, code that already exists in-repo.
---

# Ponytail Review

Пользователь вызвал `/ponytail-review`. Это **не** bug review и **не** security review.

## Шаги

1. Сними diff: `git diff` и `git diff --stat` (unstaged + staged). Если чисто — скажи, что смотреть нечего.
2. Прочитай `.cursor/rules/ponytail.mdc` (лестница из 7 ступеней).
3. Для каждого лишнего куска: что удалить/заменить и **чем уже в репо / stdlib / браузере**.
4. Не предлагай рефакторинг «на всякий случай». Не трогай pacing, tenant isolation, vault, validation на trust boundary — это не оверинжиниринг.

## Вывод

- **Must delete/simplify** — конкретные файлы/символы
- **Keep** — намеренный угол с `ponytail:` или явная просьба пользователя
- Без патча, пока пользователь не сказал «правь»
