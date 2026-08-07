"""Чистые хелперы антибана без зависимости от FastAPI/SQLite."""

from __future__ import annotations

import base64
import math
import random
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlparse


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


def parse_proxy_list(raw: str | None) -> list[str]:
    """URL прокси из одной строки, списка строк или через `;`."""
    if not raw:
        return []
    return [
        p.strip()
        for chunk in str(raw).replace(";", "\n").splitlines()
        for p in [chunk.strip()]
        if p and not p.startswith("#")
    ]


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    buf = b""
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise ConnectionError("соединение закрыто")
        buf += chunk
    return buf


def _check_socks5(
    host: str,
    port: int,
    user: str | None,
    password: str | None,
    *,
    timeout: float,
) -> tuple[bool, str]:
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(timeout)
    try:
        if user and password:
            sock.sendall(b"\x05\x01\x02")
        else:
            sock.sendall(b"\x05\x01\x00")
        resp = _recv_exact(sock, 2)
        if resp[0] != 0x05:
            return False, "не SOCKS5"
        method = resp[1]
        if method == 0xFF:
            return False, "SOCKS5: прокси отклонил подключение"
        if method == 0x02:
            if not user or not password:
                return False, "SOCKS5: нужен логин и пароль"
            u = user.encode("utf-8")
            p = password.encode("utf-8")
            if len(u) > 255 or len(p) > 255:
                return False, "логин/пароль прокси слишком длинные"
            sock.sendall(bytes([0x01, len(u)]) + u + bytes([len(p)]) + p)
            auth = _recv_exact(sock, 2)
            if auth[1] != 0x00:
                return False, "SOCKS5: неверный логин или пароль"
        elif method != 0x00:
            return False, f"SOCKS5: неподдерживаемый метод {method}"
        return True, ""
    finally:
        sock.close()


def _check_http_proxy(
    host: str,
    port: int,
    user: str | None,
    password: str | None,
    *,
    timeout: float,
) -> tuple[bool, str]:
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(timeout)
    try:
        auth = ""
        if user and password:
            cred = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
            auth = f"Proxy-Authorization: Basic {cred}\r\n"
        req = (
            "CONNECT api.oneme.ru:443 HTTP/1.1\r\n"
            "Host: api.oneme.ru:443\r\n"
            f"{auth}\r\n"
        )
        sock.sendall(req.encode("ascii"))
        resp = sock.recv(512).decode("latin-1", errors="replace")
        status = resp.split("\r\n", 1)[0] if resp else ""
        if " 200" in status:
            return True, ""
        return False, f"HTTP proxy: {status[:120] or 'нет ответа'}"
    finally:
        sock.close()


def check_proxy(raw: str | None, *, timeout: float = 8.0) -> tuple[bool, str]:
    """Проверка TCP + auth прокси. Пустой URL — OK (прокси не задан)."""
    url = (raw or "").strip()
    if not url:
        return True, ""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "socks5").lower()
    host = parsed.hostname or ""
    if not host:
        return False, "некорректный URL прокси"
    port = parsed.port or (1080 if "socks" in scheme else 8080)
    user = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    try:
        if scheme.startswith("socks"):
            return _check_socks5(host, port, user, password, timeout=timeout)
        if scheme in ("http", "https"):
            return _check_http_proxy(host, port, user, password, timeout=timeout)
        return False, f"неподдерживаемая схема прокси: {scheme}"
    except OSError as e:
        return False, str(e)


def pick_proxy_from_pool(
    raw: str | None,
    profile_id: int | None = None,
) -> str | None:
    """Один URL или пул (строки / `;`); ротация по profile_id."""
    proxies = parse_proxy_list(raw)
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
