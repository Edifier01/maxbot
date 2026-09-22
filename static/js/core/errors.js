export class ApiError extends Error {
  constructor(message, { status = 0, code = 'NETWORK_ERROR', retryAfter = null, detail = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
    this.detail = detail;
  }
}

export function retryAfterValue(response) {
  const raw = response.headers.get('Retry-After');
  if (!raw) return null;
  const seconds = Number(raw);
  if (Number.isFinite(seconds) && seconds >= 0) return seconds;
  const at = Date.parse(raw);
  return Number.isFinite(at) ? Math.max(0, (at - Date.now()) / 1000) : null;
}
