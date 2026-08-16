"""Pydantic models for panel API routes."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

import antiban_core


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
    code: str


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
    worker_pool_size: int | None = None
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
        lo = self.delay_min_sec
        hi = self.delay_max_sec
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("Мин. пауза не может быть больше макс. паузы")
        if self.jitter_percent is not None and not (0 <= self.jitter_percent <= 100):
            raise ValueError("Разброс (%) должен быть от 0 до 100")
        if self.max_msgs_per_profile_day is not None and self.max_msgs_per_profile_day < 1:
            raise ValueError("Лимит сообщений в день должен быть ≥ 1")
        dlo, dhi = self.daily_limit_min, self.daily_limit_max
        if dlo is not None and dlo < 1:
            raise ValueError("Лимит/день мин должен быть ≥ 1")
        if dhi is not None and dhi < 1:
            raise ValueError("Лимит/день макс должен быть ≥ 1")
        if dlo is not None and dhi is not None and dlo > dhi:
            raise ValueError("Лимит/день мин не может быть больше макс")
        if self.message_pick_mode is not None and self.message_pick_mode not in (
            "random_norepeat",
            "round_robin",
        ):
            raise ValueError("Режим сообщений: случайно без повтора или по кругу")
        if self.campaign_goal is not None and self.campaign_goal not in (
            "daily_limits",
            "message_pool",
        ):
            raise ValueError("Цель кампании: дневные лимиты или пул сообщений")
        if self.warmup_days is not None and self.warmup_days < 1:
            raise ValueError("Дней прогрева должно быть ≥ 1")
        if self.cooldown_reauth_hours is not None and self.cooldown_reauth_hours < 0:
            raise ValueError("Пауза после повторного входа (ч) должна быть ≥ 0")
        if self.cooldown_fail_hours is not None and self.cooldown_fail_hours < 0:
            raise ValueError("Пауза после ошибки (ч) должна быть ≥ 0")
        if self.password_max_attempts is not None and self.password_max_attempts < 1:
            raise ValueError("Макс. попыток пароля должно быть ≥ 1")
        if self.backup_interval_hours is not None and self.backup_interval_hours < 0:
            raise ValueError("Интервал резервной копии (ч) должен быть ≥ 0")
        if self.worker_pool_size is not None and not (1 <= self.worker_pool_size <= 32):
            raise ValueError("Пул воркеров должен быть от 1 до 32")
        if self.day_skip_percent is not None and not (0 <= self.day_skip_percent <= 100):
            raise ValueError("Пропуск дня (%) должен быть от 0 до 100")
        if self.role_active_percent is not None and not (
            0 <= self.role_active_percent <= 100
        ):
            raise ValueError("Active (%) должен быть от 0 до 100")
        if self.role_quiet_percent is not None and not (
            0 <= self.role_quiet_percent <= 100
        ):
            raise ValueError("Quiet (%) должен быть от 0 до 100")
        if self.role_active_min is not None and self.role_active_min < 0:
            raise ValueError("Активных мин должно быть ≥ 0")
        if self.role_active_max is not None and self.role_active_max < 0:
            raise ValueError("Активных макс должно быть ≥ 0")
        if (
            self.role_active_min is not None
            and self.role_active_max is not None
            and self.role_active_min > self.role_active_max
        ):
            raise ValueError("Активных мин не может быть больше макс")
        if self.role_quiet_limit is not None and self.role_quiet_limit < 0:
            raise ValueError("Лимит тихих должен быть ≥ 0")
        for pct_name, pct_val in (
            ("short_pause_chance", self.short_pause_chance),
            ("long_pause_chance", self.long_pause_chance),
            ("lazy_day_percent", self.lazy_day_percent),
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
            "warmup_start": "Прогрев старт",
        }
        for a, b, name in (
            (self.short_pause_min_sec, self.short_pause_max_sec, "short_pause"),
            (self.long_pause_min_sec, self.long_pause_max_sec, "long_pause"),
            (self.break_min_sec, self.break_max_sec, "break"),
            (self.warmup_start_min, self.warmup_start_max, "warmup_start"),
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
        if self.lazy_day_factor is not None and not (0.05 <= self.lazy_day_factor <= 1.0):
            raise ValueError("Коэффициент ленивого дня должен быть от 0.05 до 1.0")
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


