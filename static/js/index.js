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
        btn.disabled = false;
        btn.innerHTML = orig;
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
        start.disabled = true;
        start.title = 'Обратитесь к администратору';
        stop.classList.remove('campaign-btn-active', 'campaign-btn-idle');
        return;
      }
      start.disabled = false;
      start.title = '';
      const on = !!(s && (s.running || s.auto_run));
      if (on) {
        stop.classList.add('campaign-btn-active');
        start.classList.add('campaign-btn-idle');
      } else {
        start.classList.add('campaign-btn-active');
        stop.classList.add('campaign-btn-idle');
      }
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
      if (tabId === 'campaign') loadDashboard();
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
          const detail = j.detail;
          const msg = typeof detail === 'string'
            ? detail
            : (Array.isArray(detail) ? detail.map(x => x.msg || JSON.stringify(x)).join('; ') : '');
          throw new Error(msg || r.statusText || ('HTTP ' + r.status));
        }
        return j;
      });
    };

    function markUiReady() {
      document.body.classList.add('ui-ready');
    }

    function mountCampaignLayout(simpleCampaign) {
      const userContent = document.getElementById('userSummaryContent');
      const adminSlot = document.getElementById('adminSummarySlot');
      const dashStats = document.getElementById('dashStats');
      const dashCardsPanel = document.getElementById('dashCardsPanel');
      // User summary: stats tiles only. Profile cards stay admin-only.
      if (dashStats && userContent && adminSlot) {
        const statsTarget = simpleCampaign ? userContent : adminSlot;
        if (dashStats.parentElement !== statsTarget) statsTarget.appendChild(dashStats);
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
    document.getElementById('btnStart').addEventListener('click', function() { withLoading(this, startCampaign); });
    document.getElementById('btnPause').addEventListener('click', function() { withLoading(this, pauseCampaign); });
    document.getElementById('btnStop').addEventListener('click', function() { withLoading(this, stopCampaign); });
    document.getElementById('btnReset').addEventListener('click', function() { withLoading(this, resetCampaign); });
    document.getElementById('btnTestSend').addEventListener('click', function() { withLoading(this, testSend); });
    document.getElementById('btnRetryFailed').addEventListener('click', function() { withLoading(this, retryFailed); });
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
      if (action === 'exit-impersonation') {
        exitImpersonation();
      } else if (action === 'send-log-page') {
        loadSendLog(parseDataId(btn.dataset.offset) || 0);
      } else if (action === 'login-profile') {
        withLoading(btn, () => loginProfile(profileId, btn.dataset.fresh === '1', groupId));
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

    function showAuthModal(title, message, password = false) {
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
          if (previousFocus && typeof previousFocus.focus === 'function') previousFocus.focus();
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
      try {
        return await api(`/profiles/${profileId}`);
      } catch {
        return null;
      }
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
              `Введите код из SMS для ${p.phone}`
            );
            if (code === null) {
              await api(`/profiles/${profileId}/login/reset`, { method: 'POST' });
              break;
            }
            await api(`/profiles/${profileId}/sms`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ code }),
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
              true
            );
            if (pwd === null) {
              await api(`/profiles/${profileId}/login/reset`, { method: 'POST' });
              break;
            }
            await api(`/profiles/${profileId}/password`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ code: pwd }),
            });
            loadGroups(true);
            await sleep(300);
            continue;
          }

          if (p.status === 'active' && p.auth_step === 'idle') {
            toast('Аккаунт подключён', 'success');
            loadGroups(true);
            break;
          }

          if (p.auth_step === 'error' || p.status === 'needs_reauth') {
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
        loadGroups(true);
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
      if (!prog.total || prog.total <= 0) {
        panel.style.display = 'none';
        return;
      }
      panel.style.display = '';
      const sent = prog.sent || 0;
      const total = prog.total || 0;
      const remaining = prog.remaining != null ? prog.remaining : Math.max(0, total - sent);
      const pct = Math.min(100, sent / total * 100);
      bar.style.width = pct.toFixed(1) + '%';
      label.textContent = `${sent}/${total} · ${remaining} ост. · ${pct.toFixed(0)}%`;
      if (statusEl) {
        if (running) statusEl.textContent = 'идёт рассылка';
        else if (autoRun) statusEl.textContent = 'активна · ждёт продолжения';
        else statusEl.textContent = 'остановлена';
      }
    }

    let _statusWs = null;
    let _statusWsRetry = 0;
    let _statusPollTimer = null;

    function stopStatusPoll() {
      if (_statusPollTimer) {
        clearInterval(_statusPollTimer);
        _statusPollTimer = null;
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

    function startStatusPoll() {
      if (_statusPollTimer) return;
      setLiveBadge('poll');
      _statusPollTimer = setInterval(() => { refreshStatus().catch(() => {}); }, 2000);
    }

    function connectStatusWs() {
      if (_statusWs && (_statusWs.readyState === WebSocket.OPEN || _statusWs.readyState === WebSocket.CONNECTING)) {
        return;
      }
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
        try {
          applyStatus(JSON.parse(ev.data));
        } catch (_) {}
      };
      ws.onclose = () => {
        _statusWs = null;
        startStatusPoll();
        const delay = Math.min(15000, 1000 * Math.pow(2, _statusWsRetry++));
        setTimeout(connectStatusWs, delay);
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
              <td>${esc(r.sent_at || '')}</td>
              <td>#${r.profile_id} ${esc(r.phone || '')}</td>
              <td>${esc(r.group_name || '?')}</td>
              <td>${esc(sendStatusRu(r.status))}</td>
              <td>${esc(r.error || '')}</td>
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
      el.innerHTML = `
        <div class="dash-stat"><div class="n">${counts.active || 0}</div><div class="l">активны</div></div>
        <div class="dash-stat"><div class="n">${counts.pending || 0}</div><div class="l">ожидают</div></div>
        <div class="dash-stat"><div class="n">${counts.needs_reauth || 0}</div><div class="l">нужен вход</div></div>
        <div class="dash-stat"><div class="n">${counts.banned || 0}</div><div class="l">забанены</div></div>
        <div class="dash-stat"><div class="n">${(d && d.groups_count) || 0}</div><div class="l">групп</div></div>
        <div class="dash-stat"><div class="n">${(d && d.sent_today) || 0}</div><div class="l">успешно сегодня</div></div>
        <div class="dash-stat"><div class="n">${(d && d.failed_today) || 0}</div><div class="l">ошибок сегодня</div></div>
        <div class="dash-stat"><div class="n">${(d && d.circuit_open) || 0}</div><div class="l">в автопаузе</div></div>
      `;
    }

    async function loadDashboard() {
      const errEl = document.getElementById('dashSummaryError');
      try {
        const d = await api('/dashboard');
        if (errEl) errEl.style.display = 'none';
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
        box.innerHTML = items.map(p => `
        <div class="dash-card">
          <div class="phone">${esc(p.phone)}${p.label ? ' · ' + esc(p.label) : ''}</div>
          <div class="meta">
            <span class="status-${p.status}">${esc(statusRu(p.status))}</span>
            ${p.circuit_open ? ' · <span class="auth-error">автопауза</span>' : ''}
            ${authLabel(p) ? ' · ' + esc(authLabel(p)) : ''}
          </div>
          <div class="meta">Сегодня: ${p.messages_sent_today || 0} · ${esc(p.group_names || '')}</div>
          ${p.last_error ? `<div class="auth-error">${esc(p.last_error)}</div>` : ''}
          <div class="row" style="margin-top:.5rem;margin-bottom:0">
            <button type="button" class="small" data-action="login-profile" data-profile-id="${p.id}" data-fresh="${isUserRole() ? 1 : 0}" data-group-id="${p.primary_group_id || ''}">Войти</button>
            ${isUserRole() ? '' : `<button type="button" class="small" data-action="login-profile" data-profile-id="${p.id}" data-fresh="1" data-group-id="${p.primary_group_id || ''}">Заново</button>`}
          </div>
        </div>
      `).join('');
      } catch (e) {
        if (errEl) {
          errEl.textContent = 'Не удалось загрузить сводку: ' + (e.message || 'ошибка');
          errEl.style.display = 'block';
        }
        throw e;
      }
    }

    async function startCampaign() {
      try {
        if (isUserRole() && !_subscriptionActive) {
          toast('Нет активной подписки. Обратитесь к администратору.', 'error');
          return;
        }
        if (!isSimpleCampaignView()) {
          const s = await api('/status');
          const prog = s.campaign_progress || {};
          const activeCount = (s.profiles && s.profiles.active) || 0;
          const msg = prog.goal === 'daily_limits'
            ? [
                `Цель: исчерпать дневные лимиты`,
                `Ёмкость сегодня: ${prog.total || 0} (уже ${prog.sent || 0})`,
                `Пул TXT: ${s.messages_count}`,
                `Активных профилей: ${activeCount}`,
              ].join('\n')
            : [
                `Сообщений в пуле: ${prog.total || s.messages_count}`,
                `Активных профилей: ${activeCount}`,
                prog.sent > 0 ? `Продолжить с позиции ${prog.sent}` : 'Старт с начала',
              ].join('\n');
          if (!confirm(`Запустить рассылку?\n\n${msg}`)) return;
        } else if (!confirm('Запустить рассылку?\n\nСистема будет работать автоматически каждый день, пока вы не нажмёте «Стоп».')) {
          return;
        }
        await api('/campaign/start', { method: 'POST' });
        refreshStatus();
        toast('Рассылка запущена', 'success');
      } catch (e) {
        const msg = e.message || '';
        if (isUserRole() && /загрузите файл сообщений/i.test(msg)) {
          toast('Нет файла сообщений. Обратитесь к администратору.', 'error');
        } else {
          toast(msg || 'Ошибка', 'error');
        }
      }
    }
    async function pauseCampaign() {
      try {
        await api('/campaign/pause', { method: 'POST' });
        refreshStatus();
        toast('Рассылка на паузе', 'success');
      } catch (e) {
        toast(e.message, 'error');
      }
    }
    async function stopCampaign() {
      try {
        if (!confirm('Остановить рассылку?\n\nАвтозапуск будет выключен, пока вы снова не нажмёте «Старт».')) return;
        await api('/campaign/stop', { method: 'POST' });
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
        const r = await api('/campaign/test', { method: 'POST' });
        toast(`Тест успешен: ${r.phone} → #${r.group_id}`, 'success');
        refreshStatus();
        loadSendLog(0);
      } catch (e) {
        toast(e.message, 'error');
      }
    }

    async function retryFailed() {
      if (!confirm('Повторить неотправленные ошибки с минимального индекса сообщения?')) return;
      try {
        const r = await api('/campaign/retry_failed', { method: 'POST' });
        toast(`Повтор с индекса=${r.message_idx}`, 'success');
        refreshStatus();
        loadCampaigns();
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
              <td>#${c.id}</td>
              <td>${esc(campaignStatusRu(c.status))}</td>
              <td>${esc(c.started_at || '')}</td>
              <td>${esc(c.finished_at || '—')}</td>
              <td>${c.messages_sent || 0}/${c.messages_failed || 0} · всего ${c.messages_total || 0}</td>
              <td>${esc((c.reason || '').slice(0, 80))}</td>
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
        pending: 'ожидает',
        needs_reauth: 'нужен вход',
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
      const err = p.last_error || '';
      if (p.status === 'banned') {
        badges.push(['Забанен', 'danger', err || 'Аккаунт заблокирован']);
      } else if (p.status === 'active') {
        badges.push(['Активен', 'ok', 'Активен']);
      } else {
        badges.push(['Неактивен', 'warn', statusRu(p.status) || 'Неактивен']);
      }
      if (p.status === 'needs_reauth') {
        badges.push(['Сессия', 'warn', err || 'Нужен повторный вход']);
      } else if (p.status === 'pending') {
        badges.push(['Не вошёл', 'info', 'Ещё не авторизован']);
      } else if (p.status === 'disabled') {
        badges.push(['Отключён', 'danger', err || 'Профиль отключён']);
      }
      if (p.circuit_open) {
        badges.push(['Автопауза', 'danger', 'Пауза после серии ошибок']);
      }
      if (p.in_cooldown) {
        const until = (p.cooldown_until || '').slice(0, 16);
        badges.push(['Пауза', 'warn', until ? `до ${until}` : 'временная пауза']);
      }
      if (p.auth_step === 'waiting_sms') badges.push(['Код SMS', 'warn', 'Ожидает код']);
      if (p.auth_step === 'waiting_cloud_password') badges.push(['Пароль MAX', 'warn', p.auth_hint || 'Нужен облачный пароль']);
      if (p.auth_step === 'error' && p.status === 'active') {
        badges.push(['Ошибка входа', 'danger', err || 'Ошибка авторизации']);
      }
      if (p.warmup_active && p.status === 'active') {
        badges.push([`Прогрев ${p.warmup_day}`, 'muted', 'Прогрев аккаунта']);
      }
      return `<span class="phone-badges">${badges.map(([label, kind, tip]) =>
        `<span class="phone-badge ${kind}" title="${esc(tip || label)}">${esc(label)}</span>`
      ).join('')}</span>`;
    }

    function profileActions(p, groupId) {
      const busy = ['connecting', 'waiting_sms', 'verifying_sms', 'waiting_cloud_password', 'verifying_password'].includes(p.auth_step);
      const loginFresh = isUserRole();
      return `
        <button type="button" class="small" data-action="login-profile" data-profile-id="${p.id}" data-fresh="${loginFresh ? 1 : 0}" data-group-id="${groupId}" ${busy ? 'disabled' : ''}>Войти</button>
        ${isUserRole() ? '' : `<button type="button" class="small" data-action="login-profile" data-profile-id="${p.id}" data-fresh="1" data-group-id="${groupId}" ${busy ? 'disabled' : ''}>Заново</button>`}
        ${busy ? `<button type="button" class="small" data-action="reset-login" data-profile-id="${p.id}">Сброс</button>` : ''}
        <button type="button" class="small danger" data-action="remove-profile" data-group-id="${groupId}" data-profile-id="${p.id}">Удалить</button>`;
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
      } catch (e) {
        toast(e.message || 'Не удалось удалить профиль', 'error');
      }
    }

    async function resetLogin(id) {
      await api(`/profiles/${id}/login/reset`, { method: 'POST' });
      loadGroups(true);
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
      const q = params.toString() ? '?' + params.toString() : '';
      try {
        const r = await api(`/profiles/${id}/login${q}`, { method: 'POST' });
        toast(r.message || 'Вход запущен', 'success');
        loadGroups(true);
        startLoginWatch(id, r.auth_step || 'connecting');
      } catch (e) {
        toast(e.message, 'error');
        loadGroups(true);
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
      } catch (e) {
        toast(e.message, 'error');
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
      document.getElementById('groupsList').innerHTML = groups.map(g => {
        const open = openGroupId === g.id;
        const pdata = openProfiles[g.id];
        const profiles = pdata ? pdata.items : [];
        const total = pdata ? pdata.total : g.profiles_count;
        const body = open ? (profiles.length ? profiles.map(p => `
          <tr>
            <td>${p.id}</td>
            <td>
              <div class="phone-cell">
                <span class="phone-num">${esc(p.phone)}${p.label ? ' ('+esc(p.label)+')' : ''}</span>
                ${phoneBadges(p)}
              </div>
              ${p.in_cooldown ? `<div class="auth-error">пауза до ${esc((p.cooldown_until||'').slice(0,16))}</div>` : ''}
            </td>
            <td>
              <span class="status-${p.status}">${statusRu(p.status)}</span>
              ${p.circuit_open ? ' · <span class="auth-error">автопауза</span>' : ''}
              ${authLabel(p) ? `<div class="auth-wait">${esc(authLabel(p))}</div>` : ''}
              ${p.last_error ? `<div class="auth-error">${esc(p.last_error)}</div>` : ''}
            </td>
            <td>${p.messages_sent_today || 0}${p.daily_limit != null ? '/'+p.daily_limit : ''}</td>
            <td>${profileActions(p, g.id)}</td>
          </tr>`).join('') : `<tr><td colspan="5" class="hint">Профилей нет — ${isUserRole() ? 'добавьте номер' : 'добавьте номер или импортируйте CSV'}</td></tr>`) : '';
        const groupActive = g.is_active == null || Number(g.is_active) !== 0;
        return `
          <div class="group-card">
            <div class="group-head-row">
            <button type="button" class="group-head" aria-expanded="${open ? 'true' : 'false'}" data-action="toggle-group" data-group-id="${g.id}">
              <span class="arrow">${open ? '▼' : '▶'}</span>
              <span class="title">${esc(g.name)}${groupActive ? '' : ' <span class="badge stop">неактивна</span>'}</span>
              <span class="meta">${g.profiles_count} проф.${g.active_count != null ? ' · ' + g.active_count + ' активных' : ''} · ${esc(g.invite_link || '—')}</span>
            </button>
              <span class="group-actions">
                ${!isUserRole() ? `<button type="button" class="small" data-action="toggle-group-active" data-group-id="${g.id}" data-active="${groupActive ? 0 : 1}">${groupActive ? 'Выкл.' : 'Вкл.'}</button>` : ''}
                <button type="button" class="small danger" data-action="delete-group" data-group-id="${g.id}">Удалить группу</button>
              </span>
            </div>
            ${open ? `
            <div class="group-body">
              ${!isUserRole() ? `<div class="row" style="margin-bottom:.75rem">
                <textarea id="groupProxy-${g.id}" rows="2" placeholder="1 прокси на группу (~30 acc). Несколько URL — ротация по аккаунту…" aria-label="Прокси группы" style="max-width:360px;min-height:2.4rem">${esc(g.proxy||'')}</textarea>
                <button type="button" class="small" data-action="save-group-proxy" data-group-id="${g.id}">Сохранить прокси</button>
              </div>` : ''}
              <div class="table-wrap group-table-wrap">
              <table>
                <thead><tr><th>ID</th><th>Телефон</th><th>Статус</th><th>Сегодня</th><th>Действия</th></tr></thead>
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
      } catch (e) {
        toast(e.message, 'error');
      }
    }

    async function loadSettings() {
      const s = await api('/settings');
      document.getElementById('delayMin').value = s.delay_min_sec;
      document.getElementById('delayMax').value = s.delay_max_sec;
      document.getElementById('dayLimitMin').value = s.daily_limit_min || '5';
      document.getElementById('dayLimitMax').value = s.daily_limit_max || s.max_msgs_per_profile_day || '12';
      document.getElementById('jitter').value = s.jitter_percent;
      document.getElementById('msgPickMode').value = s.message_pick_mode || 'random_norepeat';
      document.getElementById('campaignGoal').value = s.campaign_goal || 'daily_limits';
      document.getElementById('warmupOn').checked = String(s.warmup_enabled || '1') === '1';
      document.getElementById('warmupDays').value = s.warmup_days || '7';
      document.getElementById('warmupStartMin').value = s.warmup_start_min || '1';
      document.getElementById('warmupStartMax').value = s.warmup_start_max || '2';
      document.getElementById('lazyDayPct').value = s.lazy_day_percent || '15';
      document.getElementById('lazyDayFactor').value = s.lazy_day_factor || '0.4';
      document.getElementById('rhythmOn').checked = String(s.human_rhythm_enabled || '1') === '1';
      document.getElementById('tzOffset').value = s.timezone_offset_hours ?? '3';
      document.getElementById('windowsWeekday').value = s.send_windows_weekday || '9-13,16-21';
      document.getElementById('windowsWeekend').value = s.send_windows_weekend || '11-14,17-20';
      document.getElementById('daySkipPct').value = s.day_skip_percent || '40';
      document.getElementById('roleActivePct').value = s.role_active_percent || '30';
      document.getElementById('roleQuietPct').value = s.role_quiet_percent || '30';
      document.getElementById('rolePlanOn').checked = String(s.role_plan_enabled || '1') === '1';
      document.getElementById('roleActiveMin').value = s.role_active_min || '5';
      document.getElementById('roleActiveMax').value = s.role_active_max || '10';
      document.getElementById('roleQuietLimit').value = s.role_quiet_limit || '1';
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
      document.getElementById('presenceOn').checked = String(s.human_presence_enabled || '1') === '1';
      document.getElementById('presHist').value = s.presence_history_chance || '70';
      document.getElementById('presRead').value = s.presence_read_chance || '40';
      document.getElementById('presReact').value = s.presence_react_chance || '12';
      document.getElementById('presReactions').value = s.presence_reactions || '👍,❤️,🔥,😂';
      document.getElementById('presIdle').value = s.presence_idle_chance || '5';
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
      document.getElementById('workerPool').value = s.worker_pool_size || '1';
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
        daily_limit_min: +document.getElementById('dayLimitMin').value,
        daily_limit_max: +document.getElementById('dayLimitMax').value,
        jitter_percent: +document.getElementById('jitter').value,
        message_pick_mode: document.getElementById('msgPickMode').value,
        campaign_goal: document.getElementById('campaignGoal').value,
        warmup_enabled: document.getElementById('warmupOn').checked ? 1 : 0,
        warmup_days: +document.getElementById('warmupDays').value,
        warmup_start_min: +document.getElementById('warmupStartMin').value,
        warmup_start_max: +document.getElementById('warmupStartMax').value,
        lazy_day_percent: +document.getElementById('lazyDayPct').value,
        lazy_day_factor: +document.getElementById('lazyDayFactor').value,
        human_rhythm_enabled: document.getElementById('rhythmOn').checked ? 1 : 0,
        timezone_offset_hours: +document.getElementById('tzOffset').value,
        send_windows_weekday: document.getElementById('windowsWeekday').value.trim(),
        send_windows_weekend: document.getElementById('windowsWeekend').value.trim(),
        day_skip_percent: +document.getElementById('daySkipPct').value,
        role_plan_enabled: document.getElementById('rolePlanOn').checked ? 1 : 0,
        role_active_percent: +document.getElementById('roleActivePct').value,
        role_quiet_percent: +document.getElementById('roleQuietPct').value,
        role_active_min: +document.getElementById('roleActiveMin').value,
        role_active_max: +document.getElementById('roleActiveMax').value,
        role_quiet_limit: +document.getElementById('roleQuietLimit').value,
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
        human_presence_enabled: document.getElementById('presenceOn').checked ? 1 : 0,
        presence_history_chance: +document.getElementById('presHist').value,
        presence_read_chance: +document.getElementById('presRead').value,
        presence_react_chance: +document.getElementById('presReact').value,
        presence_reactions: document.getElementById('presReactions').value.trim(),
        presence_idle_chance: +document.getElementById('presIdle').value,
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
      if (!isUserRole()) {
        body.worker_pool_size = +document.getElementById('workerPool').value;
      }
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

    document.getElementById('csvFile').addEventListener('change', async (e) => {
      const f = e.target.files[0];
      e.target.value = '';
      if (!f) return;
      if (!openGroupId) {
        toast('Сначала откройте группу', 'error');
        return;
      }
      const text = await f.text();
      const profiles = [];
      for (const raw of text.split(/\r?\n/)) {
        const line = raw.trim();
        if (!line || line.startsWith('#') || line.toLowerCase().startsWith('phone')) continue;
        const parts = line.split(/[,;\t]/);
        const phone = (parts[0] || '').trim();
        const label = (parts[1] || '').trim();
        if (!phone) continue;
        profiles.push({ phone, label });
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
    setInterval(() => {
      if (document.getElementById('groups').classList.contains('active') && !authModalOpen) loadGroups();
      if (document.getElementById('campaign').classList.contains('active') && !isSimpleCampaignView()) {
        loadSendLog(sendLogOffset);
        loadCampaigns();
        loadScheduleHint();
      }
      if (document.getElementById('campaign').classList.contains('active')) {
        loadDashboard().catch(() => {});
      }
    }, 2000);
