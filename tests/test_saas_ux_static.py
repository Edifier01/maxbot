"""Static SaaS UX strings — FEATURE-SAAS-UX-2026 (no server required)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
ADMIN = (ROOT / "static" / "admin.html").read_text(encoding="utf-8")
AUTH = (ROOT / "static" / "auth.html").read_text(encoding="utf-8")


def test_index_subscription_start_gate_and_no_svodka_tab():
    assert "Обратитесь к администратору" in INDEX
    assert "оформите подписку" not in INDEX
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
    assert "dash-stat" in INDEX
    assert "renderDashStats" in INDEX
    assert "dashSummaryError" in INDEX
    assert 'id="dashCardsPanel" class="campaign-admin-only"' in INDEX
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


def test_index_user_progress_hidden_simple_view_only():
    assert "body.simple-campaign #dashProgressPanel" in INDEX
    assert "body.simple-campaign #progressWrap" in INDEX
    assert "function isSimpleCampaignView()" in INDEX
    assert "isUserRole() || isAdminImpersonating()" not in INDEX
    assert "return isUserRole();" in INDEX
    assert "if (isUserRole())" in INDEX
    assert "renderDashProgress" in INDEX
    assert "dashStats" in INDEX
    assert 'data-tab="messages"' in INDEX
    assert 'data-tab="settings"' in INDEX
    assert 'data-tab="password"' not in INDEX
    assert "Нет файла сообщений. Обратитесь к администратору." in INDEX
    assert "btn.innerHTML = orig" in INDEX
    assert 'aria-label="Предыдущая страница"' in INDEX
    assert 'aria-hidden="true"' in INDEX
    assert "toggleGroupActive" in INDEX
    assert "lookupProfileByPhone" in INDEX
    assert "createGroupHint" in INDEX
    assert "translateY(-1px)" not in INDEX


def test_admin_stats_subscription_extend_and_empty_users():
    assert ">Статистика</button>" in ADMIN
    assert "Учреждений пока нет" in ADMIN
    assert "subscription/revoke" in ADMIN
    assert "от оставшихся дней" in ADMIN
    assert 'data-action="grant-days"' in ADMIN
    assert 'data-action="revoke-sub"' in ADMIN
    assert 'data-action="impersonate"' in ADMIN
    assert "Открыть кабинет" in ADMIN
    assert "cursor: text" in ADMIN
    assert "Загрузка…" in ADMIN
    assert "применяется ко всем учреждениям" in ADMIN


def test_auth_forms_enter_submit_and_errors():
    assert '<form id="formLogin"' in AUTH
    assert '<form id="formRegister"' in AUTH
    assert "event.preventDefault()" in AUTH
    assert "formatApiError" in AUTH
    assert "Вход…" in AUTH
    assert "Регистрация…" in AUTH
    assert "Пароли не совпадают" in AUTH
    assert 'spellcheck="false"' in AUTH
    assert 'autocomplete="organization"' in AUTH
    assert 'id="rememberMeLogin"' in AUTH
    assert 'id="rememberMeRegister"' in AUTH
    tabs_idx = AUTH.index('role="tablist"')
    login_form = AUTH.index('id="formLogin"')
    remember_idx = AUTH.index('id="rememberMeLogin"')
    assert tabs_idx < login_form < remember_idx
