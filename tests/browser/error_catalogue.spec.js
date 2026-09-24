const fs = require('fs');
const path = require('path');
const { test, expect } = require('./fixtures');

const contract = fs.readFileSync(
  path.join(__dirname, '..', '..', 'docs', 'ui-ux-contract.md'),
  'utf8',
);
const ERROR_ROWS = contract
  .split('\n')
  .filter((line) => line.startsWith('| ') && !line.startsWith('| Code'))
  .map((line) => line.split('|').map((part) => part.trim()).filter(Boolean))
  .filter(([code, action]) => code && action && code !== '---')
  .map(([code, action]) => ({ code, action }));
const ERROR_CODES = ERROR_ROWS.map(({ code }) => code);
const ERROR_ACTIONS = Object.fromEntries(ERROR_ROWS.map(({ code, action }) => [code, action]));
const ACTION_CODES = [...new Set(ERROR_CODES.map((code) => ERROR_ACTIONS[code]))]
  .map((action) => ERROR_CODES.find((code) => ERROR_ACTIONS[code] === action));

function errorDetail(code, stage) {
  return {
    code,
    source: 'http',
    stage,
    safe_message: `Безопасное сообщение ${code}`,
    recommended_action: ERROR_ACTIONS[code],
    retryable: false,
    session_preserved: 'raw-secret-preservation-metadata',
    request_id: `raw-secret-request-${code}`,
    attempt_id: `raw-secret-attempt-${code}`,
    operation_id: `raw-secret-operation-${code}`,
    retry_after_at: 'raw-secret-retry-after',
    raw_message: `raw-secret-${code}`,
  };
}

function dashboardPayload(pathname) {
  if (pathname === '/api/health') {
    return { ok: true, server_mode: false, max_external_actions: 'held', recovery_hold: true };
  }
  if (pathname === '/api/vault/status') return { unlocked: false, needs_setup: true, legacy: false };
  if (pathname === '/api/messages') return { count: 0, messages: [], meta: {} };
  if (pathname === '/api/groups') return [];
  if (pathname === '/api/settings/audit') return { items: [] };
  if (pathname === '/api/settings') return {};
  if (pathname === '/api/campaign/schedule') return { enabled: false, start_at: null };
  if (pathname === '/api/backups') return { items: [] };
  if (pathname === '/api/send_log') return { items: [], total: 0, limit: 30, offset: 0 };
  if (pathname === '/api/campaigns') return { items: [] };
  if (pathname === '/api/status') {
    return {
      running: false,
      auto_run: false,
      messages_count: 0,
      log: ['Recovery hold: внешние действия удержаны локальной fixture'],
      activity: [],
      vault: { unlocked: false, needs_setup: true, legacy: false },
      circuit_open: 0,
      profiles: {},
      campaign_progress: {},
    };
  }
  return {};
}

