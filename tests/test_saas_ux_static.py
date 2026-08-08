"""Static SaaS UX strings — FEATURE-SAAS-UX-2026 (no server required)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
ADMIN = (ROOT / "static" / "admin.html").read_text(encoding="utf-8")


def test_index_subscription_start_gate_and_no_svodka_tab():
    assert "оформите подписку" in INDEX
    assert 'data-tab="svodka"' not in INDEX
    assert 'data-tab="campaign"' in INDEX
    assert "Отправка:" in INDEX
    assert "p.status === 'banned'" in INDEX
    assert "Забанен" in INDEX


def test_index_worker_pool_hidden_for_users():
    assert "workerPoolRow" in INDEX
    assert "settings-admin-only" in INDEX


def test_admin_tab_navigation_and_subscription_ux():
    assert 'role="tablist"' in ADMIN
    assert 'data-tab="users"' in ADMIN
    assert 'data-tab="settings"' in ADMIN
    assert 'data-tab="messages"' in ADMIN
    assert "globalSettingsPanel" in ADMIN
    assert "globalMessagesPanel" in ADMIN
    assert "Настройки рассылки" in ADMIN
    assert "Сообщения (пул)" in ADMIN
    assert "days-group" not in ADMIN
    assert "grantDays" not in ADMIN
    assert 'data-action="delete-user"' in ADMIN
    assert 'onclick="deleteUser' not in ADMIN
    assert "deleteUser" in ADMIN
    assert "worker_pool_size" in ADMIN
    assert "index.html" not in ADMIN


def test_index_user_dashboard_visible():
    assert "dashStats" in INDEX
    assert "dashCards" in INDEX
    assert 'id="dashCards"' in INDEX
    assert 'id="userSummaryBlock"' in INDEX
    assert 'id="userSummaryContent"' in INDEX
    assert 'id="adminSummarySlot"' in INDEX
    assert "summary-panel" in INDEX
    assert "Сводка" in INDEX
    stats_idx = INDEX.index('id="dashStats"')
    content_idx = INDEX.index('id="userSummaryContent"')
    assert content_idx < stats_idx
    assert "maxAdminGlobalTab" not in INDEX
    assert "_adminGlobalMode" not in INDEX


def test_index_simple_campaign_layout_slots():
    assert 'id="runBadgeSlot"' in INDEX
    assert "mountCampaignLayout" in INDEX
    assert "campaign-user-only" in INDEX
    assert "body.simple-campaign .campaign-user-only" in INDEX
    assert "classList.toggle('simple-campaign'" in INDEX
    user_block = INDEX.index('id="userSummaryBlock"')
    toolbar = INDEX.index('class="toolbar row"', user_block)
    assert user_block < toolbar
    slot = INDEX.index('id="runBadgeSlot"')
    schedule = INDEX.index('id="scheduleAt"', slot)
    assert slot < schedule
