"""Static contracts for the dev-only rendered browser gate."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _manifest() -> dict:
    return json.loads((ROOT / "package.json").read_text(encoding="utf-8"))


def _playwright_config() -> str:
    return (ROOT / "playwright.config.js").read_text(encoding="utf-8")


def test_browser_manifest_is_private_and_dev_only() -> None:
    manifest = _manifest()

    assert manifest["private"] is True
    assert manifest["scripts"]["browser:e2e"] == "playwright test"
    assert manifest.get("dependencies", {}) == {}
    assert manifest["devDependencies"] == {"@playwright/test": "1.63.0"}


def test_browser_config_is_loopback_and_three_viewports() -> None:
    config = _playwright_config()

    assert "process.env.BASE_URL || 'http://127.0.0.1:8765'" in config
    assert "name: '390x844'" in config
    assert "name: '768x1024'" in config
    assert "name: '1440x1000'" in config
    assert "width: 390, height: 844" in config
    assert "width: 768, height: 1024" in config
    assert "width: 1440, height: 1000" in config
    assert "trace: 'retain-on-failure'" in config
    assert "screenshot: 'only-on-failure'" in config
    assert "video: 'retain-on-failure'" in config
    assert "webServer" not in config


def test_browser_runner_contains_no_provider_boundary() -> None:
    manifest = (ROOT / "package.json").read_text(encoding="utf-8")
    config = _playwright_config()
    source = f"{manifest}\n{config}".lower()

    for forbidden in ("max.ru", "maxapi", "telegram", "yookassa", "jwt_secret"):
        assert forbidden not in source


def test_browser_workflow_isolated_and_artifacted() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "  browser-e2e:\n" in workflow
    browser_job = workflow.split("  browser-e2e:\n", 1)[1]

    assert "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020" in browser_job
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in browser_job
    assert 'node-version: "24"' in browser_job
    assert "npm ci" in browser_job
    assert "npx playwright install --with-deps chromium" in browser_job
    assert "npm run browser:e2e" in browser_job
    assert "MAX_TEST: \"1\"" in browser_job
    assert "MAX_SERVER_MODE: \"0\"" in browser_job
    assert "MAX_DATA" in browser_job
    assert "MAX_RECOVERY_HOLD_FILE" in browser_job
    assert "MAX_DATA: ${{ runner.temp }}" not in browser_job
    assert "MAX_RECOVERY_HOLD_FILE: ${{ runner.temp }}" not in browser_job
    assert 'browser_data="$RUNNER_TEMP/maxbot-browser-data"' in browser_job
    assert 'recovery_hold_file="$RUNNER_TEMP/maxbot-recovery-hold.json"' in browser_job
    assert "MAX_HOST: 127.0.0.1" in browser_job
    assert 'MAX_PORT: "8765"' in browser_job
    assert "curl -fsS http://127.0.0.1:8765/api/health" in browser_job
    assert "if: always()" in browser_job
    assert "playwright-report/" in browser_job
    assert "test-results/" in browser_job
    assert "server.log" in browser_job
    assert "DATABASE_URL" not in browser_job
    assert "MAX.ru" not in browser_job
