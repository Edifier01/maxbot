"""Source-aware, non-secret error contracts for MAX/proxy boundaries.

Exception text is untrusted diagnostic input.  It is used only to choose a
conservative catalogue code inside the already trusted source boundary; it is
never copied into an ErrorInfo or returned to a caller.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    source: str
    stage: str
    safe_message: str
    retryable: bool
    retry_after_at: str | None
    session_preserved: bool
    request_id: str | None
    attempt_id: str | None
    operation_id: str | None
    recommended_action: str


@dataclass(frozen=True)
class _ErrorSpec:
    safe_message: str
    recommended_action: str
    retryable: bool = False


# Keep the catalogue finite and source-independent.  Consumer tasks can add
# UI-specific wording without ever exposing adapter exception strings.
_CATALOG: Final[dict[str, _ErrorSpec]] = {
    "AUTH_REQUIRED": _ErrorSpec("Требуется вход.", "AUTHENTICATE"),
    "AUTH_SESSION_EXPIRED": _ErrorSpec("Сессия истекла.", "REAUTHENTICATE"),
    "AUTH_SESSION_REVOKED": _ErrorSpec("Сессия отозвана.", "REAUTHENTICATE"),
    "LOGIN_INVALID": _ErrorSpec("Не удалось выполнить вход.", "REVIEW_INPUT"),
    "PERMISSION_DENIED": _ErrorSpec("Недостаточно прав для операции.", "REVIEW_ACCESS"),
    "SUBSCRIPTION_INACTIVE": _ErrorSpec("Подписка неактивна.", "REVIEW_SUBSCRIPTION"),
    "PROFILE_NOT_FOUND": _ErrorSpec("Профиль не найден.", "REVIEW_PROFILE"),
    "OBJECT_NOT_FOUND": _ErrorSpec("Объект не найден.", "REVIEW_OBJECT"),
    "WORK_GROUP_SELECTION_REQUIRED": _ErrorSpec("Выберите рабочую группу.", "SELECT_GROUP"),
    "DESTINATION_REVIEW_REQUIRED": _ErrorSpec("Требуется проверить назначение.", "REVIEW_DESTINATION"),
    "MEMBERSHIP_REVIEW_REQUIRED": _ErrorSpec("Требуется проверить членство.", "REVIEW_MEMBERSHIP"),
    "CONSENT_REVOKED": _ErrorSpec("Согласие отозвано.", "STOP_OPERATION"),
    "ACCOUNT_AUTOMATION_CONFLICT": _ErrorSpec("Для аккаунта уже выполняется другая операция.", "WAIT_OPERATION"),
    "ROUTE_MISSING": _ErrorSpec("Для аккаунта не задан маршрут.", "CONFIGURE_ROUTE"),
    "ROUTE_CONFLICT": _ErrorSpec("Маршрут аккаунта конфликтует с текущими данными.", "REVIEW_ROUTE"),
    "ROUTE_DISABLED": _ErrorSpec("Маршрут аккаунта отключён.", "ENABLE_ROUTE"),
    "ROUTE_REVISION_CONFLICT": _ErrorSpec("Маршрут изменился, обновите данные.", "RELOAD_ROUTE"),
    "PROXY_URL_INVALID": _ErrorSpec("Адрес прокси имеет неверный формат.", "REVIEW_PROXY"),
    "PROXY_UNSUPPORTED_SCHEME": _ErrorSpec("Схема прокси не поддерживается.", "REVIEW_PROXY"),
    "PROXY_AUTH_FAILED": _ErrorSpec("Прокси отклонил учётные данные.", "REVIEW_PROXY"),
    "PROXY_CONNECT_FAILED": _ErrorSpec("Не удалось подключиться через прокси.", "REVIEW_PROXY"),
    "PROXY_RESPONSE_INVALID": _ErrorSpec("Прокси вернул некорректный ответ.", "REVIEW_PROXY"),
    "TLS_ERROR": _ErrorSpec("Не удалось установить защищённое соединение.", "REVIEW_NETWORK"),
    "MAX_CONNECT_FAILED": _ErrorSpec("Не удалось подключиться к MAX.", "REVIEW_NETWORK"),
    "SDK_INCOMPATIBLE": _ErrorSpec("Интеграция MAX несовместима с установленным SDK.", "REVIEW_RUNTIME"),
    "MAX_SESSION_REVOKED": _ErrorSpec("Сессия MAX отозвана.", "REAUTHENTICATE"),
    "MAX_RATE_LIMIT": _ErrorSpec("MAX временно ограничил частоту действий.", "WAIT_RETRY"),
    "MAX_ACCOUNT_BANNED": _ErrorSpec("Аккаунт MAX заблокирован.", "STOP_TENANT"),
    "MAX_ACTION_FORBIDDEN": _ErrorSpec("MAX отклонил это действие.", "REVIEW_ACTION"),
    "CONNECTION_TIMEOUT": _ErrorSpec("Истекло время ожидания соединения.", "REVIEW_NETWORK"),
    "CODE_REQUEST_TIMEOUT": _ErrorSpec("Не удалось вовремя запросить код.", "RETRY_LOGIN"),
    "CODE_INPUT_TIMEOUT": _ErrorSpec("Время ввода кода истекло.", "RESTART_LOGIN"),
    "PASSWORD_INPUT_TIMEOUT": _ErrorSpec("Время ввода пароля истекло.", "RESTART_LOGIN"),
    "OTP_FORMAT_INVALID": _ErrorSpec("Код имеет неверный формат.", "REVIEW_INPUT"),
    "OTP_INVALID": _ErrorSpec("Код недействителен.", "REVIEW_INPUT"),
    "OTP_EXPIRED": _ErrorSpec("Код истёк.", "REQUEST_NEW_CODE"),
    "PASSWORD_INVALID": _ErrorSpec("Пароль недействителен.", "REVIEW_INPUT"),
    "ATTEMPT_STATE_CONFLICT": _ErrorSpec("Состояние попытки изменилось.", "RELOAD_OPERATION"),
    "ATTEMPT_EXPIRED": _ErrorSpec("Попытка истекла.", "RESTART_OPERATION"),
    "ATTEMPT_INTERRUPTED": _ErrorSpec("Попытка была прервана.", "REVIEW_OPERATION"),
    "REGISTRATION_REQUIRED": _ErrorSpec("Требуется завершить регистрацию.", "REVIEW_REGISTRATION"),
    "SEND_OUTCOME_UNKNOWN": _ErrorSpec("Результат действия неизвестен; сначала выполните сверку.", "RECONCILE_BEFORE_RETRY"),
    "ACK_PERSIST_PENDING": _ErrorSpec("Подтверждение получено, но ещё не сохранено.", "PERSIST_ACK"),
    "CLEANUP_FAILED": _ErrorSpec("Не удалось завершить очистку после действия.", "REVIEW_CLEANUP"),
    "DAILY_BUDGET_ALLOCATED": _ErrorSpec("Дневной лимит уже зарезервирован.", "REVIEW_BUDGET"),
    "CAMPAIGN_BUSY": _ErrorSpec("Кампания уже выполняется.", "WAIT_OPERATION"),
    "PREVIEW_STALE": _ErrorSpec("Предпросмотр устарел.", "RELOAD_PREVIEW"),
    "COMMAND_STATE_UNKNOWN": _ErrorSpec("Состояние команды неизвестно.", "RECONCILE_BEFORE_RETRY"),
    "STOP_PENDING": _ErrorSpec("Остановка сохранена и ожидает завершения.", "WAIT_OPERATION"),
    "RESTORE_HOLD": _ErrorSpec("Внешние действия остановлены до проверки восстановления.", "REVIEW_RESTORE"),
    "MIGRATION_REVIEW_REQUIRED": _ErrorSpec("Требуется проверить миграцию.", "REVIEW_MIGRATION"),
    "VAULT_KEY_REQUIRED": _ErrorSpec("Требуется ключ хранилища.", "UNLOCK_VAULT"),
    "VAULT_INTEGRITY_FAILED": _ErrorSpec("Проверка целостности хранилища не пройдена.", "REVIEW_VAULT"),
    "STORAGE_ERROR": _ErrorSpec("Не удалось сохранить данные.", "REVIEW_STORAGE"),
    "POLICY_APPLY_PARTIAL": _ErrorSpec("Политика применена не полностью.", "REVIEW_POLICY"),
    "VERSION_CONFLICT": _ErrorSpec("Версия данных изменилась.", "RELOAD_DATA"),
    "POOL_EMPTY": _ErrorSpec("Доступный пул сообщений пуст.", "REVIEW_LIBRARY"),
    "IMPORT_INVALID": _ErrorSpec("Импорт содержит некорректные данные.", "REVIEW_IMPORT"),
    "INPUT_TOO_LARGE": _ErrorSpec("Входные данные слишком велики.", "REVIEW_INPUT"),
    "SETTINGS_NOT_LOADED": _ErrorSpec("Настройки ещё не загружены.", "RELOAD_SETTINGS"),
    "API_RATE_LIMIT": _ErrorSpec("Слишком много запросов к приложению.", "WAIT_RETRY"),
    "NETWORK_UNAVAILABLE": _ErrorSpec("Сеть недоступна.", "REVIEW_NETWORK"),
    "SERVER_UNAVAILABLE": _ErrorSpec("Сервис временно недоступен.", "WAIT_RETRY"),
    "LOGOUT_NOT_CONFIRMED": _ErrorSpec("Выход не подтверждён.", "REVIEW_SESSION"),
    "IMPERSONATION_EXIT_FAILED": _ErrorSpec("Не удалось завершить режим impersonation.", "REVIEW_SESSION"),
    "UNCLASSIFIED": _ErrorSpec("Операция не выполнена; требуется проверка.", "REVIEW_OPERATION"),
}

_PROXY_AUTH_RE = re.compile(r"auth|credential|unauthori[sz]ed|407|login|password", re.I)
_PROXY_RESPONSE_RE = re.compile(r"response|status|protocol|http", re.I)
_MAX_BAN_RE = re.compile(r"account\s+(?:is\s+)?(?:ban|block)|banned|blocked|suspend|заблок|бан", re.I)
_MAX_REVOKED_RE = re.compile(r"revok|invalid\s+session|session\s+expired|отозван|ист[её]к", re.I)
_MAX_RATE_RE = re.compile(r"flood|rate|too\s+many|wait\s+\d+|лимит|частот", re.I)
_TIMEOUT_RE = re.compile(r"timeout|timed\s+out|истекло\s+время", re.I)
_SECRET_WORD_RE = re.compile(r"password|passwd|otp|token|secret|cookie", re.I)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _text(exc: BaseException) -> str:
    # This local string is classification input only; it never enters output.
    return f"{type(exc).__name__} {exc}"[:1000]


def _safe_identifier(value: str | None) -> str | None:
    if not value:
        return None
    candidate = str(value).strip()
    if not _IDENTIFIER_RE.fullmatch(candidate) or _SECRET_WORD_RE.search(candidate):
        return None
    return candidate


def _spec(code: str) -> _ErrorSpec:
    return _CATALOG.get(code, _CATALOG["UNCLASSIFIED"])


def _classify_code(source: str, stage: str, text: str, outcome: str) -> str:
    if source == "proxy":
        if _PROXY_AUTH_RE.search(text):
            return "PROXY_AUTH_FAILED"
        if _PROXY_RESPONSE_RE.search(text):
            return "PROXY_RESPONSE_INVALID"
        if _TIMEOUT_RE.search(text):
            return "CONNECTION_TIMEOUT"
        return "PROXY_CONNECT_FAILED"

    if source == "max":
        if _MAX_BAN_RE.search(text):
            return "MAX_ACCOUNT_BANNED"
        if _MAX_REVOKED_RE.search(text):
            return "MAX_SESSION_REVOKED"
        if _MAX_RATE_RE.search(text):
            return "MAX_RATE_LIMIT"
        if outcome in {"unknown", "in_flight", "accepted"} and stage in {"send", "mutation", "action"}:
            return "SEND_OUTCOME_UNKNOWN"
        if _TIMEOUT_RE.search(text):
            return "MAX_CONNECT_FAILED"
        return "MAX_ACTION_FORBIDDEN"

    if source == "storage":
        return "STORAGE_ERROR"
    if source == "auth":
        return "AUTH_SESSION_EXPIRED" if _MAX_REVOKED_RE.search(text) else "LOGIN_INVALID"
    if outcome in {"unknown", "in_flight", "accepted"} and stage in {"send", "mutation", "action"}:
        return "SEND_OUTCOME_UNKNOWN"
    return "UNCLASSIFIED"


def classify_exception(
    exc: BaseException,
    *,
    source: str,
    stage: str,
    outcome: str = "rejected",
    retry_after_at: str | None = None,
    request_id: str | None = None,
    attempt_id: str | None = None,
    operation_id: str | None = None,
) -> ErrorInfo:
    """Return a safe, conservative error envelope for one trusted boundary."""
    normalized_source = source.strip().lower() if source else "unknown"
    if normalized_source not in {"proxy", "max", "storage", "auth", "http", "unknown"}:
        normalized_source = "unknown"
    normalized_stage = stage.strip().lower()[:64] if stage else "unknown"
    normalized_outcome = outcome.strip().lower() if outcome else "rejected"
    code = _classify_code(normalized_source, normalized_stage, _text(exc), normalized_outcome)
    spec = _spec(code)
    # A mutating response that was lost is never an automatic replay signal.
    retryable = spec.retryable and not (
        normalized_outcome in {"unknown", "in_flight", "accepted"}
        and normalized_stage in {"send", "mutation", "action"}
    )
    return ErrorInfo(
        code=code,
        source=normalized_source,
        stage=normalized_stage,
        safe_message=spec.safe_message,
        retryable=retryable,
        retry_after_at=retry_after_at if code == "MAX_RATE_LIMIT" else None,
        session_preserved=code not in {"MAX_SESSION_REVOKED"},
        request_id=_safe_identifier(request_id),
        attempt_id=_safe_identifier(attempt_id),
        operation_id=_safe_identifier(operation_id),
        recommended_action=spec.recommended_action,
    )


def redact_error(info: ErrorInfo) -> ErrorInfo:
    """Rebuild an envelope from the fixed catalogue, dropping unsafe values."""
    spec = _spec(info.code)
    return ErrorInfo(
        code=info.code if info.code in _CATALOG else "UNCLASSIFIED",
        source=info.source if info.source in {"proxy", "max", "storage", "auth", "http", "unknown"} else "unknown",
        stage=info.stage[:64] if info.stage else "unknown",
        safe_message=spec.safe_message,
        retryable=bool(info.retryable) and info.code != "SEND_OUTCOME_UNKNOWN",
        retry_after_at=info.retry_after_at if info.code == "MAX_RATE_LIMIT" else None,
        session_preserved=bool(info.session_preserved),
        request_id=_safe_identifier(info.request_id),
        attempt_id=_safe_identifier(info.attempt_id),
        operation_id=_safe_identifier(info.operation_id),
        recommended_action=spec.recommended_action,
    )


ERROR_CODES: Final[frozenset[str]] = frozenset(_CATALOG)
