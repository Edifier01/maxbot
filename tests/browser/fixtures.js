const { test: base, expect } = require('@playwright/test');

function isLoopbackUrl(rawUrl, baseURL) {
  let url;
  let configured;
  try {
    url = new URL(rawUrl);
    configured = new URL(baseURL);
  } catch (_) {
    return false;
  }

  if (url.origin === configured.origin) return true;
  if (!['http:', 'https:'].includes(url.protocol)) return false;
  return ['127.0.0.1', 'localhost', '[::1]', '::1'].includes(url.hostname);
}

function matchesPath(pattern, url) {
  if (pattern instanceof RegExp) return pattern.test(url);
  return new URL(url).pathname.includes(pattern);
}

const test = base.extend({
  diagnostics: async ({ page, baseURL }, use, testInfo) => {
    const expectedResponses = [];
    const expectedConsoleErrors = [];
    const consoleErrors = [];
    const pageErrors = [];
    const failedRequests = [];
    const failedResponses = [];
    const externalRequests = [];

    const diagnostics = {
      allowResponse(path, statuses = [401]) {
        expectedResponses.push({ path, statuses });
      },
      allowConsoleError(pattern) {
        expectedConsoleErrors.push(pattern);
      },
    };

    page.on('console', (message) => {
      if (message.type() === 'error') {
        consoleErrors.push(message.text());
      }
    });
    page.on('pageerror', (error) => {
      pageErrors.push(error.message);
    });
    page.on('request', (request) => {
      if (!isLoopbackUrl(request.url(), baseURL)) {
        externalRequests.push({ method: request.method(), url: request.url() });
      }
    });
    page.on('requestfailed', (request) => {
      failedRequests.push({
        method: request.method(),
        url: request.url(),
        failure: request.failure()?.errorText || 'unknown request failure',
      });
    });
    page.on('response', (response) => {
      if (response.status() < 400) return;
      const expected = expectedResponses.some(({ path, statuses }) => (
        matchesPath(path, response.url()) && statuses.includes(response.status())
      ));
      if (!expected) {
        failedResponses.push({ status: response.status(), url: response.url() });
      }
    });

    await use(diagnostics);

    const unexpectedConsoleErrors = consoleErrors.filter((message) => (
      !expectedConsoleErrors.some((pattern) => (
        pattern instanceof RegExp ? pattern.test(message) : message.includes(pattern)
      ))
    ));
    const report = {
      baseURL,
      consoleErrors,
      expectedConsoleErrors: expectedConsoleErrors.map(String),
      pageErrors,
      failedRequests,
      failedResponses,
      externalRequests,
      expectedResponses: expectedResponses.map(({ path, statuses }) => ({
        path: String(path),
        statuses,
      })),
    };
    await testInfo.attach('browser-diagnostics.json', {
      body: Buffer.from(JSON.stringify(report, null, 2)),
      contentType: 'application/json',
    });

    const violations = [
      ...unexpectedConsoleErrors.map((message) => `console.error: ${message}`),
      ...pageErrors.map((message) => `pageerror: ${message}`),
      ...failedRequests.map(({ method, url, failure }) => (
        `requestfailed: ${method} ${url} (${failure})`
      )),
      ...failedResponses.map(({ status, url }) => `HTTP ${status}: ${url}`),
      ...externalRequests.map(({ method, url }) => `external request: ${method} ${url}`),
    ];
    if (violations.length > 0) {
      throw new Error(`Browser diagnostics failed:\n${violations.join('\n')}`);
    }
  },
});

module.exports = { test, expect };
