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

async function routeProfileAuthFixture(page, mode) {
  const state = { profileReads: 0 };
  await page.unroute('**/api/**');
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === '/api/groups') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([{
          id: 1,
          name: 'Fixture group',
          invite_link: 'https://example.test/fixture',
          profiles_count: 1,
          active_count: 0,
          is_active: 1,
        }]),
      });
      return;
    }
    if (pathname === '/api/groups/1/profiles') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [{
            id: 7,
            phone: '+70000000007',
            status: 'pending',
            auth_step: 'idle',
            last_error: '',
            circuit_open: false,
          }],
          total: 1,
          limit: 20,
          offset: 0,
        }),
      });
      return;
    }
    if (pathname === '/api/profiles/7/automation-scope') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
      return;
    }
    if (pathname === '/api/profiles/7/login') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ message: 'Вход запущен', auth_step: 'connecting' }),
      });
      return;
    }
    if (pathname === '/api/profiles/7') {
      state.profileReads += 1;
      if (mode === 'network') {
        await route.abort('failed');
        return;
      }
      const status = mode === 'server' ? 503 : 429;
      const detail = mode === 'server'
        ? { code: 'SERVER_UNAVAILABLE' }
        : { code: 'API_RATE_LIMIT', safe_message: 'Слишком много запросов к кабинету' };
      await route.fulfill({
        status,
        headers: mode === 'rate' ? { 'Retry-After': '7' } : {},
        contentType: 'application/json',
        body: JSON.stringify({ detail }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(fixturePayload(pathname)),
    });
  });
  return state;
}