test.describe('structured error catalogue', () => {
  test.beforeEach(async ({ page, diagnostics }) => {
    diagnostics.allowResponse('/api/dashboard', [409]);
    diagnostics.allowResponse('/api/admin/users', [409]);
    diagnostics.allowConsoleError(/status of 409/);

    await page.route('**/api/**', async (route) => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname === '/api/dashboard') {
        const code = route.request().headers()['x-fixture-error-code'] || 'AUTH_REQUIRED';
        await route.fulfill({
            status: 409,
            contentType: 'application/json',
            body: JSON.stringify({
              detail: errorDetail(code, 'dashboard'),
            }),
          });
        return;
      }
      if (pathname === '/api/auth/me') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ role: 'admin', email: 'fixture@example.test', impersonating: false }),
        });
        return;
      }
      if (pathname === '/api/admin/users') {
        const code = route.request().headers()['x-fixture-error-code'] || 'AUTH_REQUIRED';
        await route.fulfill({
            status: 409,
            contentType: 'application/json',
            body: JSON.stringify({
              detail: errorDetail(code, 'admin'),
            }),
          });
        return;
      }
      if (pathname === '/api/admin/subscriptions/expiring') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ items: [] }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(dashboardPayload(pathname)),
      });
    });
    await page.routeWebSocket('**/ws/status', (webSocket) => webSocket.close());
  });

  test('user renderer preserves safe messages for every catalogue code', async ({ page }, testInfo) => {
    expect(ERROR_CODES).toHaveLength(66);

    await page.route('**/api/health', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, server_mode: true }),
    }));
    await page.route('**/api/auth/restore-session', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    }));
    await page.route('**/api/auth/me', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        role: 'user',
        email: 'cabinet@example.test',
        impersonating: false,
        subscription: { active: true },
      }),
    }));

    for (const code of ERROR_CODES) {
      await page.setExtraHTTPHeaders({ 'X-Fixture-Error-Code': code });
      await page.goto('/');
      const error = page.locator('#dashSummaryError');
      await expect(error).toBeVisible();
      await expect(error).toContainText(`Безопасное сообщение ${code}`);
      await expect(error).not.toContainText(`raw-secret-${code}`);
      await expect(error).toHaveAttribute('data-error-code', code);
      await expect(error).toHaveAttribute('data-error-source', 'http');
      await expect(error).toHaveAttribute('data-error-stage', 'dashboard');
      await expect(error).toHaveAttribute('data-error-action', ERROR_ACTIONS[code]);
      await expect(error).not.toHaveAttribute('data-error-session-preserved');
      await expect(error.locator('[data-action="error-action"]'))
        .toHaveAttribute('data-error-action', ERROR_ACTIONS[code]);
      if (code === ERROR_CODES[0]) {
        await testInfo.attach(`user-error-${testInfo.project.name}.png`, {
          body: await page.screenshot(),
          contentType: 'image/png',
        });
      }
    }
  });

  test('impersonation renderer preserves safe messages and action metadata', async ({ page }, testInfo) => {
    expect(ERROR_CODES).toHaveLength(66);

    await page.route('**/api/health', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, server_mode: true }),
    }));
    await page.route('**/api/auth/restore-session', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    }));
    await page.route('**/api/auth/me', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        role: 'admin',
        email: 'admin@example.test',
        impersonating: true,
        institution_name: 'Fixture tenant',
        subscription: { active: true },
      }),
    }));

    for (const code of ERROR_CODES) {
      await page.setExtraHTTPHeaders({ 'X-Fixture-Error-Code': code });
      await page.goto('/');
      const error = page.locator('#dashSummaryError');
      await expect(page.locator('#serverBanner')).toContainText('Режим админа: кабинет');
      await expect(error).toBeVisible();
      await expect(error).toContainText(`Безопасное сообщение ${code}`);
      await expect(error).not.toContainText(`raw-secret-${code}`);
      await expect(error).toHaveAttribute('data-error-action', ERROR_ACTIONS[code]);
      await expect(error.locator('[data-action="error-action"]'))
        .toHaveAttribute('data-error-action', ERROR_ACTIONS[code]);
      if (code === ERROR_CODES[0]) {
        await testInfo.attach(`impersonation-error-${testInfo.project.name}.png`, {
          body: await page.screenshot(),
          contentType: 'image/png',
        });
      }
    }
  });

  test('admin renderer preserves safe messages for every catalogue code', async ({ page }, testInfo) => {
    expect(ERROR_CODES).toHaveLength(66);

    for (const code of ERROR_CODES) {
      await page.setExtraHTTPHeaders({ 'X-Fixture-Error-Code': code });
      await page.goto('/admin.html');
      await expect(page.locator('main [data-error-code]')).toBeVisible();
      await expect(page.locator('main')).toContainText(`Безопасное сообщение ${code}`);
      await expect(page.locator('main')).not.toContainText(`raw-secret-${code}`);
      await expect(page.locator('main [data-action="error-action"]'))
        .toHaveAttribute('data-error-action', ERROR_ACTIONS[code]);
      if (code === ERROR_CODES[0]) {
        await testInfo.attach(`admin-error-${testInfo.project.name}.png`, {
          body: await page.screenshot(),
          contentType: 'image/png',
        });
      }
    }
  });

  test('unknown structured codes use the conservative UNCLASSIFIED fallback', async ({ page }, testInfo) => {
    await page.setExtraHTTPHeaders({ 'X-Fixture-Error-Code': 'UNKNOWN_CODE' });

    await page.goto('/');
    await expect(page.locator('#dashSummaryError')).toContainText('Операция не выполнена');
    await expect(page.locator('#dashSummaryError')).toHaveAttribute('data-error-code', 'UNCLASSIFIED');
    await expect(page.locator('#dashSummaryError [data-action="error-action"]'))
      .toHaveAttribute('data-error-action', 'REVIEW_OPERATION');
    await expect(page.locator('#dashSummaryError')).not.toContainText('raw-secret-UNKNOWN_CODE');
    await expect(page.locator('#dashSummaryError')).not.toContainText('Безопасное сообщение UNKNOWN_CODE');
    await testInfo.attach(`unknown-error-user-${testInfo.project.name}.png`, {
      body: await page.screenshot(),
      contentType: 'image/png',
    });

    await page.goto('/admin.html');
    await expect(page.locator('main')).toContainText('Операция не выполнена');
    await expect(page.locator('main')).not.toContainText('raw-secret-UNKNOWN_CODE');
    await expect(page.locator('main')).not.toContainText('Безопасное сообщение UNKNOWN_CODE');
    await expect(page.locator('main [data-action="error-action"]'))
      .toHaveAttribute('data-error-action', 'REVIEW_OPERATION');
    await testInfo.attach(`unknown-error-admin-${testInfo.project.name}.png`, {
      body: await page.screenshot(),
      contentType: 'image/png',
    });
  });

  test('every normalized action token is explicit, safe, and invoked without provider traffic', async ({ page, diagnostics }, testInfo) => {
    test.skip(testInfo.project.name !== '390x844', 'action invocation is bound to one viewport');
    diagnostics.allowFailedRequest('/');
    diagnostics.allowResponse('/api/auth/restore-session', [401]);
    diagnostics.allowConsoleError(/status of 401/);
    await page.route('**/api/health', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, server_mode: true }),
    }));
    await page.route('**/api/auth/restore-session', (route) => route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'fixture: session absent' }),
    }));
    await page.route('**/api/auth/me', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        role: 'user',
        email: 'cabinet@example.test',
        impersonating: false,
        subscription: { active: true },
      }),
    }));

    for (const code of ACTION_CODES) {
      await page.setExtraHTTPHeaders({ 'X-Fixture-Error-Code': code });
      await page.goto('/');
      const button = page.locator('#dashSummaryError [data-action="error-action"]');
      await expect(button).toHaveAttribute('data-error-action', ERROR_ACTIONS[code]);
      if (['AUTHENTICATE', 'REAUTHENTICATE', 'REVIEW_SESSION'].includes(ERROR_ACTIONS[code])) {
        await Promise.all([
          page.waitForURL('**/auth.html'),
          button.click(),
        ]);
        await page.waitForLoadState('domcontentloaded');
        continue;
      }
      await button.click();
      await expect(page.locator('body'))
        .toHaveAttribute('data-last-error-action', ERROR_ACTIONS[code]);
      await expect(page.locator('body')).not.toContainText('raw-secret-' + code);
    }
  });

  test('admin and impersonation surfaces invoke every normalized action token safely', async ({ page, diagnostics }, testInfo) => {
    test.skip(testInfo.project.name !== '390x844', 'role action invocation is bound to one viewport');
    diagnostics.allowFailedRequest('/');
    diagnostics.allowResponse('/api/auth/restore-session', [401]);
    diagnostics.allowConsoleError(/status of 401/);

    await page.route('**/api/health', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, server_mode: true }),
    }));
    await page.route('**/api/auth/restore-session', (route) => route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'fixture: session absent' }),
    }));

    const surfaces = [
      {
        path: '/admin.html',
        me: { role: 'admin', email: 'admin@example.test', impersonating: false },
        selector: 'main [data-action="error-action"]',
      },
      {
        path: '/',
        me: {
          role: 'admin',
          email: 'admin@example.test',
          impersonating: true,
          institution_name: 'Fixture tenant',
          subscription: { active: true },
        },
        selector: '#dashSummaryError [data-action="error-action"]',
      },
    ];

    for (const surface of surfaces) {
      await page.route('**/api/auth/me', (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(surface.me),
      }));
      for (const code of ACTION_CODES) {
        await page.setExtraHTTPHeaders({ 'X-Fixture-Error-Code': code });
        await page.goto(surface.path);
        const button = page.locator(surface.selector);
        await expect(button).toHaveAttribute('data-error-action', ERROR_ACTIONS[code]);
        if (['AUTHENTICATE', 'REAUTHENTICATE', 'REVIEW_SESSION'].includes(ERROR_ACTIONS[code])) {
          await button.click();
          await expect(page).toHaveURL(/\/auth\.html$/);
          await page.waitForLoadState('domcontentloaded');
          continue;
        }
        await button.click();
        if (surface.path === '/admin.html') {
          await expect(page.locator('main [data-error-code]'))
            .toHaveAttribute('data-error-action-invoked', ERROR_ACTIONS[code]);
        } else {
          await expect(page.locator('body'))
            .toHaveAttribute('data-last-error-action', ERROR_ACTIONS[code]);
        }
        await expect(page.locator('body')).not.toContainText('raw-secret-' + code);
      }
      await page.unroute('**/api/auth/me');
    }
  });

  test('reconcile and wait actions never trigger mutation or auth retries', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== '390x844', 'bounded action semantics use one viewport');
    const requests = [];
    page.on('request', (request) => {
      const url = new URL(request.url());
      requests.push({ method: request.method(), pathname: url.pathname });
    });

    await page.route('**/api/health', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, server_mode: true }),
    }));
    await page.route('**/api/auth/restore-session', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    }));
    await page.route('**/api/auth/me', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        role: 'user',
        email: 'cabinet@example.test',
        impersonating: false,
        subscription: { active: true },
      }),
    }));

    for (const code of ['COMMAND_STATE_UNKNOWN', 'MAX_RATE_LIMIT', 'API_RATE_LIMIT']) {
      await page.setExtraHTTPHeaders({ 'X-Fixture-Error-Code': code });
      await page.goto('/');
      const button = page.locator('#dashSummaryError [data-action="error-action"]');
      await expect(button).toHaveAttribute('data-error-action', ERROR_ACTIONS[code]);
      requests.length = 0;
      await button.click();
      await expect(page.locator('body')).toHaveAttribute(
        'data-last-error-action',
        ERROR_ACTIONS[code],
      );
      const forbidden = requests.filter(({ method, pathname }) => (
        method !== 'GET' && [
          '/api/campaign/retry_failed',
          '/api/campaign/test',
          '/api/campaign/start',
          '/api/auth/request-code',
          '/api/auth/verify-code',
        ].includes(pathname)
      ));
      expect(forbidden).toEqual([]);
      if (code === 'COMMAND_STATE_UNKNOWN') {
        expect(requests).toContainEqual({ method: 'GET', pathname: '/api/send_log' });
      }
    }
  });

  test('stale dashboard error cannot overwrite a newer successful snapshot', async ({ page }, testInfo) => {
    let calls = 0;
    let releaseFirst;
    const firstResponse = new Promise((resolve) => { releaseFirst = resolve; });

    await page.route('**/api/dashboard', async (route) => {
      calls += 1;
      if (calls === 1) {
        await firstResponse;
        await route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({ detail: errorDetail('SERVER_UNAVAILABLE', 'dashboard') }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          counts: { active: 7 },
          groups_count: 1,
          sent_today: 0,
          failed_today: 0,
          circuit_open: 0,
          items: [],
        }),
      });
    });

    await page.goto('/');
    await page.getByRole('tab', { name: 'Сообщения' }).click();
    await page.getByRole('tab', { name: 'Рассылка' }).click();
    await expect.poll(() => calls).toBeGreaterThan(1);
    releaseFirst();

    await expect(page.locator('#dashStats')).toContainText('7');
    await expect(page.locator('#dashSummaryError')).toBeHidden();
    await testInfo.attach(`stale-dashboard-${testInfo.project.name}.png`, {
      body: await page.screenshot(),
      contentType: 'image/png',
    });
  });
});
