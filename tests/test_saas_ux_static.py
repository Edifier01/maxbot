"""Static SaaS UX strings — FEATURE-SAAS-UX-2026 (no server required)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
ADMIN = (ROOT / "static" / "admin.html").read_text(encoding="utf-8")


def test_index_subscription_start_gate_and_no_svodka_tab():
    assert "оформите подписку" in INDEX
    assert "Сводка" not in INDEX
    assert 'data-tab="campaign"' in INDEX
    assert "Отправка:" in INDEX
    assert "p.status === 'banned'" in INDEX
    assert "Забанен" in INDEX


def test_index_worker_pool_hidden_for_users():
    assert "workerPoolRow" in INDEX
    assert "settings-admin-only" in INDEX


def test_admin_global_panels_and_delete_user():
    assert "globalSettingsPanel" in ADMIN
    assert "globalMessagesPanel" in ADMIN
    assert "Настройки рассылки" in ADMIN
    assert "Сообщения (пул)" in ADMIN
    assert "deleteUser" in ADMIN
    assert "worker_pool_size" in ADMIN
    assert "index.html" not in ADMIN
