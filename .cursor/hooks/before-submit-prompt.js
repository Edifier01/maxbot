#!/usr/bin/env node
/**
 * Adapted from ECC before-submit-prompt — secret pattern warning.
 */
let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => (raw += c));
process.stdin.on('end', () => {
  try {
    const input = JSON.parse(raw || '{}');
    const prompt = input.prompt || input.content || input.message || '';
    const patterns = [
      /sk-[a-zA-Z0-9]{20,}/,
      /ghp_[a-zA-Z0-9]{36,}/,
      /AKIA[A-Z0-9]{16}/,
      /xox[bpsa]-[a-zA-Z0-9-]+/,
      /-----BEGIN (RSA |EC )?PRIVATE KEY-----/,
      /JWT_SECRET\s*=\s*['\"]?[^'\"\s]{16,}/i,
      /INTERNAL_SERVICE_TOKEN\s*=\s*['\"]?[^'\"\s]{8,}/i,
    ];
    for (const pattern of patterns) {
      if (pattern.test(prompt)) {
        console.error('[max-sender] WARNING: Potential secret detected in prompt.');
        console.error('[max-sender] Remove secrets; use env vars / vault instead.');
        break;
      }
    }
  } catch (_) {}
  process.stdout.write(raw);
});
