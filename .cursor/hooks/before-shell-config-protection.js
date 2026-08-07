#!/usr/bin/env node
/**
 * Lightweight config-protection: warn on commands that skip tests or disable CI checks.
 * Adapted from ECC config-protection intent (Cursor shell hook).
 */
let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => (raw += c));
process.stdin.on('end', () => {
  try {
    const input = JSON.parse(raw || '{}');
    const cmd = String(input.command || input.cmd || '');
    const risky =
      /\bpytest\b.*--no-header.*-k\s+NONE/i.test(cmd) ||
      /\bgit\s+commit\b.*--no-verify\b/i.test(cmd) ||
      /\bgit\s+push\b.*--no-verify\b/i.test(cmd) ||
      /\brm\s+-rf\s+tests\b/i.test(cmd) ||
      /\becho\s+.*>>\s*\.github\/workflows\//i.test(cmd);
    if (risky) {
      console.error('[max-sender] WARNING: Command may weaken tests/CI gates.');
      console.error('[max-sender] Prefer fixing code; do not skip hooks or delete tests.');
    }
  } catch (_) {}
  process.stdout.write(raw);
});
