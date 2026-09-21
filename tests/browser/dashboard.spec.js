const { test, expect } = require('./fixtures');

const holdLog = 'Recovery hold: внешние действия удержаны локальной fixture';

function fixturePayload(pathname) {
  if (pathname === '/api/health') {
    return {
      ok: true,
      server_mode: false,
      max_external_actions: 'held',
      recovery_hold: true,
    };
  }
  if (pathname === '/api/vault/status') {
    return { unlocked: false, needs_setup: true, legacy: false };
  }
  if (pathname === '/api/messages') return { count: 0, messages: [], meta: {} };
  if (pathname === '/api/groups') return [];
  if (pathname === '/api/settings/audit') return { items: [] };
  if (pathname === '/api/settings') return {};
  if (pathname === '/api/campaign/schedule') return { enabled: false, start_at: null };
  if (pathname === '/api/backups') return { items: [] };
  if (pathname === '/api/send_log') return { items: [], total: 0, limit: 30, offset: 0 };
  if (pathname === '/api/campaigns') return { items: [] };
  if (pathname === '/api/dashboard') {
    return {
      counts: {},
      groups_count: 0,
      sent_today: 0,
      failed_today: 0,
      circuit_open: 0,
      items: [],
    };
  }
  if (pathname === '/api/status') {
    return {
      running: false,
      auto_run: false,
      messages_count: 0,
      log: [holdLog],
      activity: [],
      vault: { unlocked: false, needs_setup: true, legacy: false },
      circuit_open: 0,
      profiles: {},
      campaign_progress: {},
    };
  }
  return {};
}

test.describe('dashboard surface', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/**', async (route) => {
      const pathname = new URL(route.request().url()).pathname;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixturePayload(pathname)),
      });
    });
    await page.routeWebSocket('**/ws/status', (webSocket) => webSocket.close());
  });

  test('renders the dashboard and visible recovery hold across keyboard flow', async ({ page }) => {
    await page.goto('/');

    await expect(page).toHaveTitle('MAX Sender');
    await expect(page.getByRole('heading', { name: 'MAX Sender' })).toBeVisible();
    await expect(page.locator('#campaign')).toBeVisible();
    await expect(page.locator('#campaignLog')).toContainText(holdLog);
    await expect(page.locator('main#main-content')).not.toHaveText('');

    const campaignTab = page.locator('#tab-campaign');
    const messagesTab = page.locator('#tab-messages');
    await campaignTab.focus();
    await expect(campaignTab).toBeFocused();
    await page.keyboard.press('ArrowRight');
    await expect(messagesTab).toBeFocused();
    await expect(messagesTab).toHaveAttribute('aria-selected', 'true');
    await page.keyboard.press('ArrowLeft');
    await expect(campaignTab).toBeFocused();
    await expect(campaignTab).toHaveAttribute('aria-selected', 'true');
  });

  test('exposes a recoverable summary error when the dashboard is unavailable', async ({ page, diagnostics }) => {
    diagnostics.allowResponse('/api/dashboard', [503]);
    diagnostics.allowConsoleError(/status of 503/);
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
        subscription: { active: true },
      }),
    }));
    await page.route('**/api/dashboard', (route) => route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: { code: 'SERVER_UNAVAILABLE' } }),
    }));

    await page.goto('/');

    const summaryError = page.locator('#dashSummaryError');
    await expect(summaryError).toBeVisible();
    await expect(summaryError).toHaveAttribute('role', 'alert');
    await expect(summaryError).toContainText('Сервис временно недоступен');
  });
});