async function beginFixtureLogin(page) {
  await page.goto('/');
  await page.getByRole('tab', { name: 'Группы' }).click();
  await page.getByRole('button', { name: /Fixture group/ }).click();
  await expect(page.getByText('+70000000007')).toBeVisible();
  await page.getByRole('table').getByRole('button', { name: 'Войти', exact: true }).click();
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

  test('shows user readiness and safe attention actions without offering login for a banned account', async ({ page }) => {
    await page.unroute('**/api/**');
    const state = { previewCalls: [], loginCalls: [], scopeCalls: [] };
    await page.route('**/api/**', async (route) => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      if (pathname === '/api/health') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, server_mode: true }) });
        return;
      }
      if (pathname === '/api/auth/restore-session') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
        return;
      }
      if (pathname === '/api/auth/me') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ role: 'user', subscription: { active: true } }) });
        return;
      }
      if (pathname === '/api/dashboard/attention') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
          items: [
            { id: 8, phone: '+70000000008', label: 'Заблокированный', status: 'banned', last_error: 'Аккаунт заблокирован платформой', primary_group_id: 2, linked_group_count: 1 },
            { id: 9, phone: '+70000000009', status: 'needs_reauth', last_error: 'Требуется повторный вход', primary_group_id: 2, linked_group_count: 1 },
          ], total: 2, offset: 0, limit: 10,
        }) });
        return;
      }
      if (pathname === '/api/campaign/preview') {
        state.previewCalls.push(request.method());
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
          ok: false, readiness_revision: 'fixture-revision', blockers: ['groups', 'profiles', 'recovery_hold_active'], warnings: [],
          selection: { groups: [], profiles: [], library_count: 0 },
        }) });
        return;
      }
      if (pathname === '/api/profiles/9/automation-scope') {
        state.scopeCalls.push(request.method());
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
        return;
      }
      if (pathname === '/api/profiles/9/login') {
        state.loginCalls.push(request.method());
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ message: 'Вход начат', auth_step: 'connecting' }) });
        return;
      }
      if (pathname === '/api/profiles/9') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 9, status: 'active', auth_step: 'idle' }) });
        return;
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixturePayload(pathname)) });
    });

    await page.goto('/');
    const readiness = page.locator('#campaignReadinessPanel');
    await expect(readiness).toBeVisible();
    await expect(readiness).toContainText('Нет активной группы');
    await expect(readiness).toContainText('Нет активного авторизованного аккаунта');
    await expect(readiness).not.toContainText('recovery_hold_active');
    await expect(page.locator('#btnStart')).toBeDisabled();

    const attention = page.locator('#attentionList');
    await expect(attention).toContainText('Заблокированный');
    await expect(attention).toContainText('Рассылка остановлена');
    const banned = attention.locator('[data-profile-id="8"]');
    await expect(banned.getByRole('button', { name: 'Войти' })).toHaveCount(0);
    const reauth = attention.locator('[data-profile-id="9"]');
    await expect(reauth.getByRole('button', { name: 'Войти' })).toBeVisible();
    expect(state.previewCalls).toContain('POST');
    await reauth.getByRole('button', { name: 'Войти' }).click();
    await expect.poll(() => state.loginCalls.length).toBe(1);
    expect(state.scopeCalls).toEqual(['PUT']);
  });

  test('exposes a recoverable summary error when the dashboard is unavailable', async ({ page, diagnostics }, testInfo) => {
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
    await testInfo.attach(`summary-error-${testInfo.project.name}.png`, {
      body: await page.screenshot(),
      contentType: 'image/png',
    });
  });

  test('renders the server-provided redacted catalogue message', async ({ page, diagnostics }, testInfo) => {
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
      body: JSON.stringify({ role: 'user', subscription: { active: true } }),
    }));
    await page.route('**/api/dashboard', (route) => route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: {
          code: 'SETTINGS_NOT_LOADED',
          safe_message: 'Настройки ещё не загружены.',
          recommended_action: 'RELOAD_SETTINGS',
        },
      }),
    }));

    await page.goto('/');

    const summaryError = page.locator('#dashSummaryError');
    await expect(summaryError).toContainText('Настройки ещё не загружены.');
    await expect(summaryError).not.toContainText('raw-secret');
    await testInfo.attach(`redacted-error-${testInfo.project.name}.png`, {
      body: await page.screenshot(),
      contentType: 'image/png',
    });
  });

  test('requires and records explicit destination confirmation before a send-ready group state', async ({ page }) => {
    await page.unroute('**/api/**');
    const state = { verified: false, request: null };
    await page.route('**/api/**', async (route) => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      if (pathname === '/api/health') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, server_mode: true }) });
        return;
      }
      if (pathname === '/api/auth/restore-session') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
        return;
      }
      if (pathname === '/api/auth/me') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ role: 'user', subscription: { active: true } }) });
        return;
      }
      if (pathname === '/api/groups') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([{
            id: 1,
            name: 'Destination review group',
            invite_link: 'https://example.test/changed',
            max_chat_id: state.verified ? '12345' : '',
            destination_revision: 2,
            destination_verified: state.verified ? 1 : 0,
            profiles_count: 0,
            active_count: 0,
            is_active: 1,
          }]),
        });
        return;
      }
      if (pathname === '/api/groups/1/profiles') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ items: [], total: 0, limit: 20, offset: 0 }),
        });
        return;
      }
      if (pathname === '/api/groups/1/destination/verify') {
        state.request = JSON.parse(request.postData() || '{}');
        state.verified = true;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 1,
            name: 'Destination review group',
            invite_link: 'https://example.test/changed',
            max_chat_id: '12345',
            destination_revision: 2,
            destination_verified: 1,
            profiles_count: 0,
            active_count: 0,
            is_active: 1,
          }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixturePayload(pathname)),
      });
    });

    await page.goto('/');
    await page.getByRole('tab', { name: 'Группы' }).click();
    await page.getByRole('button', { name: /Destination review group/ }).click();
    await expect(page.getByText('Назначение требует явного подтверждения перед рассылкой.')).toBeVisible();

    await page.getByLabel('Подтверждённый ID назначения').fill('12345');
    await page.getByRole('button', { name: 'Подтвердить назначение' }).click();
    await expect.poll(() => state.request).toEqual({ chat_id: '12345', revision: 2 });
    await expect(page.getByText('Назначение подтверждено · revision 2')).toBeVisible();
  });

  test('keeps readiness preview read-only and binds its revision to explicit start', async ({ page }) => {
    await page.unroute('**/api/**');
    const state = { previews: 0, previewMethods: [], starts: 0, startBody: null, unsafeCalls: [] };
    await page.route('**/api/**', async (route) => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      if (pathname === '/api/health') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, server_mode: true }) });
        return;
      }
      if (pathname === '/api/auth/restore-session') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
        return;
      }
      if (pathname === '/api/auth/me') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ role: 'user', subscription: { active: true } }) });
        return;
      }
      if (pathname === '/api/campaign/preview') {
        state.previews += 1;
        state.previewMethods.push(request.method());
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ok: true,
            state: 'ready',
            blockers: [],
            warnings: ['daily_plans_materialize_on_start'],
            selection: { groups: [1], profiles: [7], library_count: 5 },
            readiness_revision: 'fixture-readiness-revision-1',
          }),
        });
        return;
      }
      if (pathname === '/api/campaign/start') {
        state.starts += 1;
        state.startBody = request.postDataJSON();
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true, state: 'running' }),
        });
        return;
      }
      if (request.method() !== 'GET' && pathname !== '/api/auth/restore-session') {
        state.unsafeCalls.push({ method: request.method(), pathname });
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixturePayload(pathname)),
      });
    });

    await page.goto('/');
    await expect(page.getByText('Готово к запуску.')).toBeVisible();
    const initialPreviewCount = state.previews;
    expect(initialPreviewCount).toBeGreaterThanOrEqual(1);
    await page.getByRole('button', { name: 'Обновить проверку' }).click();
    await expect(page.getByText('Готово к запуску.')).toBeVisible();
    await expect(page.getByText('Групп: 1 · аккаунтов: 1 · сообщений: 5')).toBeVisible();
    expect(state.previews).toBe(initialPreviewCount + 1);
    expect(state.starts).toBe(0);
    expect(state.previewMethods).toEqual(Array(state.previews).fill('POST'));
    expect(state.unsafeCalls).toEqual([]);

    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: 'Старт', exact: true }).click();
    await expect.poll(() => state.startBody).toEqual({
      readiness_revision: 'fixture-readiness-revision-1',
    });
    expect(state.starts).toBe(1);
  });

  test('reconciles a lost start response from the same persisted command receipt', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== '390x844', 'command receipt lifecycle is bound to one viewport');
    await page.unroute('**/api/**');
    const state = { startIds: [], statusQueries: [] };
    await page.route('**/api/**', async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.pathname === '/api/health') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, server_mode: true }) });
        return;
      }
      if (url.pathname === '/api/auth/restore-session') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
        return;
      }
      if (url.pathname === '/api/auth/me') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ role: 'user', subscription: { active: true } }),
        });
        return;
      }
      if (url.pathname === '/api/campaign/preview') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ok: true,
            readiness_revision: 'fixture-command-readiness-revision',
            blockers: [],
            warnings: [],
            selection: { groups: [1], profiles: [7], library_count: 1 },
          }),
        });
        return;
      }
      if (url.pathname === '/api/campaign/start') {
        state.startIds.push(request.headers()['x-request-id'] || null);
        await route.abort('failed');
        return;
      }
      if (url.pathname === '/api/campaign/command-status') {
        state.statusQueries.push({
          command: url.searchParams.get('command'),
          requestId: url.searchParams.get('request_id'),
        });
        const status = state.statusQueries.length === 1 ? 'preflight' : 'running';
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ known: true, command: 'start', state: status, accepted: true, generation: 4 }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixturePayload(url.pathname)),
      });
    });

    await page.goto('/');
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: 'Старт', exact: true }).click();

    expect(state.startIds).toHaveLength(1);
    expect(state.startIds[0]).toBeTruthy();
    const recovery = page.locator('#campaignCommandRecovery');
    await expect(recovery).toBeVisible();
    await expect(recovery).toContainText('preflight');
    expect(state.statusQueries).toEqual([{
      command: 'start',
      requestId: state.startIds[0],
    }]);

    await page.reload();
    await expect.poll(() => state.statusQueries.length).toBe(2);
    await expect(recovery).toContainText('running');
    expect(state.statusQueries[1]).toEqual(state.statusQueries[0]);
    expect(state.startIds).toHaveLength(1);
  });

  test('keeps an ambiguous test send unresolved and never posts it again', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== '390x844', 'test-send ambiguity is bound to one viewport');
    await page.unroute('**/api/**');
    const state = { testIds: [], statusQueries: [] };
    await page.route('**/api/**', async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.pathname === '/api/health') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, server_mode: false }) });
        return;
      }
      if (url.pathname === '/api/auth/restore-session') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
        return;
      }
      if (url.pathname === '/api/auth/me') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ role: 'user', email: 'fixture-user@example.test', subscription: { active: true } }),
        });
        return;
      }
      if (url.pathname === '/api/campaign/test') {
        state.testIds.push(request.headers()['x-request-id'] || null);
        await route.abort('failed');
        return;
      }
      if (url.pathname === '/api/campaign/command-status') {
        state.statusQueries.push({
          command: url.searchParams.get('command'),
          requestId: url.searchParams.get('request_id'),
        });
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ known: true, command: 'test', state: 'unknown', accepted: false, generation: 2 }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixturePayload(url.pathname)),
      });
    });

    await page.goto('/');
    await page.locator('details.campaign-more summary').click();
    await page.getByRole('button', { name: 'Тест', exact: true }).click();
    const recovery = page.locator('#campaignCommandRecovery');
    await expect(recovery).toBeVisible();
    await expect(recovery).toContainText('unknown');
    expect(state.testIds).toHaveLength(1);
    expect(state.testIds[0]).toBeTruthy();
    expect(state.statusQueries).toEqual([{
      command: 'test',
      requestId: state.testIds[0],
    }]);

    await page.reload();
    await expect.poll(() => state.statusQueries.length).toBe(2);
    await expect(recovery).toContainText('unknown');
    expect(state.statusQueries[1]).toEqual(state.statusQueries[0]);
    expect(state.testIds).toHaveLength(1);
  });

  test('keeps the same test request ID after an ambiguous HTTP 409', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== '390x844', 'command receipt lifecycle is bound to one viewport');
    await page.unroute('**/api/**');
    const state = { testIds: [], statusQueries: [] };
    await page.route('**/api/**', async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.pathname === '/api/health') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, server_mode: false }) });
        return;
      }
      if (url.pathname === '/api/auth/restore-session') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
        return;
      }
      if (url.pathname === '/api/auth/me') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ role: 'admin', email: 'fixture-admin@example.test' }),
        });
        return;
      }
      if (url.pathname === '/api/campaign/test') {
        state.testIds.push(request.headers()['x-request-id'] || null);
        await route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({ detail: { state: 'fenced_by_stop' } }),
        });
        return;
      }
      if (url.pathname === '/api/campaign/command-status') {
        state.statusQueries.push({
          command: url.searchParams.get('command'),
          requestId: url.searchParams.get('request_id'),
        });
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ known: true, command: 'test', state: 'unknown', accepted: false, generation: 2 }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixturePayload(url.pathname)),
      });
    });

    await page.goto('/');
    await page.locator('details.campaign-more summary').click();
    const testButton = page.getByRole('button', { name: 'Тест', exact: true });
    await testButton.click();
    const recovery = page.locator('#campaignCommandRecovery');
    await expect(recovery).toBeVisible();
    await expect(recovery).toContainText('unknown');
    expect(state.testIds).toHaveLength(1);
    expect(state.statusQueries).toEqual([{ command: 'test', requestId: state.testIds[0] }]);

    await testButton.click();
    await expect.poll(() => state.statusQueries.length).toBe(2);
    expect(state.statusQueries[1]).toEqual(state.statusQueries[0]);
    expect(state.testIds).toHaveLength(1);

    await page.reload();
    await expect.poll(() => state.statusQueries.length).toBe(3);
    await expect(recovery).toContainText('unknown');
    expect(state.statusQueries[2]).toEqual(state.statusQueries[0]);
    expect(state.testIds).toHaveLength(1);
  });

  test('preserves bounded quoted CSV profile import content', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== '390x844', 'profile import fixture is bound to one viewport');
    await page.unroute('**/api/**');
    const state = { bulkCalls: 0, body: null };
    await page.route('**/api/**', async (route) => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname === '/api/health') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true, server_mode: true }),
        });
        return;
      }
      if (pathname === '/api/auth/restore-session') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true }),
        });
        return;
      }
      if (pathname === '/api/auth/me') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            role: 'admin',
            email: 'fixture-admin@example.test',
            impersonating: true,
            institution_name: 'Fixture import tenant',
            subscription: { active: true },
          }),
        });
        return;
      }
      if (pathname === '/api/groups') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([{
            id: 1,
            name: 'Fixture import group',
            invite_link: 'https://example.test/import',
            profiles_count: 0,
            active_count: 0,
            is_active: 1,
          }]),
        });
        return;
      }
      if (pathname === '/api/groups/1/profiles') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ items: [], total: 0, limit: 20, offset: 0 }),
        });
        return;
      }
      if (pathname === '/api/groups/1/profiles/bulk') {
        state.bulkCalls += 1;
        state.body = JSON.parse(route.request().postData() || '{}');
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ added: state.body.profiles.length, skipped: 0, errors: [] }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixturePayload(pathname)),
      });
    });

    await page.goto('/');
    await page.getByRole('tab', { name: 'Группы' }).click();
    await page.getByRole('button', { name: /Fixture import group/ }).click();
    await expect(page.getByRole('button', { name: 'Импорт CSV' })).toBeVisible();

    const validCsv = [
      '# fixture comment',
      'phone;label',
      '+70000000001;"Школа; 🚀"',
      '+70000000002;"{""value"":""a|b""}"',
      '+70000000003;"Школа; 🚀"',
    ].join('\n');
    await page.locator('#csvFile').setInputFiles({
      name: 'profiles.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(validCsv, 'utf8'),
    });
    await expect.poll(() => state.bulkCalls).toBe(1);
    expect(state.body).toEqual({
      profiles: [
        { phone: '+70000000001', full_name: '', label: 'Школа; 🚀' },
        { phone: '+70000000002', full_name: '', label: '{"value":"a|b"}' },
        { phone: '+70000000003', full_name: '', label: 'Школа; 🚀' },
      ],
    });

    await page.locator('#csvFile').setInputFiles({
      name: 'unterminated.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from('+70000000004;"не закрыто', 'utf8'),
    });
    await expect(page.locator('#toast-container .toast.error'))
      .toContainText('Незакрытая кавычка в CSV');
    expect(state.bulkCalls).toBe(1);

    const tooManyRows = [
      'phone;label',
      ...Array.from({ length: 2001 }, (_, index) => `+7999000${String(index).padStart(4, '0')};row`),
    ].join('\n');
    await page.locator('#csvFile').setInputFiles({
      name: 'too-many.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(tooManyRows, 'utf8'),
    });
    await expect(page.getByText('Максимум 2000 профилей за раз', { exact: true }))
      .toBeVisible();
    expect(state.bulkCalls).toBe(1);
  });

  test('reflows the dashboard surface at a 200-percent-equivalent CSS viewport', async ({ page }) => {
    await page.setViewportSize({ width: 195, height: 422 });
    await page.goto('/');

    const layout = await page.locator('main#main-content').evaluate((main) => {
      const rect = main.getBoundingClientRect();
      return {
        viewportWidth: window.innerWidth,
        left: rect.left,
        right: rect.right,
        documentWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      };
    });

    expect(layout.left).toBeGreaterThanOrEqual(0);
    expect(layout.right).toBeLessThanOrEqual(layout.viewportWidth + 1);
    expect(layout.documentWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
    const readinessBeforeStart = await page.evaluate(() => (
      document.getElementById('campaignReadinessPanel').getBoundingClientRect().top
      < document.getElementById('btnStart').getBoundingClientRect().top
    ));
    expect(readinessBeforeStart).toBe(true);
    await expect(page.locator('#campaign')).toBeVisible();
    await expect(page.locator('#campaignLog')).toContainText(holdLog);
  });

  test('uses one healthy WebSocket without periodic status GETs', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== '390x844', 'transport timing check is bound to one viewport');
    let authMessages = 0;
    const statusRequests = [];
    page.on('request', (request) => {
      if (new URL(request.url()).pathname === '/api/status') statusRequests.push(request);
    });
    await page.routeWebSocket('**/ws/status', (webSocket) => {
      webSocket.onMessage((message) => {
        const data = JSON.parse(String(message));
        if (data.type !== 'auth') return;
        authMessages += 1;
        webSocket.send(JSON.stringify(fixturePayload('/api/status')));
      });
    });

    await page.goto('/');
    await expect(page.locator('#liveBadge')).toHaveText('онлайн');
    const baseline = statusRequests.length;
    await page.waitForTimeout(5500);

    expect(authMessages).toBeGreaterThan(0);
    expect(statusRequests.length).toBe(baseline);
  });

  test('keeps two healthy tabs below the status rate limit', async ({ page, context }, testInfo) => {
    test.skip(testInfo.project.name !== '390x844', 'two-tab timing check is bound to one viewport');
    test.setTimeout(75_000);
    const secondPage = await context.newPage();
    const pages = [page, secondPage];
    const statusRequests = new Map();
    const responseStatuses = [];
    const authMessages = new Map();

    try {
      for (const target of pages) {
        statusRequests.set(target, 0);
        authMessages.set(target, 0);
        target.on('request', (request) => {
          if (new URL(request.url()).pathname === '/api/status') {
            statusRequests.set(target, statusRequests.get(target) + 1);
          }
        });
        target.on('response', (response) => {
          if (new URL(response.url()).pathname.startsWith('/api/')) {
            responseStatuses.push(response.status());
          }
        });
        await target.route('**/api/**', async (route) => {
          const pathname = new URL(route.request().url()).pathname;
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(fixturePayload(pathname)),
          });
        });
        await target.routeWebSocket('**/ws/status', (webSocket) => {
          webSocket.onMessage((message) => {
            const data = JSON.parse(String(message));
            if (data.type !== 'auth') return;
            authMessages.set(target, authMessages.get(target) + 1);
            webSocket.send(JSON.stringify(fixturePayload('/api/status')));
          });
        });
      }

      await Promise.all(pages.map((target) => target.goto('/')));
      await Promise.all(pages.map((target) => expect(target.locator('#liveBadge')).toHaveText('онлайн')));
      const baseline = new Map(statusRequests);

      await page.waitForTimeout(60_000);

      for (const target of pages) {
        expect(authMessages.get(target)).toBeGreaterThan(0);
        expect(statusRequests.get(target)).toBe(baseline.get(target));
      }
      expect(responseStatuses).not.toContain(429);
    } finally {
      await secondPage.close();
    }
  });

  test('runs one fallback request during an outage and stops it after reconnect', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== '390x844', 'transport timing check is bound to one viewport');
    test.setTimeout(20_000);
    let connections = 0;
    const statusRequests = [];
    page.on('request', (request) => {
      if (new URL(request.url()).pathname === '/api/status') statusRequests.push(request);
    });
    await page.routeWebSocket('**/ws/status', (webSocket) => {
      connections += 1;
      if (connections < 4) {
        webSocket.close({ code: 1011, reason: 'fixture outage' });
        return;
      }
      webSocket.onMessage((message) => {
        const data = JSON.parse(String(message));
        if (data.type === 'auth') webSocket.send(JSON.stringify(fixturePayload('/api/status')));
      });
    });

    const initialStatusResponse = page.waitForResponse((response) => (
      new URL(response.url()).pathname === '/api/status'
    ));
    await page.goto('/');
    await initialStatusResponse;
    const baseline = statusRequests.length;
    await expect.poll(() => connections, { timeout: 10_000 }).toBe(4);
    await expect(page.locator('#liveBadge')).toHaveText('онлайн');
    expect(statusRequests.length - baseline).toBe(1);
    await page.waitForTimeout(1_000);
    expect(statusRequests.length - baseline).toBe(1);
  });

  test('does not poll while hidden and performs one resync on return', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== '390x844', 'visibility timing check is bound to one viewport');
    const statusRequests = [];
    page.on('request', (request) => {
      if (new URL(request.url()).pathname === '/api/status') statusRequests.push(request);
    });
    await page.goto('/');
    await expect.poll(() => statusRequests.length).toBeGreaterThan(0);
    const baseline = statusRequests.length;

    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        configurable: true,
        get: () => 'hidden',
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await page.waitForTimeout(5_500);
    expect(statusRequests.length).toBe(baseline);

    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        configurable: true,
        get: () => 'visible',
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await expect.poll(() => statusRequests.length, { timeout: 2_000 }).toBe(baseline + 1);
    await page.waitForTimeout(1_000);
    expect(statusRequests.length).toBe(baseline + 1);
  });

  test('keeps a profile auth attempt when findProfile is rate-limited', async ({ page, diagnostics }, testInfo) => {
    test.skip(testInfo.project.name !== '390x844', 'auth transport check is bound to one viewport');
    diagnostics.allowResponse('/api/profiles/7', [429]);
    diagnostics.allowConsoleError(/status of 429/);
    const state = await routeProfileAuthFixture(page, 'rate');
    await beginFixtureLogin(page);

    await expect(page.locator('#toast-container .toast.error')).toContainText('Слишком много запросов к кабинету');
    await expect(page.locator('#toast-container')).not.toContainText('Профиль не найден');
    const profileRow = page.getByRole('row').filter({ hasText: '+70000000007' });
    await expect(profileRow.locator('.status-pending')).toHaveText('ожидает входа');
    await expect(profileRow.locator('.status-banned, .status-needs_reauth')).toHaveCount(0);
    expect(state.profileReads).toBe(1);
  });

  test('shows a service error instead of profile-not-found on findProfile 5xx', async ({ page, diagnostics }, testInfo) => {
    test.skip(testInfo.project.name !== '390x844', 'auth transport check is bound to one viewport');
    diagnostics.allowResponse('/api/profiles/7', [503]);
    diagnostics.allowConsoleError(/status of 503/);
    const state = await routeProfileAuthFixture(page, 'server');
    await beginFixtureLogin(page);

    await expect(page.locator('#toast-container .toast.error')).toContainText('Сервис временно недоступен');
    await expect(page.locator('#toast-container')).not.toContainText('Профиль не найден');
    expect(state.profileReads).toBe(1);
  });

  test('shows a network error instead of profile-not-found on findProfile failure', async ({ page, diagnostics }, testInfo) => {
    test.skip(testInfo.project.name !== '390x844', 'auth transport check is bound to one viewport');
    diagnostics.allowFailedRequest('/api/profiles/7');
    diagnostics.allowConsoleError(/ERR_FAILED/);
    const state = await routeProfileAuthFixture(page, 'network');
    await beginFixtureLogin(page);

    await expect(page.locator('#toast-container .toast.error')).toContainText('Сеть недоступна');
    await expect(page.locator('#toast-container')).not.toContainText('Профиль не найден');
    expect(state.profileReads).toBe(1);
  });

  test('keeps toast notifications in document flow above page content', async ({ page }, testInfo) => {
    await page.goto('/');
    await page.evaluate(() => {
      const toast = document.createElement('div');
      toast.className = 'toast error';
      toast.textContent = 'Fixture notice';
      document.getElementById('toast-container').appendChild(toast);
    });
    const bounds = await page.evaluate(() => {
      const container = document.getElementById('toast-container');
      const main = document.getElementById('main-content');
      return {
        position: getComputedStyle(container).position,
        toastBottom: container.getBoundingClientRect().bottom,
        mainTop: main.getBoundingClientRect().top,
        toastText: container.textContent,
      };
    });
    expect(bounds.position).not.toBe('fixed');
    expect(bounds.mainTop).toBeGreaterThanOrEqual(bounds.toastBottom);
    expect(bounds.toastText).toContain('Fixture notice');
    await page.screenshot({ path: `/tmp/maxbot-t26-toast-in-flow-${testInfo.project.name}.png` });
    await testInfo.attach('toast-in-flow.png', {
      body: await page.screenshot(),
      contentType: 'image/png',
    });
  });

  test('user previews and downloads only the current safe auth diagnostic', async ({ page }, testInfo) => {
    let diagnosticDownloadRequests = 0;
    await page.unroute('**/api/**');
    await page.route('**/api/**', async (route) => {
      const url = new URL(route.request().url());
      const path = url.pathname;
      const json = (body, status = 200, headers = {}) => route.fulfill({
        status,
        contentType: 'application/json',
        headers,
        body: JSON.stringify(body),
      });
      if (path === '/api/health') return json({ ok: true, server_mode: true });
      if (path === '/api/auth/restore-session') return json({ ok: true });
      if (path === '/api/auth/me') return json({
        server_mode: true, role: 'user', tenant_id: 8,
        subscription: { active: true },
      });
      if (path === '/api/groups') return json([{
        id: 1, name: 'Fixture diagnostic group', invite_link: 'https://example.test/group',
        profiles_count: 1, active_count: 0, is_active: 1,
      }]);
      if (path === '/api/groups/1/profiles') return json({
        items: [{
          id: 7, phone: '+70000000007', status: 'pending', auth_step: 'idle',
          attempt_id: 'attempt-current-7', last_error: '', circuit_open: false,
        }],
        total: 1, limit: 20, offset: 0,
      });
      if (path === '/api/profiles/7/auth-attempts/attempt-current-7/diagnostic') {
        const body = {
          attempt_id: 'attempt-current-7', phone: '+7000••••••07', status: 'pending',
          auth_step: 'waiting_sms', next_action: 'submit_code', has_error: false,
          retention: 'metadata_only',
        };
        if (url.searchParams.get('download') === '1') diagnosticDownloadRequests += 1;
        return url.searchParams.get('download') === '1'
          ? route.fulfill({
            status: 200, contentType: 'application/json',
            headers: { 'Content-Disposition': 'attachment; filename="auth-attempt.json"' },
            body: JSON.stringify(body),
          })
          : json(body);
      }
      return json(fixturePayload(path));
    });
    await page.goto('/');
    await page.getByRole('tab', { name: 'Группы' }).click();
    await page.getByRole('button', { name: /Fixture diagnostic group/ }).click();
    await page.locator('details.profile-more > summary').click();
    const previewButton = page.getByRole('button', { name: 'Диагностика входа' });
    await previewButton.click();
    await expect(page.locator('.auth-diagnostic-preview')).toContainText('attempt-current-7');
    await expect(page.locator('.auth-diagnostic-preview')).toContainText('+7000••••••07');
    await expect(page.locator('.auth-diagnostic-preview')).not.toContainText('operation_id');
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Скачать JSON' }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe('auth-attempt.json');
    expect(diagnosticDownloadRequests).toBe(1);
    await page.screenshot({ path: '/tmp/maxbot-t26-auth-diagnostic-preview-390x844.png' });
    await testInfo.attach('auth-diagnostic-preview.png', {
      body: await page.screenshot(),
      contentType: 'image/png',
    });
  });

  test('keeps OTP controls usable with the virtual keyboard open and preserves focus after login', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== '390x844', 'auth attempt lifecycle is bound to one viewport');
    await page.setViewportSize({ width: 390, height: 440 });
    await page.unroute('**/api/**');
    const state = {
      loginCalls: 0,
      smsCalls: 0,
      profileSteps: [],
      authCompleted: false,
      delayedCompletionRefresh: false,
      delayedCompletionRefreshDone: false,
    };
    await page.route('**/api/**', async (route) => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      if (pathname === '/api/health') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, server_mode: true }) });
        return;
      }
      if (pathname === '/api/auth/restore-session') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
        return;
      }
      if (pathname === '/api/auth/me') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ role: 'user', subscription: { active: true } }) });
        return;
      }
      if (pathname === '/api/groups') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([{
            id: 1,
            name: 'Fixture group',
            invite_link: 'https://example.test/fixture',
            profiles_count: 1,
            active_count: 0,
            is_active: 1,
          }]),
        });
        return;
      }
      if (pathname === '/api/groups/1/profiles') {
        if (state.authCompleted && !state.delayedCompletionRefresh) {
          state.delayedCompletionRefresh = true;
          await new Promise((resolve) => setTimeout(resolve, 250));
          state.delayedCompletionRefreshDone = true;
        }
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            items: [{
              id: 7,
              phone: '+70000000007',
              status: state.authCompleted ? 'active' : 'needs_reauth',
              auth_step: 'idle',
              attempt_id: state.authCompleted ? 'auth-browser-retry' : undefined,
              last_error: 'Предыдущий вход не завершён',
              circuit_open: false,
            }],
            total: 1,
            limit: 20,
            offset: 0,
          }),
        });
        return;
      }
      if (pathname === '/api/profiles/7/automation-scope') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
        return;
      }
      if (pathname === '/api/profiles/7/login') {
        state.loginCalls += 1;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            message: 'Вход запущен',
            auth_step: 'connecting',
            attempt_id: 'auth-browser-retry',
            revision: 0,
          }),
        });
        return;
      }
      if (pathname === '/api/profiles/7') {
        const steps = ['connecting', 'waiting_sms', 'verifying_sms', 'idle'];
        const step = steps[Math.min(state.profileSteps.length, steps.length - 1)];
        state.profileSteps.push(step);
        if (step === 'idle') state.authCompleted = true;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 7,
            phone: '+70000000007',
            status: step === 'idle' ? 'active' : 'needs_reauth',
            auth_step: step,
            auth_stage: {
              connecting: 'connecting',
              waiting_sms: 'waiting_code',
              verifying_sms: 'verifying_code',
              idle: 'succeeded',
            }[step],
            attempt_id: 'auth-browser-retry',
            revision: step === 'waiting_sms' ? 1 : 0,
            last_error: step === 'idle' ? '' : 'Предыдущий вход не завершён',
          }),
        });
        return;
      }
      if (pathname === '/api/profiles/7/sms') {
        state.smsCalls += 1;
        const body = request.postDataJSON();
        expect(body.code).toBe('123456');
        expect(body.attempt_id).toBe('auth-browser-retry');
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true, auth_step: 'verifying_sms' }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixturePayload(pathname)),
      });
    });

    await page.goto('/');
    await page.getByRole('tab', { name: 'Группы' }).click();
    await page.getByRole('button', { name: /Fixture group/ }).click();
    await expect(page.getByText('+70000000007')).toBeVisible();
    await page.getByRole('table').getByRole('button', { name: 'Войти', exact: true }).click();

    await expect(page.locator('#authModal')).toBeVisible();
    await expect(page.locator('#authModalTitle')).toHaveText('SMS-код');
    await expect(page.locator('#authModalInput')).toBeFocused();
    await expect(page.locator('#authModalCancel')).toBeVisible();
    await expect(page.locator('#authModalOk')).toBeVisible();
    const controlsBounds = await page.locator('#authModal').evaluate((overlay) => {
      const bounds = (selector) => {
        const rect = overlay.querySelector(selector).getBoundingClientRect();
        return { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right };
      };
      return {
        input: bounds('#authModalInput'),
        cancel: bounds('#authModalCancel'),
        submit: bounds('#authModalOk'),
        viewportWidth: document.documentElement.clientWidth,
        viewportHeight: window.visualViewport?.height || window.innerHeight,
        documentWidth: document.documentElement.scrollWidth,
      };
    });
    expect(controlsBounds.input.top).toBeGreaterThanOrEqual(0);
    expect(controlsBounds.submit.bottom).toBeLessThanOrEqual(controlsBounds.viewportHeight);
    expect(controlsBounds.cancel.left).toBeGreaterThanOrEqual(0);
    expect(controlsBounds.submit.right).toBeLessThanOrEqual(controlsBounds.viewportWidth);
    expect(controlsBounds.documentWidth).toBeLessThanOrEqual(controlsBounds.viewportWidth);
    await testInfo.attach('otp-modal-390x440.png', {
      body: await page.screenshot(),
      contentType: 'image/png',
    });

    await page.keyboard.press('Tab');
    await expect(page.locator('#authModalCancel')).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.locator('#authModalOk')).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.locator('#authModalInput')).toBeFocused();

    await page.locator('#authModalInput').fill('123456');
    await page.locator('#authModalInput').press('Enter');
    await expect(page.locator('#authModal')).toBeHidden();
    await expect(page.getByRole('table').getByRole('button', { name: 'Войти', exact: true })).toBeFocused();
    await expect.poll(() => state.delayedCompletionRefreshDone).toBe(true);
    await expect(page.locator('details.profile-more > summary')).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.locator('#phone-1')).toBeFocused();
    await expect(page.getByText('Аккаунт подключён', { exact: true })).toBeVisible();
    expect(state.loginCalls).toBe(1);
    expect(state.smsCalls).toBe(1);
    expect(state.profileSteps).toEqual(['connecting', 'waiting_sms', 'verifying_sms', 'idle']);
  });

});
