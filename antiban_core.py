"""Чистые хелперы антибана без зависимости от FastAPI/SQLite."""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone


def clamp_range(lo: float, hi: float) -> tuple[float, float]:
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def local_now(offset_hours: float = 3.0) -> datetime:
    """«Локальное» время с фиксированным UTC-смещением."""
    offset = max(-12.0, min(14.0, float(offset_hours)))
    tz = timezone(timedelta(hours=offset))
    return datetime.now(tz).replace(tzinfo=None)


def lognormal_delay_sec(
    lo: float,
    hi: float,
    *,
    jitter_percent: float = 40.0,
    sigma: float = 0.45,
) -> float:
    """Пауза с логнормальным распределением (не uniform).

    Медиана около (lo+hi)/2; мягкий хвост за пределы [lo, hi].
    """
    lo, hi = clamp_range(float(lo), float(hi))
    mid = max(1.0, (lo + hi) / 2.0)
    mu = math.log(mid) - sigma**2 / 2.0
    delay = random.lognormvariate(mu, sigma)
    delay = max(lo * 0.5, min(hi * 2.5, delay))
    jitter = max(0.0, min(100.0, float(jitter_percent))) / 100.0
    delay *= random.uniform(1 - jitter * 0.3, 1 + jitter * 0.3)
    return max(1.0, delay)


def escalating_cooldown_hours(
    fail_count: int,
    *,
    base_hours: float = 2.0,
    max_hours: float = 48.0,
) -> float:
    """Экспоненциальный cooldown: base * 2^(n-1), capped."""
    n = max(1, int(fail_count))
    hours = float(base_hours) * (2 ** (n - 1))
    return min(hours, float(max_hours))


def pick_proxy_from_pool(
    raw: str | None,
    profile_id: int | None = None,
) -> str | None:
    """Один URL или пул (строки / `;`); ротация по profile_id."""
    if not raw:
        return None
    proxies = [
        p.strip()
        for chunk in str(raw).replace(";", "\n").splitlines()
        for p in [chunk.strip()]
        if p and not p.startswith("#")
    ]
    if not proxies:
        return None
    if len(proxies) == 1:
        return proxies[0]
    if profile_id is not None:
        return proxies[int(profile_id) % len(proxies)]
    return random.choice(proxies)


def dedupe_window(configured: int, enabled_profiles: int) -> int:
    """Окно анти-дубликатов: max(настройка, аккаунты×2)."""
    cfg = max(1, int(configured))
    n = max(0, int(enabled_profiles))
    return max(cfg, n * 2)
