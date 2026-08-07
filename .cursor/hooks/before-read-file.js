#!/usr/bin/env node
/**
 * Adapted from ECC before-read-file (Cursor-native, no plugin root).
 * Warns when agents read sensitive paths; does not block.
 */
let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => (raw += c));
process.stdin.on('end', () => {
  try {
    const input = JSON.parse(raw || '{}');
    const filePath = input.path || input.file || input.filePath || '';
    if (/\.(env|key|pem)$|\.env\.|credentials|secret|id_rsa/i.test(filePath)) {
      console.error('[max-sender] WARNING: Reading sensitive file: ' + filePath);
      console.error('[max-sender] Do not expose secrets in outputs or commits.');
    }
  } catch (_) {}
  process.stdout.write(raw);
});
