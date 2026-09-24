"""Pydantic models for panel API routes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

import antiban_core
from app.config import webhook_url_allowed


class ProfileIn(BaseModel):
    phone: str
    label: str = ""
    proxy: str = ""

    @field_validator("proxy")
    @classmethod
    def validate_proxy(cls, v: str) -> str:
        return antiban_core.normalize_proxy_field(v)


class ProfilePatchIn(BaseModel):
    label: str | None = None
    proxy: str | None = None

    @field_validator("proxy")
    @classmethod
    def validate_proxy(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return antiban_core.normalize_proxy_field(v)


class CodeIn(BaseModel):
    code: str = Field(max_length=1024)
    attempt_id: str | None = Field(default=None, max_length=128)
    revision: int | None = Field(default=None, ge=0)
    request_id: str | None = Field(default=None, max_length=128)


class AuthAttemptStartIn(BaseModel):
    group_id: int | None = Field(default=None, ge=1)
    mode: Literal["session_or_login", "login", "session"] = "session_or_login"
    request_id: str | None = Field(default=None, max_length=128)


class AutomationScopeIn(BaseModel):
    group_id: int = Field(ge=1)


class AuthCodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    revision: int = Field(ge=0)
    request_id: str | None = Field(default=None, max_length=128)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        if not value.isascii() or not value.isdigit():
            raise ValueError("OTP_FORMAT_INVALID")
        return value


class AuthPasswordIn(BaseModel):
    password: str = Field(max_length=1024)
    revision: int = Field(ge=0)
    request_id: str | None = Field(default=None, max_length=128)


class SessionDeleteIn(BaseModel):
    confirm: Literal["DELETE_SESSION"]


class GroupIn(BaseModel):
    name: str
    max_chat_id: str = ""
    invite_link: str = ""
    proxy: str = ""

    @field_validator("proxy")
    @classmethod
    def validate_proxy(cls, v: str) -> str:
        return antiban_core.normalize_proxy_field(v)


class GroupPatchIn(BaseModel):
    name: str | None = None
    max_chat_id: str | None = None
    invite_link: str | None = None
    proxy: str | None = None
    is_active: int | None = None

    @field_validator("proxy")
    @classmethod
    def validate_proxy(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return antiban_core.normalize_proxy_field(v)

    @field_validator("is_active")
    @classmethod
    def validate_is_active(cls, v: int | None) -> int | None:
        if v is None:
            return None
        iv = int(v)
        if iv not in (0, 1):
            raise ValueError("is_active должен быть 0 или 1")
        return iv


class DestinationVerifyIn(BaseModel):
    chat_id: str = Field(min_length=1, max_length=200)
    revision: int = Field(ge=0)

    @field_validator("chat_id")
    @classmethod
    def validate_chat_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or not normalized.isprintable():
            raise ValueError("Укажите корректный ID назначения")
        return normalized


class SettingsIn(BaseModel):
    delay_min_sec: int | None = Field(default=None, ge=5)
    delay_max_sec: int | None = Field(default=None, ge=5)
    max_msgs_per_profile_day: int | None = None
    daily_limit_min: int | None = None
    daily_limit_max: int | None = None
    jitter_percent: int | None = None
    message_pick_mode: str | None = None
    campaign_goal: str | None = None
    warmup_enabled: int | None = None
    warmup_days: int | None = None
    cooldown_reauth_hours: float | None = None
    cooldown_fail_hours: float | None = None
    password_max_attempts: int | None = None
    api_pin: str | None = None
    webhook_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    backup_interval_hours: float | None = None
    worker_pool_size: Literal[1] | None = None
    human_rhythm_enabled: int | None = None
    send_windows_weekday: str | None = None
    send_windows_weekend: str | None = None
    day_skip_percent: float | None = None
    role_plan_enabled: int | None = None
    role_active_percent: float | None = None
    role_quiet_percent: float | None = None
    role_active_min: int | None = None
    role_active_max: int | None = None
    role_quiet_limit: int | None = None
    human_pauses_enabled: int | None = None
    short_pause_chance: float | None = None
    short_pause_min_sec: int | None = None
    short_pause_max_sec: int | None = None
    long_pause_chance: float | None = None
    long_pause_min_sec: int | None = None
    long_pause_max_sec: int | None = None
    break_after_n: int | None = None
    break_min_sec: int | None = None
    break_max_sec: int | None = None
    jitter_morning_percent: int | None = None
    jitter_evening_percent: int | None = None
    warmup_start_min: int | None = None
    warmup_start_max: int | None = None
    lazy_day_percent: float | None = None
    lazy_day_factor: float | None = None
    human_presence_enabled: int | None = None
    presence_history_chance: float | None = None
    presence_read_chance: float | None = None
    presence_react_chance: float | None = None
    presence_reactions: str | None = None
    presence_idle_chance: float | None = None
    human_texts_enabled: int | None = None
    text_dedupe_enabled: int | None = None
    text_similarity_max: float | None = None
    text_dedupe_window: int | None = None
    text_length_variety: int | None = None
    timezone_offset_hours: float | None = None
    circuit_break_minutes: float | None = None
    cooldown_fail_max_hours: float | None = None
    cooldown_disable_after_fails: int | None = None

    @model_validator(mode="after")
    def check_delays(self) -> SettingsIn:
        if self.webhook_url is not None:
            webhook = self.webhook_url.strip()
            if webhook and not webhook_url_allowed(webhook):
                raise ValueError(
                    "Webhook разрешён только для HTTPS-хостов из WEBHOOK_ALLOWED_HOSTS"
                )
        lo = self.delay_min_sec
        hi = self.delay_max_sec
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("Мин. пауза не может быть больше макс. паузы")
        if self.jitter_percent is not None and not (0 <= self.jitter_percent <= 100):
            raise ValueError("Разброс (%) должен быть от 0 до 100")
        if self.message_pick_mode is not None and self.message_pick_mode not in (
            "random_norepeat",
            "round_robin",
        ):
            raise ValueError("Режим сообщений: случайно без повтора или по кругу")
        if self.cooldown_reauth_hours is not None and self.cooldown_reauth_hours < 0:
            raise ValueError("Пауза после повторного входа (ч) должна быть ≥ 0")
        if self.cooldown_fail_hours is not None and self.cooldown_fail_hours < 0:
            raise ValueError("Пауза после ошибки (ч) должна быть ≥ 0")
        if self.password_max_attempts is not None and self.password_max_attempts < 1:
            raise ValueError("Макс. попыток пароля должно быть ≥ 1")
        if self.backup_interval_hours is not None and self.backup_interval_hours < 0:
            raise ValueError("Интервал резервной копии (ч) должен быть ≥ 0")
        for pct_name, pct_val in (
            ("short_pause_chance", self.short_pause_chance),
            ("long_pause_chance", self.long_pause_chance),
            ("jitter_morning_percent", self.jitter_morning_percent),
            ("jitter_evening_percent", self.jitter_evening_percent),
            ("presence_history_chance", self.presence_history_chance),
            ("presence_read_chance", self.presence_read_chance),
            ("presence_react_chance", self.presence_react_chance),
            ("presence_idle_chance", self.presence_idle_chance),
        ):
            if pct_val is not None and not (0 <= pct_val <= 100):
                raise ValueError(f"Параметр «{pct_name}» должен быть от 0 до 100")
        if self.text_similarity_max is not None and not (
            0.5 <= self.text_similarity_max <= 0.99
        ):
            raise ValueError("Сходство текстов должно быть от 0.5 до 0.99")
        if self.text_dedupe_window is not None and self.text_dedupe_window < 1:
            raise ValueError("Окно антидублей должно быть ≥ 1")
        _range_labels = {
            "short_pause": "Короткая пауза",
            "long_pause": "Длинная пауза",
            "break": "Перерыв",
        }
        for a, b, name in (
            (self.short_pause_min_sec, self.short_pause_max_sec, "short_pause"),
            (self.long_pause_min_sec, self.long_pause_max_sec, "long_pause"),
            (self.break_min_sec, self.break_max_sec, "break"),
        ):
            label = _range_labels.get(name, name)
            if a is not None and a < 0:
                raise ValueError(f"{label}: мин должно быть ≥ 0")
            if b is not None and b < 0:
                raise ValueError(f"{label}: макс должно быть ≥ 0")
            if a is not None and b is not None and a > b:
                raise ValueError(f"{label}: мин не может быть больше макс")
        if self.break_after_n is not None and self.break_after_n < 0:
            raise ValueError("Перерыв после N должен быть ≥ 0")
        for field, raw, field_ru in (
            ("send_windows_weekday", self.send_windows_weekday, "Окна будни"),
            ("send_windows_weekend", self.send_windows_weekend, "Окна выходные"),
        ):
            if raw is None:
                continue
            s = str(raw).strip()
            if not s:
                continue
            if not __import__("main")._parse_send_windows(s):
                raise ValueError(
                    f"{field_ru}: ожидается формат вроде 9-13,16-21 или 09:00-13:00"
                )
        if self.timezone_offset_hours is not None and not (
            -12.0 <= self.timezone_offset_hours <= 14.0
        ):
            raise ValueError("Часовой пояс UTC+ должен быть от -12 до 14")
        if self.circuit_break_minutes is not None and self.circuit_break_minutes < 1:
            raise ValueError("Автопауза (мин) должна быть ≥ 1")
        if self.cooldown_fail_max_hours is not None and self.cooldown_fail_max_hours < 0:
            raise ValueError("Макс. пауза после ошибки (ч) должна быть ≥ 0")
        if (
            self.cooldown_disable_after_fails is not None
            and self.cooldown_disable_after_fails < 0
        ):
            raise ValueError("Отключение после N ошибок должно быть ≥ 0")
        return self


class BulkProfilesIn(BaseModel):
    profiles: list[ProfileIn]
