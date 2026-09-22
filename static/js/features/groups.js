/** Account-list helpers shared by admin and cabinet views. */

const FILTER_KEYS = Object.freeze([
  'group_id',
  'role',
  'availability',
  'daily_plan',
  'connection_problem',
]);

function boundedInteger(value, fallback, minimum, maximum) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(maximum, Math.max(minimum, parsed));
}

export function createAccountQuery(filters = {}) {
  const params = new URLSearchParams();
  const q = String(filters.q || '').trim().slice(0, 100);
  const page = boundedInteger(filters.page, 1, 1, 1000000);
  const limit = boundedInteger(filters.limit, 50, 1, 200);
  if (q) params.set('q', q);
  params.set('page', String(page));
  params.set('limit', String(limit));
  for (const key of FILTER_KEYS) {
    const value = filters[key];
    if (value !== undefined && value !== null && String(value) !== '') {
      params.set(key, String(value));
    }
  }
  return `/api/profiles?${params.toString()}`;
}

export function normalizePhone(value) {
  const raw = String(value || '').trim();
  const hasPlus = raw.startsWith('+');
  const digits = raw.replace(/\D/g, '');
  return digits ? `${hasPlus ? '+' : ''}${digits}` : '';
}

export function preserveDirtyDraft(serverAccount = {}, draft = null) {
  const serverRevision = serverAccount.server_revision ?? serverAccount.revision ?? null;
  if (!draft || !draft.dirty) {
    return { ...serverAccount, server_revision: serverRevision, conflict: false };
  }
  const draftRevision = draft.server_revision ?? null;
  return {
    ...serverAccount,
    ...(draft.fields || {}),
    server_revision: serverRevision,
    conflict: draftRevision !== null
      && serverRevision !== null
      && draftRevision !== serverRevision,
  };
}

export function accountDrawerModel(account = {}) {
  return {
    id: account.id,
    phone: normalizePhone(account.phone),
    label: account.label || '',
    role: account.role || account.status || 'unknown',
    availability: account.availability || 'unknown',
    assigned_connection: account.connection_label || account.connection_name || null,
    consent: account.consent_state || 'unknown',
    association_count: Number(account.association_count || account.group_count || 0),
    next_action: account.next_action || 'review',
  };
}

export function accountActionImpact(account = {}, action = 'archive') {
  const associations = Number(account.association_count || account.group_count || 0);
  return {
    action,
    association_count: associations,
    affects_all_group_associations: associations > 1,
    next_action: action === 'unlink' && associations > 1
      ? 'select_group'
      : 'confirm_action',
  };
}
