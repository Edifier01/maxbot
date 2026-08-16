"""Static SaaS UX strings — FEATURE-SAAS-UX-2026 (no server required)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
ADMIN = (ROOT / "static" / "admin.html").read_text(encoding="utf-8")
AUTH = (ROOT / "static" / "auth.html").read_text(encoding="utf-8")
INDEX_JS = (ROOT / "static" / "js" / "index.js").read_text(encoding="utf-8")
ADMIN_JS = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")
AUTH_JS = (ROOT / "static" / "js" / "auth.js").read_text(encoding="utf-8")
CADDYFILE = (ROOT / "caddy" / "Caddyfile").read_text(encoding="utf-8")
INDEX_ALL = INDEX + "\n" + INDEX_JS
ADMIN_ALL = ADMIN + "\n" + ADMIN_JS
AUTH_ALL = AUTH + "\n" + AUTH_JS

_SCRIPT_OPEN = re.compile(r"<script\b([^>]*)>", re.I)


def test_external_scripts_and_no_inline_handlers():
    assert '<script src="/static/js/index.js"' in INDEX
    assert '<script src="/static/js/admin.js"' in ADMIN
    assert '<script src="/static/js/auth.js"' in AUTH
    for name, html in (("index", INDEX), ("admin", ADMIN), ("auth", AUTH)):
        assert "onclick=" not in html, name
        assert "onsubmit=" not in html, name
        assert "onchange=" not in html, name
        assert "onkeydown=" not in html, name
        opens = _SCRIPT_OPEN.findall(html)
        assert opens, name
        for attrs in opens:
            assert re.search(r"\bsrc\s*=", attrs, re.I), f"{name}: script without src"
        assert not re.search(r"<script\b[^>]*>\s*[^<\s]", html, re.I), name


def test_cookie_only_client_no_js_jwt_store():
    for name, blob in (
        ("index.html", INDEX),
        ("admin.html", ADMIN),
        ("auth.html", AUTH),
        ("index.js", INDEX_JS),
        ("admin.js", ADMIN_JS),
        ("auth.js", AUTH_JS),
    ):
        assert "sessionStorage.setItem('maxAuthToken'" not in blob, name
        assert "sessionStorage.setItem('maxAdminAuthToken'" not in blob, name
    assert "exit-impersonation" in ADMIN_JS or "exit-impersonation" in INDEX_JS
    assert "JSON.stringify({ type: 'auth' })" in INDEX_JS
    assert "token: getAuthToken()" not in INDEX_JS
    assert "type: 'auth', token" not in INDEX_JS
    assert "Authorization" not in ADMIN_JS
    assert "Authorization" not in AUTH_JS
    assert "Bearer " not in AUTH_JS
    assert "if (!_serverMode)" in INDEX_JS
    assert "opts.headers['Authorization'] = 'Bearer ' + pin" in INDEX_JS


def test_caddy_csp_script_src_self_no_unsafe_inline():
    assert "script-src 'self'" in CADDYFILE
    assert "script-src 'self' 'unsafe-inline'" not in CADDYFILE
    assert "style-src 'self' 'unsafe-inline'" in CADDYFILE


def test_index_subscription_start_gate_and_no_svodka_tab():
    assert "Нет активной подписки. Обратитесь к администратору." in INDEX_ALL
    assert "оформите подписку" not in INDEX_ALL
    assert 'data-tab="svodka"' not in INDEX
    assert 'data-tab="campaign"' in INDEX
    assert "Отправка:" in INDEX
    assert "p.status === 'banned'" in INDEX_ALL
    assert "Забанен" in INDEX_ALL


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
    assert 'data-action="delete-user"' in ADMIN_ALL
    assert 'onclick="deleteUser' not in ADMIN_ALL
    assert "deleteUser" in ADMIN_ALL
    assert "worker_pool_size" in ADMIN_ALL
    assert "index.html" not in ADMIN_ALL


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
    assert "renderDashStats" in INDEX_ALL
    assert "dashSummaryError" in INDEX
    assert 'id="dashCardsPanel" class="campaign-admin-only"' in INDEX
    assert "maxAdminGlobalTab" not in INDEX_ALL
    assert "_adminGlobalMode" not in INDEX_ALL


def test_index_simple_campaign_layout_slots():
    assert 'id="runBadgeSlot"' in INDEX
    assert "mountCampaignLayout" in INDEX_ALL
    assert "campaign-user-only" in INDEX
    assert "body.simple-campaign .campaign-user-only" in INDEX
    assert "classList.toggle('simple-campaign'" in INDEX_ALL
    user_block = INDEX.index('id="userSummaryBlock"')
    toolbar = INDEX.index('class="toolbar row"', user_block)
    assert user_block < toolbar
    slot = INDEX.index('id="runBadgeSlot"')
    schedule = INDEX.index('id="scheduleAt"', slot)
    assert slot < schedule


def test_index_user_progress_hidden_simple_view_only():
    assert "body.simple-campaign #dashProgressPanel" in INDEX
    assert "progressWrap" not in INDEX_ALL
    assert "function isSimpleCampaignView()" in INDEX_ALL
    assert "isUserRole() || isAdminImpersonating()" not in INDEX_ALL
    assert "return isUserRole();" in INDEX_ALL
    assert "if (isUserRole())" in INDEX_ALL
    assert "renderDashProgress" in INDEX_ALL
    assert "dashStats" in INDEX
    assert 'data-tab="messages"' in INDEX
    assert 'data-tab="settings"' in INDEX
    assert 'data-tab="password"' not in INDEX
    assert "Нет файла сообщений. Обратитесь к администратору." in INDEX_ALL
    assert "btn.innerHTML = orig" in INDEX_ALL
    assert 'aria-label="Предыдущая страница"' in INDEX_ALL
    assert 'aria-hidden="true"' in INDEX
    assert "toggleGroupActive" in INDEX_ALL
    assert "lookupProfileByPhone" in INDEX_ALL
    assert "createGroupHint" in INDEX
    assert "translateY(-1px)" not in INDEX


def test_admin_stats_subscription_extend_and_empty_users():
    assert ">Статистика</button>" in ADMIN_ALL
    assert "Учреждений пока нет" in ADMIN_ALL
    assert "subscription/revoke" in ADMIN_ALL
    assert "от оставшихся дней" in ADMIN_ALL
    assert 'data-action="grant-days"' in ADMIN_ALL
    assert 'data-action="revoke-sub"' in ADMIN_ALL
    assert 'data-action="impersonate"' in ADMIN_ALL
    assert "Открыть кабинет" in ADMIN_ALL
    assert "cursor: text" in ADMIN
    assert "Загрузка…" in ADMIN_ALL
    assert "применяется ко всем учреждениям" in ADMIN


def _admin_save_global_body() -> str:
    m = re.search(
        r"async function saveGlobalSettings\(\) \{.*?const body = \{([^}]+)\}",
        ADMIN_JS,
        re.S,
    )
    assert m, "saveGlobalSettings body object not found"
    return m.group(1)


def test_admin_global_pacing_form_covers_allowlist():
    from app.settings_scope import GLOBAL_PACING_NEVER_COPY, GLOBAL_PACING_SETTING_KEYS

    assert "windowsWeekday" in ADMIN
    assert "human_rhythm" in ADMIN_ALL
    assert "presenceOn" in ADMIN
    assert "circuitMins" in ADMIN
    assert "send_windows_weekday" in ADMIN_JS
    assert "human_presence_enabled" in ADMIN_JS
    assert "circuit_break_minutes" in ADMIN_JS

    body = _admin_save_global_body()
    for key in GLOBAL_PACING_SETTING_KEYS:
        assert key in body, key
    for key in GLOBAL_PACING_NEVER_COPY:
        assert key not in body, key
    assert "worker_pool_size" not in body
    assert "worker_pool_size" in ADMIN_JS
    assert 'id="pool-' in ADMIN_JS or "pool-" in ADMIN_JS
    assert "api_pin" not in ADMIN
    assert "webhookUrl" not in ADMIN
    assert "auto_run" not in body


def test_index_cabinet_activity_journal_not_admin_only():
    assert 'id="userActivityLog"' in INDEX
    assert 'id="userActivityBlock"' in INDEX
    block = INDEX[INDEX.index('id="userActivityBlock"') : INDEX.index('id="userActivityLog"') + 50]
    assert "campaign-user-only" in block
    assert "campaign-admin-only" not in block
    assert 'id="campaignLog"' in INDEX
    camp = INDEX.index('id="campaignLog"')
    assert "campaign-admin-only" in INDEX[max(0, camp - 200) : camp]
    assert "renderUserActivity" in INDEX_JS
    assert "kind === 'failed'" in INDEX_JS
    assert "kind === 'fail'" not in INDEX_JS
    assert "s.activity" in INDEX_JS
    assert "Пока нет событий" in INDEX_ALL
    assert "userActivityLog" in INDEX_JS


def test_admin_auth_skip_link_and_main_content():
    assert 'class="skip-link"' in ADMIN
    assert 'id="main-content"' in ADMIN
    assert 'class="skip-link"' in AUTH
    assert 'id="main-content"' in AUTH


def test_auth_forms_enter_submit_and_errors():
    assert '<form id="formLogin"' in AUTH
    assert '<form id="formRegister"' in AUTH
    assert "event.preventDefault()" in AUTH_ALL
    assert "formatApiError" in AUTH_ALL
    assert "Вход…" in AUTH_ALL
    assert "Регистрация…" in AUTH_ALL
    assert "Пароли не совпадают" in AUTH_ALL
    assert 'spellcheck="false"' in AUTH
    assert 'autocomplete="organization"' in AUTH
    assert 'id="rememberMeLogin"' in AUTH
    assert 'id="rememberMeRegister"' in AUTH
    tabs_idx = AUTH.index('role="tablist"')
    login_form = AUTH.index('id="formLogin"')
    remember_idx = AUTH.index('id="rememberMeLogin"')
    assert tabs_idx < login_form < remember_idx
