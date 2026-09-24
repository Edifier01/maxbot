let openGroupId = null;
    const draftInputs = {};
    let groupsRefreshPaused = false;
    let focusedInputId = null;
    const authWatchers = new Set();
    let authModalOpen = false;
    const PROFILE_PAGE = 20;
    const groupProfilePages = {};
    let sendLogOffset = 0;
    let _wasRunning = false;

    function toast(msg, type = 'info', duration = 4000) {
      let c = document.getElementById('toast-container');
      if (!c) {
        c = document.createElement('div');
        c.id = 'toast-container';
        c.setAttribute('role', 'status');
        c.setAttribute('aria-live', 'polite');
        document.body.appendChild(c);
      }
      const t = document.createElement('div');
      t.className = `toast ${type}`;
      t.textContent = msg;
      c.appendChild(t);
      setTimeout(() => t.remove(), duration);
    }

    async function withLoading(btn, asyncFn) {
      const orig = btn.innerHTML;
      btn.disabled = true;
      btn.textContent = btn.getAttribute('data-loading-label') || '…';
      try {
        await asyncFn();
      } catch (e) {
        toast(e.message || 'Ошибка', 'error');
      } finally {
        btn.innerHTML = orig;
        if (btn.id === 'btnStart') updateCampaignStartGate();
        else btn.disabled = false;
      }
    }

    function renderLogLines(lines) {
      if (!lines || !lines.length) return '—';
      return lines.map(line => {
        let cls = '';
        if (line.includes('Ошибка')) cls = 'fail';
        else if (line.includes('Успех #') || line.includes('Готово')) cls = 'ok';
        return `<div class="log-line ${cls}">${esc(line)}</div>`;
      }).join('');
    }

    function renderUserActivity(activity) {
      const el = document.getElementById('userActivityLog');
      if (!el) return;
      if (!Array.isArray(activity) || !activity.length) {
        el.textContent = 'Пока нет событий';
        return;
      }
      el.innerHTML = activity.map(item => {
        const ts = item && item.ts != null ? String(item.ts) : '';
        const text = item && item.text != null ? String(item.text) : '';
        const kind = item && item.kind != null ? String(item.kind) : '';
        let cls = '';
        if (kind === 'failed') cls = 'fail';
        else if (kind === 'sent') cls = 'ok';
        const line = ts ? (ts + '  ' + text) : text;
        return `<div class="log-line ${cls}">${esc(line)}</div>`;
      }).join('');
      el.scrollTop = el.scrollHeight;
    }

    async function tryRestoreSession() {
      try {
        const r = await fetch('/api/auth/restore-session', {
          method: 'POST',
          credentials: 'same-origin',
        });
        return r.ok;
      } catch (_) {
        return false;
      }
    }

    async function exitImpersonation() {
      try {
        await fetch('/api/auth/exit-impersonation', {
          method: 'POST',
          credentials: 'same-origin',
        });
      } catch (_) {}
      sessionStorage.removeItem('maxImpersonating');
      location.href = '/admin.html';
    }

    async function logoutUser() {
      try {
        await fetch('/api/auth/logout', {
          method: 'POST',
          credentials: 'same-origin',
        });
      } catch (_) {}
      sessionStorage.removeItem('maxImpersonating');
      location.href = '/auth.html';
    }

    let _serverMode = false;
    let _userRole = 'local';
    let _subscriptionActive = true;
    let _subscriptionExpiresAt = null;
    let _adminImpersonating = false;
    let _lastStatus = null;
    let _dashboardLoadSequence = 0;
    let _readinessRevision = null;
    let _readinessKnown = false;
    let _readinessReady = false;
    let _readinessRequestSequence = 0;
    let _attentionOffset = 0;
    let _attentionTotal = 0;
    let _attentionLoadSequence = 0;
    let _readinessStatusSignature = null;
    let _readinessRefreshTimer = null;
    const CAMPAIGN_COMMAND_STORAGE_KEY = 'maxbot.pendingCampaignCommand.v1';
    const CAMPAIGN_COMMAND_PENDING_STATES = new Set(['preflight', 'testing', 'stopping', 'unknown']);
    const CAMPAIGN_COMMAND_LABELS = Object.freeze({
      start: 'Старт', stop: 'Стоп', pause: 'Пауза', test: 'Тест',
    });

    function isUserRole() {
      return _serverMode && _userRole === 'user';
    }

    function isAdminImpersonating() {
      return _serverMode && _userRole === 'admin' && _adminImpersonating;
    }

    /** Institution user cabinet: start/stop + stats only. Impersonating admin gets full ops. */
    function isSimpleCampaignView() {
      return isUserRole();
    }

    function formatSubscriptionDate(iso) {
      if (!iso) return null;
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
      return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
    }

    function subscriptionDaysLeft(iso) {
      if (!iso) return null;
      const exp = new Date(iso);
      if (Number.isNaN(exp.getTime())) return null;
      const now = new Date();
      return Math.ceil((exp.getTime() - now.getTime()) / 86400000);
    }

    function applySubscriptionBadge() {
      const el = document.getElementById('subscriptionBadge');
      if (!el) return;
      if (!isUserRole()) {
        el.style.display = 'none';
        return;
      }
      el.style.display = '';
      if (!_subscriptionActive) {
        const expiredLabel = _subscriptionExpiresAt
          ? formatSubscriptionDate(_subscriptionExpiresAt)
          : null;
        el.textContent = expiredLabel
          ? 'Подписка истекла ' + expiredLabel
          : 'Подписка не оформлена';
        el.className = 'badge stop';
        el.title = expiredLabel
          ? 'Истекла ' + expiredLabel + '. Обратитесь к администратору'
          : 'Обратитесь к администратору';
        return;
      }
      const label = _subscriptionExpiresAt ? formatSubscriptionDate(_subscriptionExpiresAt) : null;
      el.textContent = label
        ? 'Подписка активна до ' + label
        : 'Подписка активна';
      el.title = label ? 'Действует до ' + label : 'Подписка активна';
      const days = _subscriptionExpiresAt ? subscriptionDaysLeft(_subscriptionExpiresAt) : null;
      if (days !== null && days <= 7) el.className = 'badge warn';
      else el.className = 'badge ok';
    }

    function applyCampaignButtonState(s) {
      const start = document.getElementById('btnStart');
      const stop = document.getElementById('btnStop');
      if (!start || !stop) return;
      start.classList.remove('campaign-btn-active', 'campaign-btn-idle');
      stop.classList.remove('campaign-btn-active', 'campaign-btn-idle');
      if (!isSimpleCampaignView()) return;
      if (isUserRole() && !_subscriptionActive) {
        updateCampaignStartGate();
        start.title = 'Обратитесь к администратору';
        stop.classList.remove('campaign-btn-active', 'campaign-btn-idle');
        return;
      }
      updateCampaignStartGate();
      start.title = isUserRole() && !_readinessReady
        ? 'Сначала устраните причины в блоке «Готовность к запуску»'
        : '';
      const on = !!(s && (s.running || s.auto_run));
      if (on) {
        stop.classList.add('campaign-btn-active');
        start.classList.add('campaign-btn-idle');
      } else {
        start.classList.add('campaign-btn-active');
        stop.classList.add('campaign-btn-idle');
      }
    }

    function updateCampaignStartGate() {
      const start = document.getElementById('btnStart');
      if (!start || !isUserRole()) return;
      start.disabled = !_subscriptionActive || !_readinessKnown || !_readinessReady;
    }

    const VALID_TABS = ['campaign', 'messages', 'groups', 'settings'];

    function isTabAccessible(tabId) {
      const btn = document.querySelector(`nav button[data-tab="${tabId}"]`);
      if (!btn || btn.style.display === 'none') return false;
      return VALID_TABS.includes(tabId);
    }

    function tabFromHash() {
      const h = location.hash.slice(1);
      return VALID_TABS.includes(h) ? h : null;
    }

    function syncTabHash(tabId) {
      const next = '#' + tabId;
      if (location.hash !== next) history.replaceState(null, '', next);
    }

    function applyTabFromHash() {
      const tab = tabFromHash();
      if (tab && isTabAccessible(tab)) switchTab(tab, { skipHash: true });
    }

    function initAccessibleTips() {
      document.querySelectorAll('#settings .tip[title]').forEach((el, i) => {
        const tip = el.getAttribute('title');
        if (!tip) return;
        const id = 'tip-desc-' + i;
        const span = document.createElement('span');
        span.id = id;
        span.className = 'sr-only';
        span.textContent = tip;
        el.insertAdjacentElement('afterend', span);
        el.setAttribute('aria-describedby', id);
        el.removeAttribute('title');
      });
    }

    function getFocusableIn(root) {
      return [...root.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
        .filter(n => !n.disabled && n.offsetParent !== null);
    }

    function switchTab(tabId, { skipHash = false } = {}) {
      const btn = document.querySelector(`nav button[data-tab="${tabId}"]`);
      if (!btn) return;
      document.querySelectorAll('nav button[role="tab"]').forEach(x => {
        x.classList.remove('active');
        x.setAttribute('aria-selected', 'false');
        x.setAttribute('tabindex', '-1');
      });
      document.querySelectorAll('main > section').forEach(x => {
        x.classList.remove('active');
        x.hidden = true;
      });
      btn.classList.add('active');
      btn.setAttribute('aria-selected', 'true');
      btn.setAttribute('tabindex', '0');
      const panel = document.getElementById(tabId);
      panel.classList.add('active');
      panel.hidden = false;
      if (!skipHash) syncTabHash(tabId);
      if (tabId === 'campaign') {
        loadDashboard().catch(error => {
          if (!(error instanceof PanelApiError)) toast('Не удалось обновить сводку.', 'error');
        });
      }
    }

    function getApiPin() {
      const s = sessionStorage.getItem('maxApiPin');
      if (s) return s;
      const legacy = localStorage.getItem('maxApiPin') || '';
      if (legacy) {
        sessionStorage.setItem('maxApiPin', legacy);
        localStorage.removeItem('maxApiPin');
      }
      return legacy;
    }

    function setApiPin(pin) {
      if (pin) sessionStorage.setItem('maxApiPin', pin);
      else sessionStorage.removeItem('maxApiPin');
      localStorage.removeItem('maxApiPin');
      if (_statusWs) {
        try { _statusWs.close(); } catch (_) {}
        _statusWs = null;
      }
      _statusWsRetry = 0;
      connectStatusWs();
    }

    const SAFE_ERROR_MESSAGES = Object.freeze({
      PROXY_AUTH_FAILED: 'Проверьте учётные данные прокси.',
      PROXY_CONNECT_FAILED: 'Не удалось подключиться через прокси.',
      MAX_ACCOUNT_BANNED: 'Аккаунт MAX заблокирован. Отправка остановлена.',
      ACCOUNT_AUTOMATION_CONFLICT: 'Аккаунт MAX уже используется в другой области автоматизации.',
      MAX_SESSION_REVOKED: 'Сессия MAX отозвана. Требуется повторный вход.',
      MAX_RATE_LIMIT: 'MAX временно ограничил частоту действий. Дождитесь разрешённого времени.',
      SEND_OUTCOME_UNKNOWN: 'Результат действия неизвестен. Сначала выполните сверку.',
      NETWORK_UNAVAILABLE: 'Сеть недоступна. Проверьте соединение.',
      SERVER_UNAVAILABLE: 'Сервис временно недоступен.',
      RESTORE_HOLD: 'Внешние действия остановлены до проверки восстановления.',
      UNCLASSIFIED: 'Операция не выполнена. Требуется проверка.',
    });
    const KNOWN_ERROR_CODES = new Set([
      'AUTH_REQUIRED', 'AUTH_SESSION_EXPIRED', 'AUTH_SESSION_REVOKED', 'LOGIN_INVALID',
      'PERMISSION_DENIED', 'SUBSCRIPTION_INACTIVE', 'PROFILE_NOT_FOUND', 'OBJECT_NOT_FOUND',
      'WORK_GROUP_SELECTION_REQUIRED', 'DESTINATION_REVIEW_REQUIRED', 'MEMBERSHIP_REVIEW_REQUIRED',
      'CONSENT_REVOKED', 'ACCOUNT_AUTOMATION_CONFLICT', 'ROUTE_MISSING', 'ROUTE_CONFLICT',
      'ROUTE_DISABLED', 'ROUTE_REVISION_CONFLICT', 'PROXY_URL_INVALID',
      'PROXY_UNSUPPORTED_SCHEME', 'PROXY_AUTH_FAILED', 'PROXY_CONNECT_FAILED',
      'PROXY_RESPONSE_INVALID', 'TLS_ERROR', 'MAX_CONNECT_FAILED', 'SDK_INCOMPATIBLE',
      'MAX_SESSION_REVOKED', 'MAX_RATE_LIMIT', 'MAX_ACCOUNT_BANNED', 'MAX_ACTION_FORBIDDEN',
      'CONNECTION_TIMEOUT', 'CODE_REQUEST_TIMEOUT', 'CODE_INPUT_TIMEOUT',
      'PASSWORD_INPUT_TIMEOUT', 'OTP_FORMAT_INVALID', 'OTP_INVALID', 'OTP_EXPIRED',
      'PASSWORD_INVALID', 'ATTEMPT_STATE_CONFLICT', 'ATTEMPT_EXPIRED', 'ATTEMPT_INTERRUPTED',
      'REGISTRATION_REQUIRED', 'SEND_OUTCOME_UNKNOWN', 'ACK_PERSIST_PENDING', 'CLEANUP_FAILED',
      'DAILY_BUDGET_ALLOCATED', 'CAMPAIGN_BUSY', 'PREVIEW_STALE', 'COMMAND_STATE_UNKNOWN',
      'STOP_PENDING', 'RESTORE_HOLD', 'MIGRATION_REVIEW_REQUIRED', 'VAULT_KEY_REQUIRED',
      'VAULT_INTEGRITY_FAILED', 'STORAGE_ERROR', 'POLICY_APPLY_PARTIAL', 'VERSION_CONFLICT',
      'POOL_EMPTY', 'IMPORT_INVALID', 'INPUT_TOO_LARGE', 'SETTINGS_NOT_LOADED',
      'API_RATE_LIMIT', 'NETWORK_UNAVAILABLE', 'SERVER_UNAVAILABLE', 'LOGOUT_NOT_CONFIRMED',
      'IMPERSONATION_EXIT_FAILED', 'UNCLASSIFIED',
    ]);

    const ERROR_ACTION_LABELS = Object.freeze({
      AUTHENTICATE: 'Открыть вход',
      REAUTHENTICATE: 'Войти заново',
      REVIEW_INPUT: 'Проверить ввод',
      REVIEW_ACCESS: 'Проверить доступ',
      REVIEW_SUBSCRIPTION: 'Проверить подписку',
      REVIEW_PROFILE: 'Открыть профили',
      REVIEW_OBJECT: 'Проверить объект',
      SELECT_GROUP: 'Выбрать группу',
      REVIEW_DESTINATION: 'Проверить назначение',
      REVIEW_MEMBERSHIP: 'Проверить участие',
      STOP_OPERATION: 'Открыть остановку',
      REVIEW_CONFLICT: 'Проверить конфликт',
      CONFIGURE_ROUTE: 'Настроить маршрут',
      REVIEW_ROUTE: 'Проверить маршрут',
      ENABLE_ROUTE: 'Открыть маршруты',
      RELOAD_ROUTE: 'Перезагрузить маршруты',
      REVIEW_PROXY: 'Проверить прокси',
      REVIEW_NETWORK: 'Проверить сеть',
      REVIEW_RUNTIME: 'Проверить среду',
      WAIT_RETRY: 'Показать состояние',
      STOP_TENANT: 'Открыть остановку',
      REVIEW_ACTION: 'Проверить операцию',
      RETRY_LOGIN: 'Открыть профили',
      RESTART_LOGIN: 'Открыть профили',
      REQUEST_NEW_CODE: 'Открыть профили',
      RELOAD_OPERATION: 'Перезагрузить операцию',
      RESTART_OPERATION: 'Открыть операцию',
      REVIEW_OPERATION: 'Открыть операцию',
      REVIEW_REGISTRATION: 'Открыть профили',
      RECONCILE_BEFORE_RETRY: 'Открыть журнал',
      PERSIST_ACK: 'Открыть журнал',
      REVIEW_CLEANUP: 'Открыть группы',
      REVIEW_BUDGET: 'Открыть операцию',
      WAIT_OPERATION: 'Показать состояние',
      RELOAD_PREVIEW: 'Перезагрузить операцию',
      REVIEW_RESTORE: 'Открыть операцию',
      REVIEW_MIGRATION: 'Открыть группы',
      UNLOCK_VAULT: 'Открыть настройки',
      REVIEW_VAULT: 'Открыть настройки',
      REVIEW_STORAGE: 'Открыть настройки',
      REVIEW_POLICY: 'Открыть настройки',
      RELOAD_DATA: 'Перезагрузить данные',
      REVIEW_LIBRARY: 'Открыть сообщения',
      REVIEW_IMPORT: 'Открыть сообщения',
      RELOAD_SETTINGS: 'Перезагрузить настройки',
      REVIEW_SESSION: 'Открыть вход',
    });

    function normalizedErrorAction(action) {
      return Object.prototype.hasOwnProperty.call(ERROR_ACTION_LABELS, action)
        ? action
        : 'REVIEW_OPERATION';
    }

    function formatStructuredApiError(detail, status) {
      if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
        const code = typeof detail.code === 'string' ? detail.code : '';
        const safeMessage = typeof detail.safe_message === 'string'
          ? detail.safe_message.trim().slice(0, 300)
          : '';
        if (KNOWN_ERROR_CODES.has(code) && safeMessage) return safeMessage;
        if (SAFE_ERROR_MESSAGES[code]) return SAFE_ERROR_MESSAGES[code];
      }
      if (typeof detail === 'string') return detail.slice(0, 300);
      if (Array.isArray(detail)) {
        return detail.map(x => (x && typeof x.msg === 'string' ? x.msg : 'Некорректный ввод')).join('; ');
      }
      return status >= 500 ? 'Сервис временно недоступен.' : 'Операция не выполнена.';
    }

    function safeErrorMetadata(value) {
      return typeof value === 'string' && /^[A-Za-z0-9._:-]{1,64}$/.test(value)
        ? value
        : '';
    }

    class PanelApiError extends Error {
      constructor(message, status, code, retryAfter, detail) {
        super(message);
        this.name = 'PanelApiError';
        this.status = status;
        this.code = KNOWN_ERROR_CODES.has(code) ? code : 'UNCLASSIFIED';
        this.retryAfter = retryAfter;
        const structured = detail && typeof detail === 'object' && !Array.isArray(detail)
          ? detail
          : {};
        this.source = safeErrorMetadata(structured.source);
        this.stage = safeErrorMetadata(structured.stage);
        this.recommendedAction = normalizedErrorAction(
          safeErrorMetadata(structured.recommended_action),
        );
        this.sessionPreserved = typeof structured.session_preserved === 'boolean'
          ? structured.session_preserved
          : null;
      }
    }

    const api = (path, opts = {}) => {
      opts.credentials = opts.credentials || 'same-origin';
      opts.headers = opts.headers || {};
      if (!_serverMode) {
        const pin = getApiPin();
        if (pin) opts.headers['Authorization'] = 'Bearer ' + pin;
      }
      return fetch('/api' + path, opts).then(async r => {
        let j = {};
        try { j = await r.json(); } catch (_) {}
        if (!r.ok) {
          const detail = j && j.detail;
          const code = detail && typeof detail === 'object' && detail.code ? String(detail.code) : '';
          const retryAfter = r.headers.get('Retry-After');
          throw new PanelApiError(
            formatStructuredApiError(detail, r.status) || r.statusText || ('HTTP ' + r.status),
            r.status,
            code || ('HTTP_' + r.status),
            retryAfter,
            detail,
          );
        }
        return j;
      }).catch(error => {
        if (error instanceof PanelApiError) throw error;
        throw new PanelApiError(
          SAFE_ERROR_MESSAGES.NETWORK_UNAVAILABLE,
          0,
          'NETWORK_UNAVAILABLE',
          null,
          { code: 'NETWORK_UNAVAILABLE' },
        );
      });
    };

    function setDashboardErrorMetadata(element, error) {
      [
        'data-error-code',
        'data-error-source',
        'data-error-stage',
        'data-error-action',
        'data-error-session-preserved',
      ].forEach(name => element.removeAttribute(name));
      if (!(error instanceof PanelApiError)) return;
      const values = {
        'data-error-code': safeErrorMetadata(error.code),
        'data-error-source': error.source,
        'data-error-stage': error.stage,
        'data-error-action': error.recommendedAction,
        'data-error-session-preserved': error.sessionPreserved === null
          ? ''
          : String(error.sessionPreserved),
      };
      Object.entries(values).forEach(([name, value]) => {
        if (value) element.setAttribute(name, value);
      });
    }

    function renderDashboardError(element, error) {
      if (!element) return;
      const message = error instanceof PanelApiError
        ? error.message
        : 'Сервис временно недоступен.';
      element.textContent = 'Не удалось загрузить сводку: ' + message;
      setDashboardErrorMetadata(element, error);
      element.removeAttribute('data-error-action-invoked');
      const action = error instanceof PanelApiError
        ? error.recommendedAction
        : 'REVIEW_OPERATION';
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'small';
      button.dataset.action = 'error-action';
      button.dataset.errorAction = normalizedErrorAction(action);
      button.textContent = ERROR_ACTION_LABELS[button.dataset.errorAction];
      button.setAttribute('aria-label', 'Действие: ' + button.textContent);
      element.append(document.createTextNode(' '), button);
    }

    async function runPanelErrorAction(action, button) {
      const normalized = normalizedErrorAction(action);
      const container = button && (button.closest('[data-error-code]') || button.parentElement);
      const markInvoked = () => {
        if (button) button.dataset.errorActionInvoked = normalized;
        if (container) container.setAttribute('data-error-action-invoked', normalized);
        document.body.setAttribute('data-last-error-action', normalized);
      };
      markInvoked();

      if (normalized === 'AUTHENTICATE'
          || normalized === 'REAUTHENTICATE'
          || normalized === 'REVIEW_SESSION') {
        markInvoked();
        location.href = '/auth.html';
        return;
      }

      try {
        const groupActions = new Set([
          'REVIEW_PROFILE', 'REVIEW_OBJECT', 'SELECT_GROUP', 'REVIEW_DESTINATION',
          'REVIEW_MEMBERSHIP', 'REVIEW_CONFLICT', 'CONFIGURE_ROUTE', 'REVIEW_ROUTE',
          'ENABLE_ROUTE', 'RELOAD_ROUTE', 'REVIEW_PROXY', 'REVIEW_NETWORK',
          'REVIEW_RUNTIME', 'RETRY_LOGIN', 'RESTART_LOGIN', 'REQUEST_NEW_CODE',
          'REVIEW_REGISTRATION', 'REVIEW_CLEANUP', 'REVIEW_MIGRATION',
        ]);
        if (groupActions.has(normalized)) {
          switchTab('groups');
          await loadGroups(true);
          markInvoked();
          return;
        }
        const messageActions = new Set(['REVIEW_LIBRARY', 'REVIEW_IMPORT']);
        if (messageActions.has(normalized)) {
          switchTab('messages');
          await loadMessages();
          markInvoked();
          return;
        }
        const settingActions = new Set([
          'UNLOCK_VAULT', 'REVIEW_VAULT', 'REVIEW_STORAGE', 'REVIEW_POLICY',
          'RELOAD_SETTINGS',
        ]);
        if (settingActions.has(normalized)) {
          switchTab('settings');
          await loadSettings();
          markInvoked();
          return;
        }
        if (normalized === 'RECONCILE_BEFORE_RETRY' || normalized === 'PERSIST_ACK') {
          switchTab('campaign');
          await loadSendLog(0);
          markInvoked();
          return;
        }
        switchTab('campaign');
        if (normalized === 'STOP_OPERATION' || normalized === 'STOP_TENANT') {
          const stop = document.getElementById('btnStop');
          if (stop) stop.focus();
          toast('Проверьте состояние и нажмите «Стоп» явно.', 'info');
        } else if (normalized === 'WAIT_RETRY' || normalized === 'WAIT_OPERATION') {
          toast('Автоматический повтор не выполняется. Проверьте состояние операции.', 'info');
        } else {
          toast('Проверьте состояние операции перед продолжением.', 'info');
        }
        markInvoked();
      } catch (actionError) {
        markInvoked();
        toast(actionError instanceof PanelApiError
          ? actionError.message
          : 'Не удалось открыть рекомендуемый раздел.', 'error');
      }
    }

    function markUiReady() {
      document.body.classList.add('ui-ready');
    }

    function mountCampaignLayout(simpleCampaign) {
      const userContent = document.getElementById('userSummaryContent');
      const adminSlot = document.getElementById('adminSummarySlot');
      const dashStats = document.getElementById('dashStats');
      const dashError = document.getElementById('dashSummaryError');
      const dashCardsPanel = document.getElementById('dashCardsPanel');
      // User summary: stats tiles only. Profile cards stay admin-only.
      if (dashStats && userContent && adminSlot) {
        const statsTarget = simpleCampaign ? userContent : adminSlot;
        if (dashStats.parentElement !== statsTarget) statsTarget.appendChild(dashStats);
      }
      if (dashError && userContent && adminSlot) {
        const errorTarget = simpleCampaign ? userContent : adminSlot;
        const before = dashStats && dashStats.parentElement === errorTarget
          ? dashStats
          : errorTarget.firstChild;
        if (dashError.parentElement !== errorTarget || dashError.nextSibling !== before) {
          errorTarget.insertBefore(dashError, before);
        }
      }
      if (dashCardsPanel && adminSlot && dashCardsPanel.parentElement !== adminSlot) {
        adminSlot.appendChild(dashCardsPanel);
      }
      const runBadge = document.getElementById('runBadge');
      const runBadgeSlot = document.getElementById('runBadgeSlot');
      const headerMeta = document.querySelector('.header-meta');
      const subBadge = document.getElementById('subscriptionBadge');
      if (runBadge && headerMeta) {
        if (simpleCampaign && runBadgeSlot) {
          if (runBadge.parentElement !== runBadgeSlot) runBadgeSlot.appendChild(runBadge);
        } else if (runBadge.parentElement !== headerMeta) {
          if (subBadge) subBadge.insertAdjacentElement('afterend', runBadge);
          else headerMeta.insertBefore(runBadge, headerMeta.firstChild);
        }
      }
      document.body.classList.toggle('simple-campaign', !!simpleCampaign);
      if (simpleCampaign && document.getElementById('campaign').classList.contains('active')) {
        loadDashboard().catch(e => toast(e.message, 'error'));
      }
    }

    function applyServerRoleUI() {
      const isUser = isUserRole();
      const simpleCampaign = isSimpleCampaignView();
      mountCampaignLayout(simpleCampaign);
      document.body.classList.toggle(
        'campaign-attention-enabled',
        _serverMode && (isUser || isAdminImpersonating()),
      );
      document.querySelectorAll('nav button[data-tab="messages"], nav button[data-tab="settings"]').forEach(el => {
        el.style.display = isUser ? 'none' : '';
      });
      document.querySelectorAll('.campaign-admin-only').forEach(el => {
        el.style.display = simpleCampaign ? 'none' : '';
      });
      document.querySelectorAll('.settings-admin-only').forEach(el => {
        el.style.display = isUser ? 'none' : '';
      });
      document.querySelectorAll('.header-user-hide').forEach(el => {
        el.style.display = isUser ? 'none' : '';
      });
      const logoutBtn = document.getElementById('btnLogout');
      if (logoutBtn) logoutBtn.style.display = isUser ? '' : 'none';
      const userHint = document.getElementById('campaignUserHint');
      const adminHint = document.getElementById('campaignAdminHint');
      if (userHint) {
        if (simpleCampaign && isUser && !_subscriptionActive) {
          userHint.style.display = '';
          userHint.textContent = 'Обратитесь к администратору';
        } else if (simpleCampaign) {
          userHint.style.display = '';
          userHint.textContent = 'Запустите один раз — рассылка продолжится автоматически';
        } else {
          userHint.style.display = 'none';
        }
      }
      if (adminHint) adminHint.style.display = simpleCampaign ? 'none' : '';
      const banner = document.getElementById('serverBanner');
      if (banner) {
        if (!_serverMode) {
          banner.style.display = 'none';
        } else {
          banner.style.display = 'block';
          const imp = sessionStorage.getItem('maxImpersonating');
          if ((imp || _adminImpersonating) && _userRole === 'admin') {
            banner.className = 'hint';
            const name = imp || 'учреждение';
            banner.textContent = 'Режим админа: кабинет «' + name + '» · ';
            banner.innerHTML += '<button type="button" data-action="exit-impersonation" style="color:var(--accent);background:none;border:none;cursor:pointer;font:inherit;padding:0">← админ-панель</button>';
          } else if (isUser && !_subscriptionActive) {
            banner.className = 'hint';
            banner.style.color = 'var(--danger)';
            const expiredLabel = _subscriptionExpiresAt
              ? ' (истекла ' + formatSubscriptionDate(_subscriptionExpiresAt) + ')'
              : '';
            banner.textContent = 'Подписка не активна' + expiredLabel + '. Обратитесь к администратору для доступа к рассылке.';
          } else if (isUser) {
            banner.style.color = '';
            banner.textContent = 'Личный кабинет — группы, аккаунты, рассылка';
          } else {
            banner.style.display = 'none';
          }
        }
      }
      applySubscriptionBadge();
      applyCampaignButtonState(_lastStatus);
    }

    async function initServerMode() {
      const h = await fetch('/api/health').then(r => r.json()).catch(() => ({}));
      if (!h.server_mode) return;
      _serverMode = true;
      await tryRestoreSession();
      try {
        const me = await api('/auth/me');
        _userRole = me.role;
        _adminImpersonating = !!me.impersonating;
        _subscriptionActive = !!(me.subscription && me.subscription.active);
        _subscriptionExpiresAt = me.subscription && me.subscription.expires_at
          ? me.subscription.expires_at
          : null;
        if (me.impersonating && me.institution_name) {
          sessionStorage.setItem('maxImpersonating', me.institution_name);
        }
        if (me.role === 'admin' && !me.impersonating) {
          location.href = '/admin.html';
          return;
        }
        applyServerRoleUI();
      } catch (e) {
        location.href = '/auth.html';
      }
    }

    function applyVaultBadge(vs) {
      const el = document.getElementById('vaultBadge');
      if (!vs || !vs.unlocked) { el.textContent = 'хранилище'; el.className = 'badge warn'; return; }
      el.textContent = 'хранилище ОК';
      el.className = 'badge run';
    }

    async function initVaultUI() {
      const vs = await api('/vault/status');
      applyVaultBadge(vs);
      return vs;
    }

    document.querySelectorAll('nav button[role="tab"]').forEach(b => {
      b.addEventListener('click', () => {
        switchTab(b.dataset.tab);
      });
    });
    document.querySelector('nav[role="tablist"]').addEventListener('keydown', (e) => {
      const tabs = [...document.querySelectorAll('nav button[role="tab"]')]
        .filter(t => t.style.display !== 'none');
      const i = tabs.indexOf(document.activeElement);
      if (i < 0) return;
      let next = -1;
      if (e.key === 'ArrowRight') next = (i + 1) % tabs.length;
      else if (e.key === 'ArrowLeft') next = (i - 1 + tabs.length) % tabs.length;
      else if (e.key === 'Home') next = 0;
      else if (e.key === 'End') next = tabs.length - 1;
      if (next < 0) return;
      e.preventDefault();
      tabs[next].focus();
      switchTab(tabs[next].dataset.tab);
    });

    function parseDataId(raw) {
      if (raw == null || raw === '') return null;
      const n = parseInt(raw, 10);
      return Number.isNaN(n) ? null : n;
    }

    document.getElementById('btnLogout').addEventListener('click', logoutUser);
    document.getElementById('dashFilter').addEventListener('change', () => loadDashboard());
    document.getElementById('attentionMore').addEventListener('click', function() {
      const next = _attentionOffset + 10;
      this.disabled = true;
      loadAttention(next).catch(() => {}).finally(() => { this.disabled = false; });
    });
    document.getElementById('btnStart').addEventListener('click', function() { withLoading(this, startCampaign); });
    document.getElementById('btnCampaignPreview').addEventListener('click', function() { withLoading(this, previewCampaign); });
    document.getElementById('btnPause').addEventListener('click', function() { withLoading(this, pauseCampaign); });
    document.getElementById('btnStop').addEventListener('click', function() { withLoading(this, stopCampaign); });
    document.getElementById('btnReset').addEventListener('click', function() { withLoading(this, resetCampaign); });
    document.getElementById('btnTestSend').addEventListener('click', function() { withLoading(this, testSend); });
    document.getElementById('btnCampaignCommandReconcile').addEventListener('click', function() {
      withLoading(this, reconcileCampaignCommand);
    });
    document.getElementById('btnSchedule').addEventListener('click', function() { withLoading(this, scheduleCampaign); });
    document.getElementById('btnCancelSchedule').addEventListener('click', function() { withLoading(this, cancelSchedule); });
    document.getElementById('sendLogQ').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') loadSendLog(0);
    });
    document.getElementById('sendLogStatus').addEventListener('change', () => loadSendLog(0));
    document.getElementById('msgFile').addEventListener('change', onMsgFileChange);
    document.getElementById('btnUploadMessages').addEventListener('click', function() {
      withLoading(this, uploadMessages).then(() => onMsgFileChange());
    });
    document.getElementById('groupName').addEventListener('input', updateCreateGroupBtn);
    document.getElementById('groupLink').addEventListener('input', updateCreateGroupBtn);
    document.getElementById('btnCreateGroup').addEventListener('click', function() { withLoading(this, addGroup); });
    document.getElementById('btnBackupNow').addEventListener('click', function() { withLoading(this, backupNow); });
    document.getElementById('btnSaveSettings').addEventListener('click', saveSettings);

    document.body.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-action]');
      if (!btn) return;
      const action = btn.dataset.action;
      const profileId = parseDataId(btn.dataset.profileId);
      const groupId = parseDataId(btn.dataset.groupId);
      if (action === 'error-action') {
        runPanelErrorAction(btn.dataset.errorAction, btn);
      } else if (action === 'exit-impersonation') {
        exitImpersonation();
      } else if (action === 'send-log-page') {
        loadSendLog(parseDataId(btn.dataset.offset) || 0);
      } else if (action === 'login-profile') {
        withLoading(btn, () => loginProfile(profileId, btn.dataset.fresh === '1', groupId));
      } else if (action === 'auth-diagnostic-preview') {
        withLoading(btn, () => showAuthDiagnostic(btn, profileId));
      } else if (action === 'auth-diagnostic-download') {
        withLoading(btn, () => downloadAuthDiagnostic(btn, profileId));
      } else if (action === 'reset-login') {
        resetLogin(profileId);
      } else if (action === 'remove-profile') {
        removeProfile(groupId, profileId);
      } else if (action === 'profile-page') {
        changeProfilePage(groupId, parseInt(btn.dataset.dir, 10));
      } else if (action === 'toggle-group') {
        toggleGroup(groupId);
      } else if (action === 'toggle-group-active') {
        toggleGroupActive(groupId, parseInt(btn.dataset.active, 10));
      } else if (action === 'delete-group') {
        deleteGroup(groupId);
      } else if (action === 'save-group-proxy') {
        saveGroupProxy(groupId);
      } else if (action === 'verify-group-destination') {
        withLoading(btn, () => verifyGroupDestination(groupId));
      } else if (action === 'login-from-phone') {
        withLoading(btn, () => loginFromPhone(groupId, true));
      } else if (action === 'import-csv') {
        document.getElementById('csvFile').click();
      }
    });

    window.addEventListener('hashchange', () => {
      const tab = tabFromHash();
      if (tab && isTabAccessible(tab)) switchTab(tab, { skipHash: true });
    });

    initAccessibleTips();

    const groupsSection = document.getElementById('groups');
    groupsSection.addEventListener('focusin', (e) => {
      if (e.target.matches('input, textarea') && e.target.closest('#groupsList')) {
        groupsRefreshPaused = true;
        focusedInputId = e.target.id;
      }
    });
    groupsSection.addEventListener('focusout', () => {
      setTimeout(() => {
        if (authModalOpen) return;
        const el = document.activeElement;
        if (!el || !groupsSection.contains(el) || !el.matches('input, textarea')) {
          groupsRefreshPaused = false;
        }
      }, 300);
    });
    groupsSection.addEventListener('input', (e) => {
      const t = e.target;
      if (t.id && (t.id.startsWith('phone-') || t.id.startsWith('label-'))) {
        draftInputs[t.id] = t.value;
      }
    });

    function sleep(ms) {
      return new Promise(r => setTimeout(r, ms));
    }

    function normalizePhone(phone) {
      phone = phone.trim().replace(/\s/g, '');
      if (phone.startsWith('8') && phone.length === 11) phone = '+7' + phone.slice(1);
      else if (phone.startsWith('7') && phone.length === 11) phone = '+' + phone;
      else if (!phone.startsWith('+')) phone = '+' + phone.replace(/^\+/, '');
      return phone;
    }

    function profileAuthActionPreference(element) {
      if (!(element instanceof HTMLElement) || !element.matches(
        '[data-action="reset-login"], [data-action="login-profile"]'
      )) return null;
      return {
        profileId: element.dataset.profileId || '',
        action: element.dataset.action || '',
        groupId: element.dataset.groupId || '',
        fresh: element.dataset.fresh || '',
      };
    }

    function focusProfileAuthAction(profileId, preferred = null) {
      const targets = [...document.querySelectorAll(
        '[data-action="reset-login"], [data-action="login-profile"]'
      )].filter(element => (
        element.dataset.profileId === String(profileId)
        && !element.disabled
        && !element.closest('details:not([open])')
      ));
      const target = preferred
        ? targets.find(element => (
          element.dataset.action === preferred.action
          && element.dataset.groupId === preferred.groupId
          && element.dataset.fresh === preferred.fresh
        ))
        : null;
      const menu = [...document.querySelectorAll('details.profile-more')]
        .find(element => element.dataset.profileId === String(profileId));
      const groupTarget = preferred && preferred.groupId
        ? document.querySelector(`[data-action="toggle-group"][data-group-id="${preferred.groupId}"]`)
        : null;
      (target || targets[0] || menu?.querySelector('summary') || groupTarget)?.focus();
    }

    function showAuthModal(title, message, password = false, restoreFocus = null) {
      return new Promise(resolve => {
        authModalOpen = true;
        groupsRefreshPaused = true;
        const overlay = document.getElementById('authModal');
        const modal = overlay.querySelector('.modal');
        const input = document.getElementById('authModalInput');
        const previousFocus = document.activeElement;
        document.getElementById('authModalTitle').textContent = title;
        document.getElementById('authModalMsg').textContent = message;
        input.type = password ? 'password' : 'text';
        input.value = '';
        input.autocomplete = password ? 'current-password' : 'one-time-code';
        overlay.style.display = 'flex';
        input.focus();

        overlay.onkeydown = (e) => {
          if (e.key !== 'Tab') return;
          const focusable = getFocusableIn(modal);
          if (!focusable.length) return;
          const first = focusable[0];
          const last = focusable[focusable.length - 1];
          if (e.shiftKey) {
            if (document.activeElement === first) { e.preventDefault(); last.focus(); }
          } else if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        };

        const finish = (val) => {
          authModalOpen = false;
          groupsRefreshPaused = false;
          overlay.style.display = 'none';
          overlay.onkeydown = null;
          okBtn.onclick = null;
          cancelBtn.onclick = null;
          input.onkeydown = null;
          window.setTimeout(() => {
            if (
              previousFocus instanceof HTMLElement
              && previousFocus !== document.body
              && previousFocus.isConnected
              && !previousFocus.matches(':disabled')
            ) {
              previousFocus.focus();
            } else if (typeof restoreFocus === 'function') {
              restoreFocus();
            }
          }, 0);
          resolve(val);
        };

        const okBtn = document.getElementById('authModalOk');
        const cancelBtn = document.getElementById('authModalCancel');
        okBtn.onclick = () => {
          const v = input.value.trim();
          if (!v) { toast('Введите значение', 'error'); return; }
          finish(v);
        };
        cancelBtn.onclick = () => finish(null);
        input.onkeydown = (e) => {
          if (e.key === 'Enter') okBtn.click();
          if (e.key === 'Escape') cancelBtn.click();
        };
      });
    }

    async function findProfile(profileId) {
      return await api(`/profiles/${profileId}`);
    }

    function authRequestId(kind, profileId) {
      const suffix = (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function')
        ? globalThis.crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      return `${kind}-${profileId}-${suffix}`;
    }

    async function startLoginWatch(profileId, initialStep = 'connecting') {
      if (authWatchers.has(profileId)) return;
      authWatchers.add(profileId);
      let idlePolls = 0;
      const maxIdlePolls = 45;

      try {
        while (authWatchers.has(profileId)) {
          const p = await findProfile(profileId);
          if (!p) {
            toast('Профиль не найден', 'error');
            break;
          }

          if (p.auth_step === 'waiting_sms' && !authModalOpen) {
            const code = await showAuthModal(
              'SMS-код',
              `Введите код из SMS для ${p.phone}`,
              false,
              () => focusProfileAuthAction(profileId)
            );
            if (code === null) {
              await api(`/profiles/${profileId}/login/reset`, { method: 'POST' });
              break;
            }
            await api(`/profiles/${profileId}/sms`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                code,
                attempt_id: p.attempt_id,
                revision: p.revision,
                request_id: authRequestId('code', profileId),
              }),
            });
            loadGroups(true);
            await sleep(300);
            continue;
          }

          if (p.auth_step === 'waiting_cloud_password' && !authModalOpen) {
            const hint = p.auth_hint ? `\nПодсказка: ${p.auth_hint}` : '';
            const pwd = await showAuthModal(
              'Облачный пароль MAX',
              `Введите облачный пароль для ${p.phone}${hint}`,
              true,
              () => focusProfileAuthAction(profileId)
            );
            if (pwd === null) {
              await api(`/profiles/${profileId}/login/reset`, { method: 'POST' });
              break;
            }
            await api(`/profiles/${profileId}/password`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                code: pwd,
                attempt_id: p.attempt_id,
                revision: p.revision,
                request_id: authRequestId('password', profileId),
              }),
            });
            loadGroups(true);
            await sleep(300);
            continue;
          }

          if (p.status === 'active' && p.auth_step === 'idle') {
            toast('Аккаунт подключён', 'success');
            break;
          }

          const attemptRunning = [
            'connecting',
            'waiting_code',
            'verifying_code',
            'waiting_password',
            'verifying_password',
          ].includes(p.auth_stage);
          if (p.auth_step === 'error' || (p.status === 'needs_reauth' && !attemptRunning)) {
            if (p.last_error) toast(p.last_error, 'error');
            loadGroups(true);
            break;
          }

          if (['connecting', 'waiting_sms', 'verifying_sms', 'waiting_cloud_password', 'verifying_password'].includes(p.auth_step)) {
            idlePolls = 0;
            await sleep(400);
            continue;
          }

          if (p.auth_step === 'idle' && initialStep === 'connecting' && idlePolls < maxIdlePolls) {
            idlePolls++;
            await sleep(400);
            continue;
          }

          if (p.auth_step === 'idle' && p.status === 'pending') {
            toast('Вход не запустился. Попробуйте ещё раз.', 'error');
          }
          break;
        }
      } catch (e) {
        toast(e.message, 'error');
      } finally {
        authWatchers.delete(profileId);
        const active = document.activeElement;
        const preferred = profileAuthActionPreference(active);
        const restoreDefault = !preferred && (
          active === document.body
          || !active.isConnected
          || Boolean(active.closest('#authModal'))
        );
        loadGroups(true).then(() => {
          if (preferred && preferred.profileId === String(profileId)) {
            focusProfileAuthAction(profileId, preferred);
          }
          else if (restoreDefault) focusProfileAuthAction(profileId);
        });
        refreshCampaignOverview();
      }
    }

    async function refreshStatus() {
      const s = await api('/status');
      applyStatus(s);
    }

    function applyRunBadge(s) {
      const el = document.getElementById('runBadge');
      if (!el) return;
      const running = !!(s && s.running);
      const autoRun = !!(s && s.auto_run);
      const sendingActive = running || autoRun;
      if (isSimpleCampaignView()) {
        el.textContent = sendingActive ? 'Отправка: активна' : 'Отправка: остановлена';
        el.className = 'badge ' + (sendingActive ? 'run' : 'stop');
      } else {
        el.textContent = running ? 'идёт рассылка' : 'остановлено';
        el.className = 'badge ' + (running ? 'run' : 'stop');
      }
    }

    function applyStatus(s) {
      const signature = JSON.stringify({
        profiles: s.profiles || {},
        running: Boolean(s.running),
        auto_run: Boolean(s.auto_run),
        circuit_open: Number(s.circuit_open || 0),
        messages_count: Number(s.messages_count || 0),
      });
      const readinessChanged = _readinessStatusSignature !== null
        && signature !== _readinessStatusSignature;
      _readinessStatusSignature = signature;
      _lastStatus = s;
      const running = !!s.running;
      if (_wasRunning && !running) {
        maybeNotifyDone(s);
      }
      _wasRunning = running;
      applyRunBadge(s);
      applyVaultBadge(s.vault);
      const circuit = s.circuit_open ? ` · автопауза: ${s.circuit_open}` : '';
      document.getElementById('msgCount').textContent = 'Пул TXT: ' + s.messages_count + circuit;
      const el = document.getElementById('campaignLog');
      el.innerHTML = renderLogLines(s.log || []);
      el.scrollTop = el.scrollHeight;
      renderUserActivity(s.activity);
      if (document.getElementById('campaign').classList.contains('active') && !isUserRole()) {
        renderDashProgress(s);
      }
      applyCampaignButtonState(s);
      if (readinessChanged && _serverMode) {
        window.clearTimeout(_readinessRefreshTimer);
        _readinessRefreshTimer = window.setTimeout(() => {
          loadAttention(0).catch(() => {});
          loadCampaignPreview().catch(() => {});
        }, 250);
      }
    }

    function renderDashProgress(data) {
      const panel = document.getElementById('dashProgressPanel');
      if (!panel) return;
      if (isUserRole()) {
        panel.style.display = 'none';
        return;
      }
      const prog = (data && data.campaign_progress) || {};
      const running = !!(data && data.running);
      const autoRun = !!(data && data.auto_run);
      const statusEl = document.getElementById('dashProgressStatus');
      const bar = document.getElementById('dashProgressBar');
      const label = document.getElementById('dashProgressLabel');
      if (!prog.total_accounts || prog.total_accounts <= 0) {
        panel.style.display = 'none';
        return;
      }
      panel.style.display = '';
      const sent = prog.sent_this_week || 0;
      const total = prog.total_accounts || 0;
      const remaining = prog.remaining != null ? prog.remaining : Math.max(0, total - sent);
      const pct = Math.min(100, sent / total * 100);
      bar.style.width = pct.toFixed(1) + '%';
      label.textContent = `${sent}/${total} за неделю · сегодня назначено ${prog.scheduled_today || 0}`;
      if (statusEl) {
        if (running) statusEl.textContent = 'идёт рассылка';
        else if (autoRun) statusEl.textContent = 'активна · ждёт продолжения';
        else statusEl.textContent = 'остановлена';
      }
    }

    let _statusWs = null;
    let _statusWsRetry = 0;
    let _statusPollTimer = null;
    let _statusPollInFlight = false;
    let _statusPollPending = false;
    let _statusWsReconnectTimer = null;

    function stopStatusPoll() {
      if (_statusPollTimer) {
        clearTimeout(_statusPollTimer);
        _statusPollTimer = null;
      }
    }

    function stopStatusReconnect() {
      if (_statusWsReconnectTimer) {
        clearTimeout(_statusWsReconnectTimer);
        _statusWsReconnectTimer = null;
      }
    }

    function setLiveBadge(mode) {
      const el = document.getElementById('liveBadge');
      if (!el) return;
      if (mode === 'live') {
        el.className = 'badge live';
        el.textContent = 'онлайн';
        el.title = 'Статус по WebSocket';
      } else {
        el.className = 'badge poll';
        el.textContent = 'опрос';
        el.title = 'Резервный опрос';
      }
    }

    async function refreshStatusFallback() {
      if (_statusWs || document.visibilityState === 'hidden') return;
      if (_statusPollInFlight) {
        _statusPollPending = true;
        return;
      }
      _statusPollInFlight = true;
      try {
        await refreshStatus();
      } catch (_) {
        // Keep the last truthful snapshot while the transport is unavailable.
      } finally {
        _statusPollInFlight = false;
        if (_statusPollPending) {
          _statusPollPending = false;
          if (!_statusWs && document.visibilityState !== 'hidden') {
            refreshStatusFallback();
            return;
          }
        }
        if (!_statusWs && document.visibilityState !== 'hidden') startStatusPoll();
      }
    }

    function startStatusPoll() {
      if (_statusPollTimer || _statusPollInFlight || _statusWs || document.visibilityState === 'hidden') return;
      setLiveBadge('poll');
      _statusPollTimer = setTimeout(async () => {
        _statusPollTimer = null;
        await refreshStatusFallback();
      }, 5000);
    }

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') {
        stopStatusPoll();
        return;
      }
      if (!_statusWs) {
        // One explicit resync on return, then the normal single fallback timer.
        refreshStatusFallback();
        connectStatusWs();
      }
    });

    function connectStatusWs() {
      if (_statusWs && (_statusWs.readyState === WebSocket.OPEN || _statusWs.readyState === WebSocket.CONNECTING)) {
        return;
      }
      stopStatusReconnect();
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      let ws;
      try {
        ws = new WebSocket(`${proto}//${location.host}/ws/status`);
      } catch (_) {
        startStatusPoll();
        return;
      }
      _statusWs = ws;
      ws.onopen = () => {
        if (_statusWs !== ws) return;
        try {
          if (_serverMode) {
            ws.send(JSON.stringify({ type: 'auth' }));
          } else {
            ws.send(JSON.stringify({ type: 'auth', pin: getApiPin() || '' }));
          }
        } catch (_) {
          ws.close();
          return;
        }
        _statusWsRetry = 0;
        stopStatusPoll();
        setLiveBadge('live');
      };
      ws.onmessage = (ev) => {
        if (_statusWs !== ws) return;
        try {
          applyStatus(JSON.parse(ev.data));
        } catch (_) {}
      };
      ws.onclose = () => {
        if (_statusWs !== ws) return;
        _statusWs = null;
        startStatusPoll();
        const delay = Math.min(15000, 1000 * Math.pow(2, _statusWsRetry++));
        if (document.visibilityState !== 'hidden' && !_statusWsReconnectTimer) {
          _statusWsReconnectTimer = setTimeout(() => {
            _statusWsReconnectTimer = null;
            connectStatusWs();
          }, delay);
        }
      };
      ws.onerror = () => {
        try { ws.close(); } catch (_) {}
      };
    }

    function maybeNotifyDone(s) {
      if (!document.getElementById('notifyDone').checked) return;
      const prog = s.campaign_progress || {};
      const title = 'MAX Sender';
      const body = prog.total
        ? `Рассылка завершена: ${prog.sent}/${prog.total}`
        : 'Рассылка остановлена';
      if (!('Notification' in window)) return;
      if (Notification.permission === 'granted') {
        new Notification(title, { body });
      } else if (Notification.permission !== 'denied') {
        Notification.requestPermission().then(p => {
          if (p === 'granted') new Notification(title, { body });
        });
      }
    }

    async function loadSendLog(offset = 0) {
      sendLogOffset = offset;
      const q = encodeURIComponent((document.getElementById('sendLogQ') || {}).value || '');
      const st = encodeURIComponent((document.getElementById('sendLogStatus') || {}).value || '');
      const d = await api(`/send_log?offset=${offset}&limit=30&q=${q}&status=${st}`);
      const box = document.getElementById('sendLog');
      if (!d.items.length) {
        box.innerHTML = '<div class="empty-state" style="margin:0;border:none"><strong>Ничего не найдено</strong>Измените фильтр или дождитесь отправок</div>';
      } else {
        box.innerHTML = `<table class="data-table">
          <thead><tr><th>Время</th><th>Профиль</th><th>Группа</th><th>Статус</th><th>Ошибка</th></tr></thead>
          <tbody>${d.items.map(r => {
            const cls = r.status === 'sent' ? 'ok' : (r.status === 'failed' ? 'fail' : '');
            return `<tr class="${cls}">
              <td data-label="Время">${esc(r.sent_at || '')}</td>
              <td data-label="Профиль">#${r.profile_id} ${esc(r.phone || '')}</td>
              <td data-label="Группа">${esc(r.group_name || '?')}</td>
              <td data-label="Статус">${esc(sendStatusRu(r.status))}</td>
              <td data-label="Ошибка">${esc(r.error || '')}</td>
            </tr>`;
          }).join('')}</tbody></table>`;
      }
      const pages = Math.ceil(d.total / d.limit) || 1;
      const cur = Math.floor(d.offset / d.limit) + 1;
      document.getElementById('sendLogPager').innerHTML = d.total > d.limit
        ? `<button type="button" class="small" aria-label="Предыдущая страница" data-action="send-log-page" data-offset="${Math.max(0, offset - d.limit)}" ${offset <= 0 ? 'disabled' : ''}>←</button>
           <span class="hint">${cur}/${pages} · ${d.total}</span>
           <button type="button" class="small" aria-label="Следующая страница" data-action="send-log-page" data-offset="${offset + d.limit}" ${offset + d.limit >= d.total ? 'disabled' : ''}>→</button>`
        : (d.total ? `<span class="hint">${d.total} записей</span>` : '');
    }

    function renderDashStats(d) {
      const counts = (d && d.counts) || {};
      const el = document.getElementById('dashStats');
      if (!el) return;
      const basics = `
        <div class="dash-stat"><div class="n">${counts.active || 0}</div><div class="l">активны</div></div>
        <div class="dash-stat"><div class="n">${counts.pending || 0}</div><div class="l">ожидают входа</div></div>
        <div class="dash-stat"><div class="n">${counts.needs_reauth || 0}</div><div class="l">повторный вход</div></div>
        <div class="dash-stat"><div class="n">${counts.banned || 0}</div><div class="l">забанены</div></div>
      `;
      el.innerHTML = isUserRole() ? basics : `${basics}
        <div class="dash-stat"><div class="n">${(d && d.groups_count) || 0}</div><div class="l">групп</div></div>
        <div class="dash-stat"><div class="n">${(d && d.sent_today) || 0}</div><div class="l">успешно сегодня</div></div>
        <div class="dash-stat"><div class="n">${(d && d.failed_today) || 0}</div><div class="l">ошибок сегодня</div></div>
        <div class="dash-stat"><div class="n">${(d && d.circuit_open) || 0}</div><div class="l">в автопаузе</div></div>
      `;
    }

    async function loadDashboard() {
      const requestSequence = ++_dashboardLoadSequence;
      const errEl = document.getElementById('dashSummaryError');
      if (_serverMode) {
        loadAttention(0).catch(() => {});
        loadCampaignPreview().catch(() => {});
      }
      try {
        const d = await api('/dashboard');
        if (requestSequence !== _dashboardLoadSequence) return;
        if (errEl) errEl.style.display = 'none';
        if (errEl) setDashboardErrorMetadata(errEl, null);
        if (!isUserRole()) renderDashProgress(d);
        renderDashStats(d);
        if (isSimpleCampaignView()) return;
        const filter = (document.getElementById('dashFilter') || {}).value || '';
        let items = d.items || [];
        if (filter) items = items.filter(p => p.status === filter);
        const box = document.getElementById('dashCards');
        if (!box) return;
        if (!items.length) {
          box.innerHTML = '<div class="empty-state"><strong>Нет аккаунтов</strong>Добавьте профили во вкладке «Группы»</div>';
          return;
        }
        box.innerHTML = items.map(p => {
          const selectedGroupId = Number(p.primary_group_id) || 0;
          const needsGroupSelection = !selectedGroupId && Number(p.linked_group_count || 0) > 0;
          const scopeMessage = p.automation_scope_state === 'revoked'
            ? 'Автоматизация остановлена: согласие отозвано.'
            : needsGroupSelection
              ? 'Выберите рабочую группу во вкладке «Группы».'
              : '';
          return `
        <div class="dash-card">
          <div class="phone">${esc(p.phone)}${p.label ? ' · ' + esc(p.label) : ''}</div>
          <div class="meta">
            <span class="status-${p.status}">${esc(statusRu(p.status))}</span>
            ${p.circuit_open ? ' · <span class="auth-error">автопауза</span>' : ''}
            ${authLabel(p) ? ' · ' + esc(authLabel(p)) : ''}
          </div>
          <div class="meta">Отправка: ${p.send_weekday == null ? '—' : ['пн','вт','ср','чт','пт','сб','вс'][p.send_weekday]} · прокси: ${esc(p.proxy_label || 'не назначен')} · ${esc(p.group_names || '')}</div>
          ${scopeMessage ? `<div class="hint" role="status">${esc(scopeMessage)}</div>` : ''}
          ${p.last_error ? `<div class="auth-error">${esc(p.last_error)}</div>` : ''}
          <div class="row" style="margin-top:.5rem;margin-bottom:0">
            ${selectedGroupId && !['active', 'banned', 'disabled'].includes(p.status) ? `<button type="button" class="small" data-action="login-profile" data-profile-id="${p.id}" data-fresh="${isUserRole() ? 1 : 0}" data-group-id="${selectedGroupId}">Войти</button>` : ''}
          </div>
        </div>
      `;
        }).join('');
      } catch (e) {
        if (requestSequence !== _dashboardLoadSequence) return;
        if (errEl) {
          renderDashboardError(errEl, e);
          errEl.style.display = 'block';
        }
        throw e;
      }
    }

    function refreshCampaignOverview() {
      if (_serverMode) loadDashboard().catch(() => {});
    }

    const READINESS_REASON_TEXT = Object.freeze({
      library: 'Нет доступных сообщений. Обратитесь к администратору.',
      groups: 'Нет активной группы с подтверждённым назначением.',
      profiles: 'Нет активного авторизованного аккаунта для отправки.',
      recovery_hold_active: 'Внешние действия временно приостановлены.',
      max_authorization_missing: 'Администратору нужно проверить разрешение на внешние действия.',
      max_authorization_expired: 'Разрешение на внешние действия истекло. Обратитесь к администратору.',
      max_authorization_revoked: 'Разрешение на внешние действия отозвано. Обратитесь к администратору.',
      migration_review_required: 'Данные требуют проверки администратором.',
      daily_plan_window_shortfall: 'Для части аккаунтов не осталось времени в сегодняшнем расписании.',
      daily_plans_materialize_on_start: 'Расписание будет подготовлено при запуске.',
    });

    function readinessReason(code, warning = false) {
      const text = READINESS_REASON_TEXT[String(code || '')];
      if (text) return text;
      return warning
        ? 'Есть дополнительное условие, которое не мешает запуску.'
        : 'Есть условие, мешающее запуску. Обратитесь к администратору.';
    }

    function renderCampaignReadiness(report) {
      const state = document.getElementById('campaignReadinessState');
      const details = document.getElementById('campaignReadinessDetails');
      const blockers = document.getElementById('campaignReadinessBlockers');
      const selection = document.getElementById('campaignReadinessSelection');
      if (!state || !details || !blockers || !selection) return;
      const isReady = report && report.ok === true;
      _readinessKnown = true;
      _readinessReady = Boolean(isReady);
      _readinessRevision = report && typeof report.readiness_revision === 'string'
        ? report.readiness_revision
        : null;
      state.textContent = isReady ? 'Готово к запуску.' : 'Запуск пока недоступен. Устраните причины ниже.';
      state.className = 'hint ' + (isReady ? 'ok' : 'auth-error');
      const reasons = [
        ...((report && report.blockers) || []).map((item) => `Мешает запуску: ${readinessReason(item)}`),
        ...((report && report.warnings) || []).map((item) => `Важно: ${readinessReason(item, true)}`),
      ];
      blockers.innerHTML = reasons.map((item) => `<li>${esc(item)}</li>`).join('');
      const picked = report && report.selection ? report.selection : {};
      const groups = Array.isArray(picked.groups) ? picked.groups.length : 0;
      const profiles = Array.isArray(picked.profiles) ? picked.profiles.length : 0;
      const libraryCount = Number.isFinite(Number(picked.library_count))
        ? Number(picked.library_count)
        : 0;
      selection.textContent = `Групп: ${groups} · аккаунтов: ${profiles} · сообщений: ${libraryCount}`;
      details.style.display = '';
      updateCampaignStartGate();
    }

    async function loadCampaignPreview() {
      if (!_serverMode) return;
      const requestSequence = ++_readinessRequestSequence;
      _readinessKnown = false;
      updateCampaignStartGate();
      const state = document.getElementById('campaignReadinessState');
      if (state) state.textContent = 'Проверяем условия запуска…';
      try {
        const report = await api('/campaign/preview', { method: 'POST' });
        if (requestSequence !== _readinessRequestSequence) return null;
        renderCampaignReadiness(report);
        return report;
      } catch (error) {
        if (requestSequence === _readinessRequestSequence) {
          _readinessKnown = false;
          _readinessReady = false;
          _readinessRevision = null;
          if (state) {
            state.textContent = 'Не удалось проверить готовность. Запуск временно недоступен; попробуйте обновить проверку.';
            state.className = 'hint auth-error';
          }
          updateCampaignStartGate();
        }
        throw error;
      }
    }

    function attentionReason(item) {
      if (item.status === 'banned') return 'Аккаунт заблокирован. Рассылка остановлена для аккаунтов этого кабинета.';
      if (item.auth_step === 'waiting_sms') return 'Введите код из SMS, чтобы завершить вход.';
      if (item.auth_step === 'waiting_cloud_password') return 'Введите облачный пароль, чтобы завершить вход.';
      if (item.status === 'needs_reauth') return 'Требуется повторный вход в аккаунт.';
      if (item.status === 'pending') {
        return Number(item.linked_group_count || 0) > 0
          ? 'Аккаунт ещё не подключён.'
          : 'Сначала добавьте аккаунт в рабочую группу в разделе «Группы».';
      }
      if (item.status === 'disabled') return 'Аккаунт отключён администратором.';
      if (item.circuit_open) return 'Временная пауза после серии ошибок.';
      if (item.in_cooldown) return 'Аккаунт временно на паузе.';
      if (item.last_error) return item.last_error;
      return 'Проверьте состояние аккаунта в разделе «Группы».';
    }

    async function loadAttention(offset = 0) {
      const list = document.getElementById('attentionList');
      const count = document.getElementById('attentionCount');
      const more = document.getElementById('attentionMore');
      if (!list || !count || !more) return;
      const requestSequence = ++_attentionLoadSequence;
      const pageSize = 10;
      _attentionOffset = Math.max(0, offset);
      if (!_attentionOffset) list.innerHTML = '<p class="hint">Загружаем состояние аккаунтов…</p>';
      try {
        const data = await api(`/dashboard/attention?offset=${_attentionOffset}&limit=${pageSize}`);
        if (requestSequence !== _attentionLoadSequence) return;
        _attentionTotal = Number(data.total || 0);
        count.textContent = _attentionTotal ? `Всего: ${_attentionTotal}` : '';
        if (!_attentionTotal) {
          list.innerHTML = '<div class="attention-clear"><strong>Всё в порядке</strong><span>Сейчас нет аккаунтов, требующих внимания.</span></div>';
          more.style.display = 'none';
          return;
        }
        const items = Array.isArray(data.items) ? data.items : [];
        if (!_attentionOffset) list.innerHTML = '';
        list.insertAdjacentHTML('beforeend', items.map((item) => {
          const groupId = Number(item.primary_group_id) || 0;
          const inProgress = ['connecting', 'waiting_sms', 'verifying_sms', 'waiting_cloud_password', 'verifying_password'].includes(item.auth_step);
          const canLogin = item.status !== 'banned' && item.status !== 'disabled'
            && ['pending', 'needs_reauth'].includes(item.status) && !inProgress && groupId;
          const canDiagnose = item.status === 'banned' && Boolean(item.attempt_id);
          const label = item.label ? ` · ${esc(item.label)}` : '';
          const diagnostic = canDiagnose
            ? `<div class="auth-diagnostic" data-auth-diagnostic-host data-profile-id="${Number(item.id)}" data-attempt-id="${escAttr(item.attempt_id)}"><button type="button" class="small" data-action="auth-diagnostic-preview" data-profile-id="${Number(item.id)}">Безопасная диагностика</button></div>`
            : '';
          return `<article class="attention-item" data-profile-id="${Number(item.id)}">
            <div class="attention-copy">
              <div class="attention-title"><strong>${esc(item.phone)}${label}</strong><span class="status-${esc(item.status)}">${esc(statusRu(item.status))}</span></div>
              <p>${esc(attentionReason(item))}</p>
              ${inProgress ? `<span class="hint">${esc(authLabel(item).replace(/^→ /, ''))}</span>` : ''}
            </div>
            ${canLogin ? `<button type="button" class="small" data-action="login-profile" data-profile-id="${Number(item.id)}" data-fresh="1" data-group-id="${groupId}">Войти</button>` : diagnostic}
          </article>`;
        }).join(''));
        const loaded = _attentionOffset + items.length;
        more.style.display = loaded < _attentionTotal ? '' : 'none';
        more.textContent = `Показать ещё (${Math.max(0, _attentionTotal - loaded)})`;
      } catch (error) {
        if (requestSequence !== _attentionLoadSequence) return;
        list.innerHTML = '<p class="hint" role="status">Не удалось загрузить состояние аккаунтов. Обновите страницу или проверьте раздел «Группы».</p>';
        count.textContent = '';
        more.style.display = 'none';
        throw error;
      }
    }

    async function startCampaign() {
      try {
        if (isUserRole() && !_subscriptionActive) {
          toast('Нет активной подписки. Обратитесь к администратору.', 'error');
          return;
        }
        if (isUserRole() && (!_readinessKnown || !_readinessReady)) {
          toast('Сначала устраните причины в блоке «Готовность к запуску».', 'error');
          if (!_readinessKnown) loadCampaignPreview().catch(() => {});
          return;
        }
        if (!isSimpleCampaignView()) {
          const s = await api('/status');
          const prog = s.campaign_progress || {};
          const activeCount = (s.profiles && s.profiles.active) || 0;
          const msg = [
            `Правило: одно сообщение на аккаунт за неделю`,
            `Отправлено на этой неделе: ${prog.sent_this_week || 0}/${prog.total_accounts || 0}`,
            `Сегодня назначено: ${prog.scheduled_today || 0}`,
            `Активных профилей: ${activeCount}`,
          ].join('\n');
          if (!confirm(`Запустить рассылку?\n\n${msg}`)) return;
        } else if (!confirm('Запустить рассылку?\n\nСистема будет работать автоматически каждый день, пока вы не нажмёте «Стоп».')) {
          return;
        }
        const options = { method: 'POST' };
        if (_readinessRevision) {
          options.headers = { 'Content-Type': 'application/json' };
          options.body = JSON.stringify({ readiness_revision: _readinessRevision });
        }
        const result = await sendCampaignCommand('start', '/campaign/start', options);
        if (result && result.reconciled) {
          if (result.known) _readinessRevision = null;
          refreshStatus();
          return;
        }
        _readinessRevision = null;
        refreshStatus();
        loadCampaignPreview().catch(() => {});
        toast('Рассылка запущена', 'success');
      } catch (e) {
        if (e && e.code === 'PREVIEW_STALE') {
          _readinessRevision = null;
          _readinessKnown = false;
          _readinessReady = false;
          const state = document.getElementById('campaignReadinessState');
          if (state) state.textContent = 'Предпросмотр устарел. Проверьте готовность ещё раз.';
          updateCampaignStartGate();
          loadCampaignPreview().catch(() => {});
        }
        const msg = e.message || '';
        if (isUserRole() && /загрузите файл сообщений/i.test(msg)) {
          toast('Нет файла сообщений. Обратитесь к администратору.', 'error');
        } else {
          toast(msg || 'Ошибка', 'error');
        }
      }
    }

    function pendingCampaignCommand() {
      let raw = '';
      try { raw = sessionStorage.getItem(CAMPAIGN_COMMAND_STORAGE_KEY) || ''; } catch (_) {}
      if (!raw) return null;
      try {
        const value = JSON.parse(raw);
        if (value && ['start', 'stop', 'pause', 'test'].includes(value.command)
            && typeof value.requestId === 'string'
            && /^campaign-[a-z]+-[A-Za-z0-9-]{16,64}$/.test(value.requestId)) {
          return value;
        }
      } catch (_) {}
      return { command: 'unknown', requestId: '' };
    }

    function storePendingCampaignCommand(command, requestId) {
      try {
        sessionStorage.setItem(CAMPAIGN_COMMAND_STORAGE_KEY, JSON.stringify({ command, requestId }));
        return true;
      } catch (_) {
        return false;
      }
    }

    function renderCampaignCommandRecovery(pending, status) {
      const panel = document.getElementById('campaignCommandRecovery');
      const message = document.getElementById('campaignCommandRecoveryMessage');
      const reconcile = document.getElementById('btnCampaignCommandReconcile');
      if (!panel || !message || !reconcile) return;
      if (!pending) {
        panel.style.display = 'none';
        return;
      }
      const known = Boolean(status && status.known === true);
      const command = CAMPAIGN_COMMAND_LABELS[pending.command] || 'Команда';
      const state = known && typeof status.state === 'string' ? status.state : 'unknown';
      message.textContent = known
        ? `${command}: состояние команды — ${state}.`
        : 'Результат команды пока не подтверждён. Не отправляйте её повторно; проверьте состояние позже.';
      panel.style.display = 'block';
      reconcile.style.display = !known || CAMPAIGN_COMMAND_PENDING_STATES.has(state) ? '' : 'none';
    }

    function campaignCommandStatusMessage(command, status) {
      if (status && status.known === false && status.state === 'not_found') {
        return 'Сервер не принял команду. Её можно отправить заново.';
      }
      if (!status || status.known !== true) {
        return 'Результат команды не подтверждён. Команда не повторялась; проверьте состояние позже.';
      }
      const label = CAMPAIGN_COMMAND_LABELS[command] || 'Команда';
      return `${label}: состояние команды — ${status.state}.`;
    }

    async function reconcilePendingCampaignCommand({ notify = false } = {}) {
      const pending = pendingCampaignCommand();
      if (!pending) {
        renderCampaignCommandRecovery(null, null);
        return null;
      }
      let status = { known: false, state: 'unknown' };
      if (pending.requestId) {
        try {
          const query = new URLSearchParams({
            command: pending.command,
            request_id: pending.requestId,
          });
          status = await api(`/campaign/command-status?${query.toString()}`);
        } catch (_) {
          status = { known: false, state: 'unknown' };
        }
      }
      const known = Boolean(status && status.known === true);
      const notFound = Boolean(status && status.known === false && status.state === 'not_found');
      if (known && !CAMPAIGN_COMMAND_PENDING_STATES.has(status.state)) {
        try { sessionStorage.removeItem(CAMPAIGN_COMMAND_STORAGE_KEY); } catch (_) {}
      }
      if (notFound) {
        try { sessionStorage.removeItem(CAMPAIGN_COMMAND_STORAGE_KEY); } catch (_) {}
      }
      renderCampaignCommandRecovery(notFound ? null : pending, status);
      if (notify) {
        toast(campaignCommandStatusMessage(pending.command, status), known ? 'info' : 'error');
      }
      return { ...(status || {}), reconciled: true };
    }

    async function sendCampaignCommand(command, path, options = {}) {
      const existing = pendingCampaignCommand();
      if (existing) {
        const status = await reconcilePendingCampaignCommand({ notify: true });
        return status || { known: false, reconciled: true };
      }
      const suffix = globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function'
        ? globalThis.crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const requestId = `campaign-${command}-${suffix}`;
      const pending = { command, requestId };
      if (!storePendingCampaignCommand(command, requestId)) {
        renderCampaignCommandRecovery(pending, { known: false, state: 'unknown' });
        toast('Не удалось сохранить идентификатор команды. Команда не отправлена.', 'error');
        return { known: false, reconciled: true };
      }
      renderCampaignCommandRecovery(pending, { known: false, state: 'unknown' });
      try {
        const result = await api(path, {
          ...options,
          headers: { ...(options.headers || {}), 'X-Request-ID': requestId },
        });
        try { sessionStorage.removeItem(CAMPAIGN_COMMAND_STORAGE_KEY); } catch (_) {}
        renderCampaignCommandRecovery(null, null);
        return result;
      } catch (error) {
        if (error instanceof PanelApiError && error.status >= 400 && error.status < 500) {
          const status = await reconcilePendingCampaignCommand();
          if (status && status.known === false && status.state === 'not_found') {
            throw error;
          }
          toast(
            campaignCommandStatusMessage(command, status),
            status && status.known === true ? 'info' : 'error',
          );
          return status || { known: false, reconciled: true };
        }
        const status = await reconcilePendingCampaignCommand({ notify: true });
        return status || { known: false, reconciled: true };
      }
    }

    async function reconcileCampaignCommand() {
      await reconcilePendingCampaignCommand({ notify: true });
    }

    async function previewCampaign() {
      const report = await loadCampaignPreview();
      if (!report) return;
      toast(report.ok ? 'Готовность подтверждена' : 'Есть блокирующие условия', report.ok ? 'success' : 'info');
    }

    async function pauseCampaign() {
      try {
        const result = await sendCampaignCommand('pause', '/campaign/pause', { method: 'POST' });
        if (result && result.reconciled) return;
        refreshStatus();
        toast('Рассылка на паузе', 'success');
      } catch (e) {
        toast(e.message, 'error');
      }
    }
    async function stopCampaign() {
      try {
        if (!confirm('Остановить рассылку?\n\nАвтозапуск будет выключен, пока вы снова не нажмёте «Старт».')) return;
        const result = await sendCampaignCommand('stop', '/campaign/stop', { method: 'POST' });
        if (result && result.reconciled) return;
        refreshStatus();
        toast('Рассылка остановлена', 'success');
      } catch (e) {
        toast(e.message, 'error');
      }
    }
    async function resetCampaign() {
      if (!confirm('Сбросить прогресс и начать с первого сообщения?')) return;
      try {
        await api('/campaign/reset', { method: 'POST' });
        refreshStatus();
        toast('Прогресс сброшен', 'success');
      } catch (e) {
        toast(e.message, 'error');
      }
    }

    async function testSend() {
      try {
        const r = await sendCampaignCommand('test', '/campaign/test', { method: 'POST' });
        if (r && r.reconciled) return;
        toast(`Тест успешен: ${r.phone} → #${r.group_id}`, 'success');
        refreshStatus();
        loadSendLog(0);
      } catch (e) {
        toast(e.message, 'error');
      }
    }

    async function scheduleCampaign() {
      const local = document.getElementById('scheduleAt').value;
      if (!local) return toast('Укажите дату/время', 'error');
      const start_at = new Date(local).toISOString();
      try {
        const r = await api('/campaign/schedule', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ start_at }),
        });
        toast(`Запланировано: ${r.start_at}`, 'success');
        loadScheduleHint();
      } catch (e) {
        toast(e.message, 'error');
      }
    }

    async function cancelSchedule() {
      try {
        await api('/campaign/schedule', { method: 'DELETE' });
        toast('Расписание отменено', 'success');
        loadScheduleHint();
      } catch (e) {
        toast(e.message, 'error');
      }
    }

    async function loadScheduleHint() {
      try {
        const s = await api('/campaign/schedule');
        const el = document.getElementById('scheduleHint');
        if (s.enabled && s.start_at) {
          el.textContent = `План: ${s.start_at}`;
        } else {
          el.textContent = 'Нет расписания';
        }
      } catch (_) {}
    }

    async function loadCampaigns() {
      try {
        const d = await api('/campaigns?limit=30');
        const box = document.getElementById('campaignsHistory');
        if (!d.items.length) {
          box.innerHTML = '<div class="empty-state" style="margin:0;border:none"><strong>Кампаний пока нет</strong></div>';
          return;
        }
        box.innerHTML = `<table class="data-table">
          <thead><tr><th>ID</th><th>Статус</th><th>Старт</th><th>Финиш</th><th>Успех/Ошибки</th><th>Причина</th></tr></thead>
          <tbody>${d.items.map(c => `
            <tr class="${c.status === 'completed' ? 'ok' : (c.status === 'stopped' || c.status === 'paused' ? '' : '')}">
              <td data-label="ID">#${c.id}</td>
              <td data-label="Статус">${esc(campaignStatusRu(c.status))}</td>
              <td data-label="Старт">${esc(c.started_at || '')}</td>
              <td data-label="Финиш">${esc(c.finished_at || '—')}</td>
              <td data-label="Успех/Ошибки">${c.messages_sent || 0}/${c.messages_failed || 0} · всего ${c.messages_total || 0}</td>
              <td data-label="Причина">${esc((c.reason || '').slice(0, 80))}</td>
            </tr>`).join('')}
          </tbody></table>`;
      } catch (_) {}
    }

    async function backupNow() {
      try {
        const r = await api('/backup', { method: 'POST' });
        toast(`Резервная копия: ${r.file}`, 'success');
        loadBackupHint();
      } catch (e) {
        toast(e.message, 'error');
      }
    }

    async function loadBackupHint() {
      try {
        const d = await api('/backups');
        const el = document.getElementById('backupHint');
        if (!d.items.length) el.textContent = 'Бэкапов нет';
        else el.textContent = `Последний: ${d.items[0].file}`;
      } catch (_) {}
    }

    async function loadMessages() {
      const d = await api('/messages');
      document.getElementById('msgMeta').textContent = d.count
        ? `Загружено: ${d.count} · ${d.meta.loaded_at || ''}`
        : 'Файл не загружен';
      document.getElementById('msgPreview').innerHTML = d.messages.map(m => `<li>${esc(m)}</li>`).join('');
      document.getElementById('msgEmpty').style.display = d.count ? 'none' : 'block';
      document.getElementById('msgPreview').style.display = d.count ? 'block' : 'none';
    }
    async function uploadMessagesFile(file, { skipConfirm = false } = {}) {
      if (!file) throw new Error('Выберите файл');
      if (!skipConfirm && !confirm('Заменить текущие сообщения?')) return;
      const fd = new FormData();
      fd.append('file', file);
      const r = await api('/messages/upload', { method: 'POST', body: fd });
      const n = r && r.count != null ? r.count : 0;
      toast('Загружено ' + n + ' сообщений', 'success');
      loadMessages();
    }

    function formatFileSize(n) {
      if (n < 1024) return n + ' Б';
      if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' КБ';
      return (n / (1024 * 1024)).toFixed(1) + ' МБ';
    }

    function onMsgFileChange() {
      const input = document.getElementById('msgFile');
      const status = document.getElementById('msgFileStatus');
      const btn = document.getElementById('btnUploadMessages');
      const f = input && input.files && input.files[0];
      if (!f) {
        if (status) status.textContent = 'Файл не выбран';
        if (btn) btn.disabled = true;
        return;
      }
      if (status) status.textContent = f.name + ' · ' + formatFileSize(f.size);
      if (btn) btn.disabled = false;
    }

    async function uploadMessages() {
      const f = document.getElementById('msgFile').files[0];
      await uploadMessagesFile(f);
      const input = document.getElementById('msgFile');
      if (input) input.value = '';
    }


    function statusRu(s) {
      return ({
        active: 'активен',
        pending: 'ожидает входа',
        needs_reauth: 'нужен повторный вход',
        disabled: 'отключён',
        banned: 'забанен',
      })[s] || s || '';
    }

    function sendStatusRu(s) {
      return ({ sent: 'отправлено', failed: 'ошибка' })[s] || s || '';
    }

    function campaignStatusRu(s) {
      return ({
        running: 'идёт',
        completed: 'завершена',
        stopped: 'остановлена',
        paused: 'пауза',
        failed: 'ошибка',
      })[s] || s || '';
    }

    function authLabel(p) {
      const map = {
        connecting: 'Подключение…',
        waiting_sms: '→ введите SMS-код',
        verifying_sms: 'Проверка SMS…',
        waiting_cloud_password: '→ введите облачный пароль',
        verifying_password: 'Проверка пароля…',
        error: 'Ошибка входа',
        idle: '',
      };
      return map[p.auth_step] || '';
    }

    function phoneBadges(p) {
      const badges = [];
      if (p.circuit_open || p.in_cooldown) {
        const until = (p.cooldown_until || '').slice(0, 16);
        const reason = p.circuit_open ? 'Пауза после серии ошибок' : 'Пауза по таймеру';
        badges.push(['Временная пауза', p.circuit_open ? 'danger' : 'warn', until ? `${reason} · до ${until}` : reason]);
      }
      return `<span class="phone-badges">${badges.map(([label, kind, tip]) =>
        `<span class="phone-badge ${kind}" title="${esc(tip || label)}">${esc(label)}</span>`
      ).join('')}</span>`;
    }

    function profileActions(p, groupId) {
      const busy = ['connecting', 'waiting_sms', 'verifying_sms', 'waiting_cloud_password', 'verifying_password'].includes(p.auth_step);
      const canLogin = !busy && !['active', 'disabled', 'banned'].includes(p.status);
      const secondary = [
        (!isUserRole() && p.status !== 'banned' ? `<button type="button" class="small" data-action="login-profile" data-profile-id="${p.id}" data-fresh="1" data-group-id="${groupId}" ${busy ? 'disabled' : ''}>Повторить вход</button>` : ''),
        (isUserRole() && p.attempt_id ? `<div class="auth-diagnostic" data-auth-diagnostic-host data-profile-id="${p.id}" data-attempt-id="${esc(p.attempt_id)}"><button type="button" class="small" data-action="auth-diagnostic-preview" data-profile-id="${p.id}">Диагностика входа</button></div>` : ''),
        (busy ? `<button type="button" class="small" data-action="reset-login" data-profile-id="${p.id}">Отменить вход</button>` : ''),
        (!isUserRole() || p.status !== 'banned' ? `<button type="button" class="small danger" data-action="remove-profile" data-group-id="${groupId}" data-profile-id="${p.id}">Удалить</button>` : ''),
      ].filter(Boolean).join('');
      return `${canLogin ? `<button type="button" class="small" data-action="login-profile" data-profile-id="${p.id}" data-fresh="${isUserRole() ? 1 : 0}" data-group-id="${groupId}">Войти</button>` : ''}
        ${busy ? '<span class="hint">Вход выполняется</span>' : ''}
        ${secondary ? `<details class="action-menu profile-more" data-profile-id="${p.id}"><summary>Ещё</summary><div>${secondary}</div></details>` : ''}`;
    }

    async function showAuthDiagnostic(button, profileId) {
      const host = button.closest('[data-auth-diagnostic-host]');
      const attemptId = host?.dataset.attemptId || '';
      if (!host || !attemptId || !Number.isInteger(profileId) || profileId < 1) {
        throw new Error('Текущая попытка входа недоступна');
      }
      const result = await api(`/profiles/${profileId}/auth-attempts/${encodeURIComponent(attemptId)}/diagnostic`);
      let preview = host.querySelector('pre');
      if (!preview) {
        preview = document.createElement('pre');
        preview.className = 'auth-diagnostic-preview';
        preview.setAttribute('aria-label', 'Предпросмотр безопасной диагностики входа');
        const download = document.createElement('button');
        download.type = 'button';
        download.className = 'small';
        download.textContent = 'Скачать JSON';
        download.dataset.action = 'auth-diagnostic-download';
        download.dataset.profileId = String(profileId);
        host.append(preview, download);
      }
      preview.textContent = JSON.stringify(result, null, 2);
    }

    async function downloadAuthDiagnostic(button, profileId) {
      const host = button.closest('[data-auth-diagnostic-host]');
      const attemptId = host?.dataset.attemptId || '';
      if (!host || !attemptId || !Number.isInteger(profileId) || profileId < 1) {
        throw new Error('Текущая попытка входа недоступна');
      }
      const result = await api(`/profiles/${profileId}/auth-attempts/${encodeURIComponent(attemptId)}/diagnostic?download=1`);
      const file = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' });
      const objectUrl = URL.createObjectURL(file);
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = 'auth-attempt.json';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
    }

    function toggleGroup(id) {
      openGroupId = openGroupId === id ? null : id;
      loadGroups(true);
    }

    function saveDrafts() {
      document.querySelectorAll('#groupsList input[id^="phone-"], #groupsList input[id^="label-"], #groupsList textarea[id^="groupProxy-"]').forEach(el => {
        draftInputs[el.id] = el.value;
      });
    }

    function restoreDrafts() {
      for (const [id, val] of Object.entries(draftInputs)) {
        const el = document.getElementById(id);
        if (el) el.value = val;
      }
      if (authModalOpen) return;
      if (focusedInputId) {
        const el = document.getElementById(focusedInputId);
        if (el) {
          el.focus();
          const len = el.value.length;
          el.setSelectionRange(len, len);
        }
      }
    }

    async function deleteGroup(id) {
      if (!confirm('Удалить группу? Профили без других групп тоже удалятся.')) return;
      try {
        await api(`/groups/${id}`, { method: 'DELETE' });
        if (openGroupId === id) openGroupId = null;
        toast('Группа удалена', 'success');
        loadGroups(true);
        refreshCampaignOverview();
      } catch (e) {
        toast(e.message || 'Не удалось удалить группу', 'error');
      }
    }

    async function removeProfile(groupId, profileId) {
      if (!confirm('Удалить профиль из группы?')) return;
      try {
        await api(`/groups/${groupId}/profiles/${profileId}`, { method: 'DELETE' });
        toast('Профиль удалён', 'success');
        loadGroups(true);
        refreshCampaignOverview();
      } catch (e) {
        toast(e.message || 'Не удалось удалить профиль', 'error');
      }
    }

    async function resetLogin(id) {
      try {
        const result = await api(`/profiles/${id}/login/reset`, { method: 'POST' });
        toast(result.message || 'Вход отменён', 'info');
        loadGroups(true);
      } catch (e) {
        toast(e.message || 'Не удалось отменить вход', 'error');
      }
      refreshCampaignOverview();
    }

    function isValidInviteLink(link) {
      return /^https?:\/\/.+/i.test(link);
    }

    function updateCreateGroupBtn() {
      const name = document.getElementById('groupName').value.trim();
      const link = document.getElementById('groupLink').value.trim();
      const btn = document.getElementById('btnCreateGroup');
      const hint = document.getElementById('createGroupHint');
      const validLink = isValidInviteLink(link);
      const ok = !!(name && link && validLink);
      if (btn) btn.disabled = !ok;
      if (hint) {
        if (ok) hint.textContent = '';
        else if (!name && !link) hint.textContent = 'Нужны название и ссылка, начинающаяся с https://';
        else if (!name) hint.textContent = 'Укажите название группы';
        else if (!link) hint.textContent = 'Укажите ссылку на группу (https://…)';
        else hint.textContent = 'Ссылка должна начинаться с http:// или https://';
      }
    }

    async function loginProfile(id, fresh = false, groupId = null) {
      const params = new URLSearchParams();
      if (fresh) params.set('fresh', 'true');
      if (groupId != null) params.set('group_id', String(groupId));
      params.set('request_id', authRequestId('start', id));
      const q = params.toString() ? '?' + params.toString() : '';
      try {
        if (groupId != null) {
          await api(`/profiles/${id}/automation-scope`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ group_id: Number(groupId) }),
          });
        }
        const r = await api(`/profiles/${id}/login${q}`, { method: 'POST' });
        toast(r.message || 'Вход запущен', 'success');
        loadGroups(true);
        startLoginWatch(id, r.auth_step || 'connecting');
      } catch (e) {
        toast(e.message, 'error');
        loadGroups(true);
        refreshCampaignOverview();
      }
    }

    async function loginFromPhone(groupId, fresh = true) {
      try {
        const phoneRaw = document.getElementById('phone-' + groupId)?.value || '';
        const label = document.getElementById('label-' + groupId)?.value || '';
        if (!phoneRaw.trim()) return toast('Введите номер телефона', 'error');
        const phone = normalizePhone(phoneRaw);

        let profile = await lookupProfileByPhone(groupId, phone);

        if (!profile) {
          const r = await api(`/groups/${groupId}/profiles`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone, label }),
          });
          profile = { id: r.id, phone };
        }

        openGroupId = groupId;
        await loginProfile(profile.id, fresh, groupId);
      } catch (e) {
        toast(e.message || 'Ошибка входа', 'error');
      }
    }

    async function lookupProfileByPhone(groupId, phone) {
      const matchIn = (items) => (items || []).find(p => normalizePhone(p.phone) === phone) || null;
      try {
        const q = encodeURIComponent(phone);
        const data = await api(`/groups/${groupId}/profiles?phone=${q}`);
        const items = data.items || (data.id ? [data] : []);
        const match = matchIn(items);
        if (match) return match;
        if (items.length) {
          const fallback = await api(`/groups/${groupId}/profiles?offset=0&limit=500`);
          return matchIn(fallback.items);
        }
        return null;
      } catch (_) {
        const fallback = await api(`/groups/${groupId}/profiles?offset=0&limit=500`);
        return matchIn(fallback.items);
      }
    }

    async function saveGroupProxy(groupId) {
      const el = document.getElementById('groupProxy-' + groupId);
      const proxy = el ? el.value.trim() : '';
      try {
        await api(`/groups/${groupId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ proxy }),
        });
        toast(proxy ? 'Прокси группы сохранён' : 'Прокси группы очищен', 'success');
        loadGroups(true);
        refreshCampaignOverview();
      } catch (e) {
        toast(e.message, 'error');
      }
    }

    async function verifyGroupDestination(groupId) {
      const input = document.getElementById('groupChatId-' + groupId);
      const chatId = input ? input.value.trim() : '';
      const revision = input ? Number(input.dataset.revision) : NaN;
      if (!chatId) return toast('Укажите подтверждённый ID назначения', 'error');
      if (!Number.isInteger(revision) || revision < 0) {
        return toast('Обновите карточку группы и повторите подтверждение', 'error');
      }
      try {
        await api(`/groups/${groupId}/destination/verify`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ chat_id: chatId, revision }),
        });
        toast('Назначение подтверждено', 'success');
        loadGroups(true);
        refreshCampaignOverview();
      } catch (e) {
        toast(e.message || 'Не удалось подтвердить назначение', 'error');
      }
    }

    async function toggleGroupActive(groupId, active) {
      try {
        await api(`/groups/${groupId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ is_active: active ? 1 : 0 }),
        });
        toast(active ? 'Группа включена в рассылку' : 'Группа выключена из рассылки', 'success');
        loadGroups(true);
        refreshCampaignOverview();
      } catch (e) {
        toast(e.message || 'Не удалось изменить группу', 'error');
      }
    }

    function profilePageControls(groupId, total) {
      const offset = groupProfilePages[groupId] || 0;
      const pages = Math.max(1, Math.ceil(total / PROFILE_PAGE));
      const cur = Math.floor(offset / PROFILE_PAGE) + 1;
      if (pages <= 1) return '';
      return `<div class="row">
        <button type="button" class="small" aria-label="Предыдущая страница" data-action="profile-page" data-group-id="${groupId}" data-dir="-1" ${offset <= 0 ? 'disabled' : ''}>←</button>
        <span class="hint">Стр. ${cur}/${pages} (${total} проф.)</span>
        <button type="button" class="small" aria-label="Следующая страница" data-action="profile-page" data-group-id="${groupId}" data-dir="1" ${offset + PROFILE_PAGE >= total ? 'disabled' : ''}>→</button>
      </div>`;
    }

    function changeProfilePage(groupId, dir) {
      const cur = groupProfilePages[groupId] || 0;
      groupProfilePages[groupId] = Math.max(0, cur + dir * PROFILE_PAGE);
      loadGroups(true);
    }

    async function loadGroups(force = false) {
      if (groupsRefreshPaused && !force) return;
      saveDrafts();
      const groups = await api('/groups');
      const emptyEl = document.getElementById('groupsEmpty');
      if (!groups.length) {
        document.getElementById('groupsList').innerHTML = '';
        emptyEl.style.display = 'block';
        return;
      }
      emptyEl.style.display = 'none';
      const openProfiles = {};
      for (const g of groups) {
        if (openGroupId === g.id) {
          const offset = groupProfilePages[g.id] || 0;
          openProfiles[g.id] = await api(`/groups/${g.id}/profiles?offset=${offset}&limit=${PROFILE_PAGE}`);
        }
      }
      const focusedAuthAction = profileAuthActionPreference(document.activeElement);
      document.getElementById('groupsList').innerHTML = groups.map(g => {
        const open = openGroupId === g.id;
        const pdata = openProfiles[g.id];
        const profiles = pdata ? pdata.items : [];
        const total = pdata ? pdata.total : g.profiles_count;
        const destinationReady = Number(g.destination_verified) === 1
          && Boolean(String(g.max_chat_id || '').trim());
        const destinationRevision = Number.isInteger(Number(g.destination_revision))
          ? Number(g.destination_revision) : 0;
        const destinationReview = destinationReady
          ? `<div class="hint">Назначение подтверждено · revision ${destinationRevision}</div>`
          : `<div class="auth-error" role="status">Назначение требует явного подтверждения перед рассылкой.</div>
             <div class="row" style="margin-top:.5rem">
               <input id="groupChatId-${g.id}" data-revision="${destinationRevision}" placeholder="Подтверждённый ID чата" aria-label="Подтверждённый ID назначения">
               <button type="button" class="small" data-action="verify-group-destination" data-group-id="${g.id}">Подтвердить назначение</button>
             </div>`;
        const body = open ? (profiles.length ? profiles.map(p => `
          <tr>
            <td data-label="ID">${p.id}</td>
            <td data-label="Телефон">
              <div class="phone-cell">
                <span class="phone-num">${esc(p.phone)}${p.label ? ' ('+esc(p.label)+')' : ''}</span>
                ${phoneBadges(p)}
              </div>
            </td>
            <td data-label="Статус">
              <span class="status-${p.status}">${esc(statusRu(p.status))}</span>
              ${authLabel(p) ? `<div class="auth-wait">${esc(authLabel(p))}</div>` : ''}
              ${p.last_error ? `<div class="auth-error">${esc(p.last_error)}</div>` : ''}
            </td>
            <td data-label="День">${p.send_weekday == null ? '—' : ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][p.send_weekday]}</td>
            <td data-label="Прокси">${esc(p.proxy_label || 'не назначен')}</td>
            <td data-label="Действия">${profileActions(p, g.id)}</td>
          </tr>`).join('') : `<tr><td colspan="6" class="hint">Профилей нет — ${isUserRole() ? 'добавьте номер' : 'добавьте номер или импортируйте CSV'}</td></tr>`) : '';
        const groupActive = g.is_active == null || Number(g.is_active) !== 0;
        return `
          <div class="group-card">
            <div class="group-head-row">
            <button type="button" class="group-head" aria-expanded="${open ? 'true' : 'false'}" data-action="toggle-group" data-group-id="${g.id}">
              <span class="arrow">${open ? '▼' : '▶'}</span>
              <span class="title">${esc(g.name)}${groupActive ? '' : ' <span class="badge stop">неактивна</span>'}</span>
              <span class="meta">${g.profiles_count} проф.${g.active_count != null ? ' · ' + g.active_count + ' активных' : ''} · ${esc(g.invite_link || '—')}</span>
            </button>
              <details class="group-actions action-menu">
                <summary>Ещё</summary>
                <div>
                  ${!isUserRole() ? `<button type="button" class="small" data-action="toggle-group-active" data-group-id="${g.id}" data-active="${groupActive ? 0 : 1}">${groupActive ? 'Включить группу' : 'Отключить группу'}</button>` : ''}
                  <button type="button" class="small danger" data-action="delete-group" data-group-id="${g.id}">Удалить группу</button>
                </div>
              </details>
            </div>
            ${open ? `
            <div class="group-body">
              ${destinationReview}
              ${!isUserRole() ? `<div class="row" style="margin-bottom:.75rem">
                <small class="muted">Назначены: ${esc((g.proxy_labels || []).join(', ') || 'нет прокси')}</small>
                <textarea id="groupProxy-${g.id}" rows="2" placeholder="Вставьте список прокси для замены; адреса и учётные данные не показываются" aria-label="Новый список прокси группы" style="max-width:360px;min-height:2.4rem"></textarea>
                <button type="button" class="small" data-action="save-group-proxy" data-group-id="${g.id}">Сохранить прокси</button>
              </div>` : ''}
              <div class="table-wrap group-table-wrap">
              <table>
                <thead><tr><th>ID</th><th>Телефон</th><th>Статус</th><th>День отправки</th><th>Прокси</th><th>Действия</th></tr></thead>
                <tbody>${body}</tbody>
              </table>
              </div>
              ${profilePageControls(g.id, total)}
              <div class="row" style="margin-top:.75rem">
                <input id="phone-${g.id}" placeholder="+79991234567…" aria-label="Телефон">
                <input id="label-${g.id}" placeholder="Метка…" aria-label="Метка" style="max-width:120px">
                <button type="button" class="primary" data-action="login-from-phone" data-group-id="${g.id}">Войти</button>
                ${isUserRole() ? '' : `<button type="button" class="small" data-action="import-csv">Импорт CSV</button>`}
              </div>
            </div>` : ''}
          </div>`;
      }).join('');
      restoreDrafts();
      if (focusedAuthAction) {
        focusProfileAuthAction(focusedAuthAction.profileId, focusedAuthAction);
      }
      for (const g of groups) {
        if (openGroupId === g.id && openProfiles[g.id]) {
          for (const p of openProfiles[g.id].items) {
            if (p.auth_step === 'waiting_sms' || p.auth_step === 'waiting_cloud_password') {
              startLoginWatch(p.id, p.auth_step);
            }
          }
        }
      }
    }

    async function addGroup() {
      const name = document.getElementById('groupName').value.trim();
      const invite_link = document.getElementById('groupLink').value.trim();
      if (!name) return toast('Введите название группы', 'error');
      if (!invite_link) return toast('Введите пригласительную ссылку группы', 'error');
      if (!isValidInviteLink(invite_link)) return toast('Ссылка должна начинаться с http:// или https://', 'error');
      try {
        await api('/groups', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ name, max_chat_id: '', invite_link, proxy: '' }),
        });
        document.getElementById('groupName').value = '';
        document.getElementById('groupLink').value = '';
        updateCreateGroupBtn();
        toast('Группа создана', 'success');
        loadGroups(true);
        refreshCampaignOverview();
      } catch (e) {
        toast(e.message, 'error');
      }
    }

    async function loadSettings() {
      const s = await api('/settings');
      document.getElementById('delayMin').value = s.delay_min_sec;
      document.getElementById('delayMax').value = s.delay_max_sec;
      document.getElementById('jitter').value = s.jitter_percent;
      document.getElementById('msgPickMode').value = s.message_pick_mode || 'random_norepeat';
      document.getElementById('windowsWeekday').value = s.send_windows_weekday || '9-13,16-21';
      document.getElementById('windowsWeekend').value = s.send_windows_weekend || '11-14,17-20';
      document.getElementById('pausesOn').checked = String(s.human_pauses_enabled || '1') === '1';
      document.getElementById('shortPauseChance').value = s.short_pause_chance || '8';
      document.getElementById('shortPauseMin').value = s.short_pause_min_sec || '30';
      document.getElementById('shortPauseMax').value = s.short_pause_max_sec || '50';
      document.getElementById('longPauseChance').value = s.long_pause_chance || '3';
      document.getElementById('longPauseMin').value = s.long_pause_min_sec || '120';
      document.getElementById('longPauseMax').value = s.long_pause_max_sec || '300';
      document.getElementById('breakAfterN').value = s.break_after_n || '8';
      document.getElementById('breakMin').value = s.break_min_sec || '600';
      document.getElementById('breakMax').value = s.break_max_sec || '1200';
      document.getElementById('jitterMorning').value = s.jitter_morning_percent || '55';
      document.getElementById('jitterEvening').value = s.jitter_evening_percent || '35';
      document.getElementById('textsOn').checked = String(s.human_texts_enabled || '1') === '1';
      document.getElementById('dedupeOn').checked = String(s.text_dedupe_enabled || '1') === '1';
      document.getElementById('lenVarietyOn').checked = String(s.text_length_variety || '1') === '1';
      document.getElementById('textSimMax').value = s.text_similarity_max || '0.72';
      document.getElementById('textDedupeWin').value = s.text_dedupe_window || '6';
      document.getElementById('cdReauth').value = s.cooldown_reauth_hours || '24';
      document.getElementById('cdFail').value = s.cooldown_fail_hours || '2';
      document.getElementById('cdFailMax').value = s.cooldown_fail_max_hours || '48';
      document.getElementById('cdDisableAfter').value = s.cooldown_disable_after_fails || '8';
      document.getElementById('circuitMins').value = s.circuit_break_minutes || '30';
      document.getElementById('pwdAttempts').value = s.password_max_attempts;
      document.getElementById('apiPinHint').textContent = s.api_pin_set
        ? 'Код API установлен (хранится как scrypt-хеш). Введите новый, чтобы заменить.'
        : 'Код API не установлен — доступ без авторизации на localhost.';
      document.getElementById('apiPin').value = '';
      document.getElementById('webhookUrl').value = s.webhook_url || '';
      document.getElementById('tgChat').value = s.telegram_chat_id || '';
      document.getElementById('tgToken').value = '';
      document.getElementById('tgTokenHint').textContent = s.telegram_bot_token_set
        ? 'Токен задан. Введите новый, чтобы заменить.'
        : 'Токен не задан.';
      document.getElementById('backupHours').value = s.backup_interval_hours || '24';
      document.getElementById('notifyDone').checked = localStorage.getItem('maxNotifyDone') === '1';
      loadScheduleHint();
      loadBackupHint();
      try {
        const audit = await api('/settings/audit?limit=30');
        const box = document.getElementById('settingsAudit');
        if (!audit.items.length) box.textContent = '—';
        else box.innerHTML = audit.items.map(r =>
          `<div class="log-line">${esc(r.changed_at)}  ${esc(r.key)}: ${esc(r.old_value || '∅')} → ${esc(r.new_value || '∅')}</div>`
        ).join('');
      } catch (_) {}
    }
    async function saveSettings() {
      const body = {
        delay_min_sec: +document.getElementById('delayMin').value,
        delay_max_sec: +document.getElementById('delayMax').value,
        jitter_percent: +document.getElementById('jitter').value,
        message_pick_mode: document.getElementById('msgPickMode').value,
        send_windows_weekday: document.getElementById('windowsWeekday').value.trim(),
        send_windows_weekend: document.getElementById('windowsWeekend').value.trim(),
        human_pauses_enabled: document.getElementById('pausesOn').checked ? 1 : 0,
        short_pause_chance: +document.getElementById('shortPauseChance').value,
        short_pause_min_sec: +document.getElementById('shortPauseMin').value,
        short_pause_max_sec: +document.getElementById('shortPauseMax').value,
        long_pause_chance: +document.getElementById('longPauseChance').value,
        long_pause_min_sec: +document.getElementById('longPauseMin').value,
        long_pause_max_sec: +document.getElementById('longPauseMax').value,
        break_after_n: +document.getElementById('breakAfterN').value,
        break_min_sec: +document.getElementById('breakMin').value,
        break_max_sec: +document.getElementById('breakMax').value,
        jitter_morning_percent: +document.getElementById('jitterMorning').value,
        jitter_evening_percent: +document.getElementById('jitterEvening').value,
        human_texts_enabled: document.getElementById('textsOn').checked ? 1 : 0,
        text_dedupe_enabled: document.getElementById('dedupeOn').checked ? 1 : 0,
        text_length_variety: document.getElementById('lenVarietyOn').checked ? 1 : 0,
        text_similarity_max: +document.getElementById('textSimMax').value,
        text_dedupe_window: +document.getElementById('textDedupeWin').value,
        cooldown_reauth_hours: +document.getElementById('cdReauth').value,
        cooldown_fail_hours: +document.getElementById('cdFail').value,
        cooldown_fail_max_hours: +document.getElementById('cdFailMax').value,
        cooldown_disable_after_fails: +document.getElementById('cdDisableAfter').value,
        circuit_break_minutes: +document.getElementById('circuitMins').value,
        password_max_attempts: +document.getElementById('pwdAttempts').value,
        webhook_url: document.getElementById('webhookUrl').value.trim(),
        telegram_chat_id: document.getElementById('tgChat').value.trim(),
        backup_interval_hours: +document.getElementById('backupHours').value,
      };
      const pin = document.getElementById('apiPin').value.trim();
      if (pin) body.api_pin = pin;
      const tg = document.getElementById('tgToken').value.trim();
      if (tg) body.telegram_bot_token = tg;
      try {
        await api('/settings', {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(body),
        });
        if (pin) setApiPin(pin);
        const notify = document.getElementById('notifyDone').checked;
        localStorage.setItem('maxNotifyDone', notify ? '1' : '0');
        if (notify && 'Notification' in window && Notification.permission === 'default') {
          Notification.requestPermission();
        }
        toast('Сохранено', 'success');
        loadSettings();
      } catch (e) {
        toast(e.message, 'error');
      }
    }

    function esc(s) {
      return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    const MAX_PROFILE_IMPORT_BYTES = 5 * 1024 * 1024;
    const MAX_PROFILE_IMPORT_ROWS = 2000;

    function detectDelimitedSeparator(line) {
      const candidates = [',', ';', '\t'];
      let best = ',';
      let bestCount = 0;
      for (const candidate of candidates) {
        let quoted = false;
        let count = 0;
        for (let i = 0; i < line.length; i += 1) {
          const char = line[i];
          if (char === '"') {
            if (quoted && line[i + 1] === '"') i += 1;
            else quoted = !quoted;
          } else if (!quoted && char === candidate) {
            count += 1;
          }
        }
        if (count > bestCount) {
          best = candidate;
          bestCount = count;
        }
      }
      return best;
    }

    function parseDelimitedRecords(text, separator) {
      const rows = [];
      let row = [];
      let field = '';
      let quoted = false;
      for (let i = 0; i < text.length; i += 1) {
        const char = text[i];
        if (quoted) {
          if (char === '"' && text[i + 1] === '"') {
            field += '"';
            i += 1;
          } else if (char === '"') {
            quoted = false;
          } else {
            field += char;
          }
        } else if (char === '"' && field.length === 0) {
          quoted = true;
        } else if (char === separator) {
          row.push(field);
          field = '';
        } else if (char === '\n') {
          row.push(field.replace(/\r$/, ''));
          rows.push(row);
          row = [];
          field = '';
        } else {
          field += char;
        }
      }
      if (quoted) throw new Error('Незакрытая кавычка в CSV');
      if (field || row.length) {
        row.push(field);
        rows.push(row);
      }
      return rows;
    }

    function parseProfileImport(text, byteLength) {
      if (byteLength > MAX_PROFILE_IMPORT_BYTES) {
        throw new Error('Файл слишком большой (максимум 5 МБ)');
      }
      const firstDataLine = text.split(/\r?\n/).find((line) => {
        const value = line.trim();
        return value && !value.startsWith('#');
      }) || '';
      const rows = parseDelimitedRecords(
        text,
        detectDelimitedSeparator(firstDataLine),
      );
      const profiles = [];
      for (const fields of rows) {
        const phone = String(fields[0] || '').trim();
        const label = String(fields[1] || '').trim();
        if (!phone || phone.startsWith('#') || phone.toLowerCase() === 'phone') continue;
        if (profiles.length >= MAX_PROFILE_IMPORT_ROWS) {
          throw new Error('Максимум 2000 профилей за раз');
        }
        profiles.push({ phone, label });
      }
      return profiles;
    }

    document.getElementById('csvFile').addEventListener('change', async (e) => {
      const f = e.target.files[0];
      e.target.value = '';
      if (!f) return;
      if (!openGroupId) {
        toast('Сначала откройте группу', 'error');
        return;
      }
      const text = await f.text();
      let profiles;
      try {
        profiles = parseProfileImport(text, f.size);
      } catch (err) {
        toast(err.message, 'error');
        return;
      }
      if (!profiles.length) {
        toast('В файле нет номеров', 'error');
        return;
      }
      try {
        const r = await api(`/groups/${openGroupId}/profiles/bulk`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ profiles }),
        });
        toast(`Импорт: +${r.added}, пропуск ${r.skipped}, ошибок ${r.errors.length}`, 'success');
        loadGroups(true);
        loadDashboard();
      } catch (err) {
        toast(err.message, 'error');
      }
    });

    (async () => {
      try { await initServerMode(); } catch (_) {}
      markUiReady();
      applyTabFromHash();
      await reconcilePendingCampaignCommand();
      try { await initVaultUI(); } catch (e) { toast(e.message, 'error'); }
      if (!isUserRole()) {
        loadMessages();
        loadSettings();
      }
      loadGroups();
      if (!isSimpleCampaignView()) {
        loadSendLog();
        loadCampaigns();
        loadScheduleHint();
      }
      refreshStatus();
      connectStatusWs();
      try { await loadDashboard(); } catch (e) { toast(e.message, 'error'); }
    })();
