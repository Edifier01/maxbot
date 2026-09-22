/* State-restoring auth wizard helpers. Secrets never enter this store. */

export const AUTH_TERMINAL_STEPS = Object.freeze([
  'idle',
  'succeeded',
  'error',
  'expired',
]);

export const AUTH_INPUT_AUTOCOMPLETE = Object.freeze({
  code: 'one-time-code',
  password: 'current-password',
});

export function authAttemptView(payload) {
  const value = payload && typeof payload === 'object' ? payload : {};
  return Object.freeze({
    attempt_id: value.attempt_id ? String(value.attempt_id) : '',
    revision: Number.isFinite(Number(value.revision)) ? Number(value.revision) : 0,
    auth_step: value.auth_step ? String(value.auth_step) : 'idle',
    auth_hint: value.auth_hint ? String(value.auth_hint) : '',
    phone: value.phone ? String(value.phone) : '',
  });
}

export function buildCodePayload(attempt, code) {
  const state = authAttemptView(attempt);
  return {
    attempt_id: state.attempt_id,
    revision: state.revision,
    code: String(code || '').trim(),
  };
}

export function buildPasswordPayload(attempt, password) {
  const state = authAttemptView(attempt);
  return {
    attempt_id: state.attempt_id,
    revision: state.revision,
    // Do not trim cloud passwords: spaces are part of the submitted secret.
    code: String(password == null ? '' : password),
  };
}

export async function restoreAuthAttempt(fetchProfile, profileId, previous) {
  const current = authAttemptView(await fetchProfile(profileId));
  if (previous && previous.attempt_id && current.attempt_id !== previous.attempt_id) {
    return authAttemptView({
      ...current,
      auth_step: AUTH_TERMINAL_STEPS.includes(current.auth_step)
        ? current.auth_step
        : 'error',
      auth_hint: 'Текущая попытка изменилась; начните новый вход явно.',
    });
  }
  return current;
}
