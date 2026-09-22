import { ApiError, retryAfterValue } from './errors.js';

// HTTP Retry-After remains a transport hint; it is never flattened into 404.

export async function requestJson(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    payload = null;
  }
  if (!response.ok) {
    const detail = payload && payload.detail;
    const code = detail && typeof detail === 'object' && detail.code
      ? String(detail.code)
      : `HTTP_${response.status}`;
    const message = detail && typeof detail === 'object' && detail.safe_message
      ? String(detail.safe_message)
      : (typeof detail === 'string' ? detail : (response.statusText || 'Request failed'));
    throw new ApiError(message, {
      status: response.status,
      code,
      retryAfter: retryAfterValue(response),
      detail,
    });
  }
  return payload;
}
