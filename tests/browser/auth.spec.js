const { test, expect } = require('./fixtures');

test.describe('auth surface', () => {
  test.beforeEach(async ({ page, diagnostics }) => {
    diagnostics.allowResponse('/api/auth/restore-session');
    diagnostics.allowResponse('/api/auth/login');
    diagnostics.allowConsoleError(/status of 401/);

    await page.route('**/api/health', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, server_mode: true }),
    }));
    await page.route('**/api/auth/restore-session', (route) => route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Сессия отсутствует' }),
    }));
    await page.route('**/api/auth/login', (route) => route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Локальная fixture: отказано' }),
    }));
  });

  test('renders identity and a usable keyboard login flow', async ({ page }) => {
    await page.goto('/auth.html');

    await expect(page).toHaveTitle('MAX Sender — Вход');
    await expect(page.getByRole('heading', { name: 'MAX Sender' })).toBeVisible();
    await expect(page.getByLabel('Логин')).toBeVisible();
    await expect(page.getByLabel('Пароль')).toBeVisible();
    await expect(page.locator('main.card')).toBeVisible();

    await page.getByLabel('Логин').focus();
    await expect(page.getByLabel('Логин')).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.getByLabel('Пароль')).toBeFocused();

    await page.getByLabel('Логин').fill('browser-fixture');
    await page.getByLabel('Пароль').fill('invalid-fixture-password');
    await page.getByLabel('Пароль').press('Enter');
    await expect(page.locator('#loginErr')).toHaveText('Локальная fixture: отказано');
    await expect(page.locator('#loginErr')).toBeVisible();
  });
});
