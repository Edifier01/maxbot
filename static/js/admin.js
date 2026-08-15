function jsonHeaders(json = true) {
      const h = {};
      if (json) h['Content-Type'] = 'application/json';
      return h;
    }
    function formatApiError(detail) {
      if (!detail) return '';
      if (typeof detail === 'string') return detail;
      if (Array.isArray(detail)) {
        return detail.map(d => (d && d.msg) ? d.msg : JSON.stringify(d)).join('; ');
      }
      return String(detail);
    }
    const ruDateFmt = new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short' });
    function formatAdminDate(iso) {
      if (!iso) return '?';
      const d = new Date(iso);
      return Number.isNaN(d.getTime()) ? iso.slice(0, 10) : ruDateFmt.format(d);
    }
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
      t.className = 'toast ' + type;
      t.textContent = msg;
      c.appendChild(t);
      setTimeout(() => t.remove(), duration);
    }
    async function api(path, opts = {}) {
      const isForm = opts.body instanceof FormData;
      opts.credentials = opts.credentials || 'same-origin';
      opts.headers = { ...jsonHeaders(!isForm), ...(opts.headers || {}) };
      const r = await fetch('/api' + path, opts);
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(formatApiError(j.detail) || r.statusText);
      return j;
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
    async function logout() {
      try {
        await fetch('/api/auth/logout', {
          method: 'POST',
          credentials: 'same-origin',
        });
      } catch (_) {}
      sessionStorage.removeItem('maxImpersonating');
      location.href = '/auth.html';
    }
    async function loadExpiring() {
      const hint = document.getElementById('expiringHint');
      const table = document.getElementById('expiringTable');
      const tbody = document.getElementById('expiringBody');
      try {
        const data = await api('/admin/subscriptions/expiring?days=7');
        const items = data.items || [];
        if (!items.length) {
          hint.textContent = 'Нет подписок, истекающих в ближайшие 7 дней.';
          table.style.display = 'none';
          return;
        }
        hint.textContent = `Найдено: ${items.length}`;
        table.style.display = '';
        tbody.innerHTML = items.map(row => {
          const exp = formatAdminDate(row.expires_at);
          const cls = row.days_left <= 1 ? 'danger' : (row.days_left <= 7 ? 'warn' : 'ok');
          return `<tr>
            <td>${esc(row.institution_name)}</td>
            <td>${esc(row.email)}</td>
            <td>${exp}</td>
            <td><span class="badge ${cls} tabular-nums">${row.days_left} дн.</span></td>
          </tr>`;
        }).join('');
      } catch (e) {
        hint.textContent = 'Ошибка: ' + e.message;
        table.style.display = 'none';
      }
    }
    async function loadUsers() {
      const data = await api('/admin/users');
      const items = data.items;
      const tbody = document.getElementById('usersBody');
      if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="hint">Учреждений пока нет</td></tr>';
        return;
      }
      tbody.innerHTML = items.map(u => {
        const sub = u.subscription;
        const subBadge = sub.active
          ? (() => {
              const exp = formatAdminDate(sub.expires_at);
              const days = sub.expires_at
                ? Math.ceil((new Date(sub.expires_at) - Date.now()) / 86400000)
                : null;
              const cls = days !== null && days <= 1 ? 'danger' : (days !== null && days <= 7 ? 'warn' : 'ok');
              const hint = days !== null && days <= 7 ? ` (${days} дн.)` : '';
              return `<span class="badge ${cls} tabular-nums">до ${exp}${hint}</span>`;
            })()
          : (sub.expires_at
              ? `<span class="badge warn tabular-nums">истекла ${formatAdminDate(sub.expires_at)}</span>`
              : '<span class="badge stop">нет</span>');
        return `<tr>
          <td>${esc(u.institution_name)}</td>
          <td>${esc(u.email)}</td>
          <td>${subBadge}</td>
          <td id="stats-${u.tenant_id}"><button class="btn" data-action="load-stats" data-tenant-id="${u.tenant_id}">Статистика</button></td>
          <td>
            <span class="row">
              <input type="number" id="pool-${u.tenant_id}" min="1" max="32" value="1" style="width:3.2rem;text-align:center" aria-label="Пул воркеров">
              <button class="btn" data-action="save-worker-pool" data-tenant-id="${u.tenant_id}">Сохранить</button>
            </span>
          </td>
          <td>
            <div class="row">
              <button class="btn primary" data-action="impersonate" data-tenant-id="${u.tenant_id}" data-institution-name="${escAttr(u.institution_name)}">Войти в кабинет</button>
              <button class="btn" data-action="grant-month" data-tenant-id="${u.tenant_id}" data-institution-name="${escAttr(u.institution_name)}">+30 дней</button>
              <input type="number" id="sub-days-${u.tenant_id}" min="1" max="3650" value="30" style="width:3.5rem;text-align:center" aria-label="Дней продления">
              <button class="btn" data-action="grant-days" data-tenant-id="${u.tenant_id}" data-institution-name="${escAttr(u.institution_name)}">Продлить</button>
              <button class="btn danger" data-action="revoke-sub" data-tenant-id="${u.tenant_id}" data-institution-name="${escAttr(u.institution_name)}">Отозвать</button>
              <button class="btn danger" data-action="delete-user" data-tenant-id="${u.tenant_id}" data-institution-name="${escAttr(u.institution_name)}">Удалить</button>
            </div>
          </td>
        </tr>`;
      }).join('');
      await loadTenantWorkerPools(items);
    }
    async function loadTenantWorkerPools(items) {
      await Promise.all(items.map(async u => {
        try {
          const s = await api('/admin/tenants/' + u.tenant_id + '/settings');
          const inp = document.getElementById('pool-' + u.tenant_id);
          if (inp) inp.value = s.worker_pool_size || 1;
        } catch (_) {}
      }));
    }
    async function saveWorkerPool(tid, btn) {
      const inp = document.getElementById('pool-' + tid);
      const size = parseInt(inp && inp.value, 10);
      if (!size || size < 1 || size > 32) {
        toast('Пул воркеров: от 1 до 32', 'error');
        return;
      }
      if (btn) btn.disabled = true;
      try {
        await api('/admin/tenants/' + tid + '/settings', {
          method: 'PUT',
          body: JSON.stringify({ worker_pool_size: size }),
        });
        toast('Пул воркеров сохранён', 'success');
      } catch (e) {
        toast(e.message, 'error');
      } finally {
        if (btn) btn.disabled = false;
      }
    }
    function esc(s) {
      return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }
    function escAttr(s) {
      return String(s ?? '').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }
    async function loadStats(tid) {
      const cell = document.getElementById('stats-' + tid);
      try {
        const s = await api('/admin/tenants/' + tid + '/stats');
        if (cell) {
          cell.innerHTML =
            `<span class="tabular-nums">групп: ${s.groups}, акк: ${s.profiles}, ✓${s.sent} ✗${s.failed}</span>`;
        }
      } catch (e) {
        if (cell) cell.innerHTML = '<span class="hint">' + esc(e.message || 'Ошибка') + '</span>';
        toast(e.message || 'Не удалось загрузить статистику', 'error');
      }
    }
    async function exitImpersonationStay() {
      try {
        await fetch('/api/auth/exit-impersonation', {
          method: 'POST',
          credentials: 'same-origin',
        });
      } catch (_) {}
      sessionStorage.removeItem('maxImpersonating');
    }
    async function loadGlobalSettings() {
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
    }
    async function saveGlobalSettings() {
      const btn = document.getElementById('btnSaveSettings');
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
      };
      if (btn) btn.disabled = true;
      try {
        await api('/settings', { method: 'PUT', body: JSON.stringify(body) });
        toast('Настройки сохранены', 'success');
        await loadGlobalSettings();
      } catch (e) {
        toast(e.message, 'error');
      } finally {
        if (btn) btn.disabled = false;
      }
    }
    async function loadAdminMessages() {
      const d = await api('/messages');
      const meta = document.getElementById('msgMeta');
      const preview = document.getElementById('msgPreview');
      const empty = document.getElementById('msgEmpty');
      meta.textContent = d.count
        ? `Загружено: ${d.count} · ${d.meta.loaded_at || ''}`
        : 'Файл не загружен';
      if (d.count) {
        preview.innerHTML = d.messages.map(m => `<li>${esc(m)}</li>`).join('');
        preview.style.display = 'block';
        empty.style.display = 'none';
      } else {
        preview.innerHTML = '';
        preview.style.display = 'none';
        empty.style.display = 'block';
      }
    }
    function formatFileSize(n) {
      if (n < 1024) return n + ' Б';
      if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' КБ';
      return (n / (1024 * 1024)).toFixed(1) + ' МБ';
    }
    function onAdminMsgFileChange() {
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
    async function uploadAdminMessages() {
      const input = document.getElementById('msgFile');
      const f = input && input.files[0];
      if (!f) {
        toast('Выберите файл', 'error');
        return;
      }
      if (!confirm('Заменить текущие сообщения?')) return;
      const btn = document.getElementById('btnUploadMessages');
      const orig = btn ? btn.textContent : '';
      if (btn) {
        btn.disabled = true;
        btn.textContent = 'Загрузка…';
      }
      try {
        const fd = new FormData();
        fd.append('file', f);
        const r = await api('/messages/upload', { method: 'POST', body: fd });
        input.value = '';
        onAdminMsgFileChange();
        const n = r && r.count != null ? r.count : 0;
        toast('Загружено ' + n + ' сообщений', 'success');
        await loadAdminMessages();
      } catch (e) {
        toast(e.message, 'error');
      } finally {
        if (btn) {
          btn.textContent = orig || 'Загрузить';
          onAdminMsgFileChange();
        }
      }
    }
    async function grantMonth(tid, name, btn) {
      const label = name || ('#' + tid);
      if (!confirm('Продлить подписку «' + label + '» на 30 дней?\n\nСрок увеличится от оставшихся дней, а не установится заново с сегодня.')) return;
      if (btn) btn.disabled = true;
      try {
        await api('/admin/users/' + tid + '/subscription/month', { method: 'POST' });
        toast('Подписка продлена на 30 дней от текущей даты окончания', 'success');
        await loadUsers();
      } catch (e) {
        toast(e.message, 'error');
      } finally {
        if (btn) btn.disabled = false;
      }
    }
    async function grantSubscriptionDays(tid, name, days, btn) {
      const label = name || ('#' + tid);
      const n = parseInt(days, 10);
      if (!n || n < 1) {
        toast('Укажите число дней (от 1)', 'error');
        return;
      }
      if (!confirm('Продлить подписку «' + label + '» на ' + n + ' дн.?\n\nСрок увеличится от оставшихся дней, а не установится заново с сегодня.')) return;
      if (btn) btn.disabled = true;
      try {
        await api('/admin/users/' + tid + '/subscription', {
          method: 'POST',
          body: JSON.stringify({ days: n }),
        });
        toast('Подписка продлена на ' + n + ' дн. от текущей даты окончания', 'success');
        await loadUsers();
      } catch (e) {
        toast(e.message, 'error');
      } finally {
        if (btn) btn.disabled = false;
      }
    }
    async function revokeSubscription(tid, name, btn) {
      const label = name || ('#' + tid);
      if (!confirm('Отозвать подписку «' + label + '»?\n\nРассылка для учреждения станет недоступна.')) return;
      if (btn) btn.disabled = true;
      try {
        await api('/admin/users/' + tid + '/subscription/revoke', { method: 'POST' });
        toast('Подписка отозвана', 'success');
        await loadUsers();
      } catch (e) {
        toast(e.message, 'error');
      } finally {
        if (btn) btn.disabled = false;
      }
    }
    async function impersonate(tid, name) {
      const label = name || ('#' + tid);
      if (!confirm('Открыть кабинет «' + label + '»?')) return;
      try {
        const j = await api('/admin/impersonate/' + tid, { method: 'POST' });
        sessionStorage.setItem('maxImpersonating', j.institution_name || '');
        location.href = '/';
      } catch (e) {
        toast(e.message || 'Не удалось открыть кабинет', 'error');
      }
    }
    async function deleteUser(tid, name, btn) {
      const label = name || ('#' + tid);
      if (!confirm('Удалить учреждение «' + label + '»?\n\nДанные, аккаунты и подписка будут удалены без восстановления.')) return;
      if (btn) btn.disabled = true;
      try {
        await api('/admin/users/' + tid, { method: 'DELETE' });
        toast('Учреждение удалено', 'success');
        await loadUsers();
      } catch (e) {
        toast(e.message || 'Не удалось удалить', 'error');
      } finally {
        if (btn) btn.disabled = false;
      }
    }
    const VALID_TABS = ['users', 'settings', 'messages'];
    const _tabLoaded = { settings: false, messages: false };

    function tabFromHash() {
      const h = location.hash.slice(1);
      return VALID_TABS.includes(h) ? h : 'users';
    }

    function syncTabHash(tabId) {
      const next = '#' + tabId;
      if (location.hash !== next) history.replaceState(null, '', next);
    }

    async function switchTab(tabId, { skipHash = false } = {}) {
      const btn = document.querySelector(`nav button[data-tab="${tabId}"]`);
      if (!btn) return;
      document.querySelectorAll('nav button').forEach(x => {
        x.classList.remove('active');
        x.setAttribute('aria-selected', 'false');
      });
      document.querySelectorAll('main > section').forEach(x => x.classList.remove('active'));
      btn.classList.add('active');
      btn.setAttribute('aria-selected', 'true');
      document.getElementById(tabId).classList.add('active');
      if (!skipHash) syncTabHash(tabId);
      if (tabId === 'settings' && !_tabLoaded.settings) {
        _tabLoaded.settings = true;
        await loadGlobalSettings();
      }
      if (tabId === 'messages' && !_tabLoaded.messages) {
        _tabLoaded.messages = true;
        await loadAdminMessages();
      }
    }

    function applyTabFromHash() {
      switchTab(tabFromHash(), { skipHash: true });
    }

    document.querySelectorAll('nav button').forEach(b => {
      b.addEventListener('click', () => switchTab(b.dataset.tab));
    });
    window.addEventListener('hashchange', () => applyTabFromHash());

    document.getElementById('btnLogout').addEventListener('click', logout);
    document.getElementById('btnGroupsOn').addEventListener('click', () => bulkGroups(1));
    document.getElementById('btnGroupsOff').addEventListener('click', () => bulkGroups(0));
    document.getElementById('btnLoadExpiring').addEventListener('click', loadExpiring);
    document.getElementById('btnSaveSettings').addEventListener('click', saveGlobalSettings);
    document.getElementById('msgFile').addEventListener('change', onAdminMsgFileChange);
    document.getElementById('btnUploadMessages').addEventListener('click', uploadAdminMessages);

    document.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-action]');
      if (!btn) return;
      const action = btn.dataset.action;
      if (action === 'logout') {
        logout();
        return;
      }
      const tid = parseInt(btn.dataset.tenantId, 10);
      const name = btn.dataset.institutionName || '';
      if (action === 'delete-user') deleteUser(tid, name, btn);
      else if (action === 'grant-month') grantMonth(tid, name, btn);
      else if (action === 'grant-days') {
        const inp = document.getElementById('sub-days-' + tid);
        grantSubscriptionDays(tid, name, inp && inp.value, btn);
      } else if (action === 'revoke-sub') revokeSubscription(tid, name, btn);
      else if (action === 'impersonate') impersonate(tid, name);
      else if (action === 'load-stats') loadStats(tid);
      else if (action === 'save-worker-pool') saveWorkerPool(tid, btn);
    });

    async function bulkGroups(active) {
      const on = active === 1;
      const msg = on
        ? 'Включить все группы у всех учреждений?\n\nОни снова будут участвовать в рассылке.'
        : 'Выключить все группы у всех учреждений?\n\nРассылка по ним не пойдёт, пока группы не включат снова.';
      if (!confirm(msg)) return;
      const hint = document.getElementById('bulkGroupsHint');
      const btnOn = document.getElementById('btnGroupsOn');
      const btnOff = document.getElementById('btnGroupsOff');
      btnOn.disabled = true;
      btnOff.disabled = true;
      hint.textContent = 'Выполняется…';
      try {
        const path = on ? '/admin/groups/activate-all' : '/admin/groups/deactivate-all';
        const r = await api(path, { method: 'POST' });
        hint.textContent = (on ? 'Включено' : 'Выключено') + ': '
          + r.groups_updated + ' групп у ' + r.tenants_processed + ' учреждений'
          + (r.skipped && r.skipped.length ? ' · пропущено ' + r.skipped.length : '');
      } catch (e) {
        hint.textContent = 'Ошибка: ' + e.message;
      } finally {
        btnOn.disabled = false;
        btnOff.disabled = false;
      }
    }
    (async () => {
      try {
        await tryRestoreSession();
        const me = await api('/auth/me');
        if (me.role !== 'admin') {
          document.querySelector('main').innerHTML =
            '<div class="panel">Этот аккаунт не администратор. <a href="/">Перейти в кабинет</a></div>';
          return;
        }
        document.getElementById('adminEmail').textContent = me.email;
        if (me.impersonating) {
          await exitImpersonationStay();
          location.reload();
          return;
        }
        await loadExpiring();
        applyTabFromHash();
        await loadUsers();
      } catch (e) {
        document.querySelector('main').innerHTML =
          '<div class="panel" style="color:var(--danger)">' +
          '<strong>Не удалось открыть админку</strong><br>' + esc(e.message) +
          '<p class="hint">Частая причина — старая версия сервера. На VDS: git pull && docker compose up --build -d</p>' +
          '<button class="btn" data-action="logout">Выйти и войти снова</button></div>';
      }
    })();
