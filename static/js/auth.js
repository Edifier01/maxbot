function showTab(name) {
  const isLogin = name === 'login';
  document.getElementById('panelLogin').classList.toggle('active', isLogin);
  document.getElementById('panelRegister').classList.toggle('active', !isLogin);
  document.getElementById('tabLogin').classList.toggle('active', isLogin);
  document.getElementById('tabRegister').classList.toggle('active', !isLogin);
  document.getElementById('tabLogin').classList.toggle('secondary', !isLogin);
  document.getElementById('tabRegister').classList.toggle('secondary', isLogin);
  document.getElementById('tabLogin').setAttribute('aria-selected', isLogin ? 'true' : 'false');
  document.getElementById('tabRegister').setAttribute('aria-selected', !isLogin ? 'true' : 'false');
}
function formatApiError(detail, fallback) {
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map(d => {
      if (!d) return '';
      if (typeof d === 'string') return d;
      return d.msg || '';
    }).filter(Boolean);
    return msgs.join('; ') || fallback;
  }
  if (typeof detail === 'object' && detail.msg) return detail.msg;
  return fallback;
}
function redirectByRole(role) {
  if (role === 'admin') location.href = '/admin.html';
  else location.href = '/';
}
async function withAuthLoading(btn, label, fn) {
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = label;
  try {
    await fn();
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}
async function doLogin() {
  const err = document.getElementById('loginErr');
  const btn = document.getElementById('btnLogin');
  err.textContent = '';
  await withAuthLoading(btn, 'Вход…', async () => {
    try {
      const r = await fetch('/api/auth/login', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: document.getElementById('loginEmail').value.trim(),
          password: document.getElementById('loginPass').value,
          remember_me: document.getElementById('rememberMeLogin').checked,
        }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(formatApiError(j.detail, 'Ошибка входа'));
      redirectByRole(j.role);
    } catch (e) { err.textContent = e.message; }
  });
}
async function doRegister() {
  const err = document.getElementById('regErr');
  const btn = document.getElementById('btnRegister');
  err.textContent = '';
  const pass = document.getElementById('regPass').value;
  const pass2 = document.getElementById('regPass2').value;
  if (pass !== pass2) {
    err.textContent = 'Пароли не совпадают';
    return;
  }
  await withAuthLoading(btn, 'Регистрация…', async () => {
    try {
      const r = await fetch('/api/auth/register', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          institution_name: document.getElementById('regInstitution').value.trim(),
          email: document.getElementById('regEmail').value.trim(),
          password: pass,
          password_confirm: pass2,
          remember_me: document.getElementById('rememberMeRegister').checked,
        }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(formatApiError(j.detail, 'Ошибка регистрации'));
      location.href = '/';
    } catch (e) { err.textContent = e.message; }
  });
}
async function tryRestoreSession() {
  try {
    const r = await fetch('/api/auth/restore-session', {
      method: 'POST',
      credentials: 'include',
    });
    if (!r.ok) return false;
    const j = await r.json();
    redirectByRole(j.role);
    return true;
  } catch (_) {
    return false;
  }
}
document.getElementById('tabLogin').addEventListener('click', () => showTab('login'));
document.getElementById('tabRegister').addEventListener('click', () => showTab('register'));
document.getElementById('formLogin').addEventListener('submit', (event) => {
  event.preventDefault();
  doLogin();
});
document.getElementById('formRegister').addEventListener('submit', (event) => {
  event.preventDefault();
  doRegister();
});
(async () => {
  const h = await fetch('/api/health').then(r => r.json()).catch(() => ({}));
  if (!h.server_mode) { location.href = '/'; return; }
  await tryRestoreSession();
})();
