/** Pure helpers for scoped administrator actions and institution views. */

function uniqueIds(values = []) {
  return [...new Set(values.map(value => Number(value)).filter(Number.isInteger))];
}

export function buildBulkPreview({
  action,
  selection_mode = 'selected',
  selected_ids = [],
  total = 0,
  explicit_all = false,
  idempotency_key = '',
} = {}) {
  const ids = uniqueIds(selected_ids);
  const allRecords = selection_mode === 'all';
  const valid = allRecords ? explicit_all === true : ids.length > 0;
  const count = allRecords ? Number(total) : ids.length;
  return {
    valid,
    reason: valid ? null : allRecords ? 'explicit_all_required' : 'selection_required',
    action: String(action || ''),
    scope: {
      selection_mode: allRecords ? 'all' : 'selected',
      explicit_all: allRecords,
      selected_ids: allRecords ? [] : ids,
      count: Math.max(0, count),
    },
    consequences: allRecords
      ? `Изменение затронет все ${Math.max(0, count)} записи.`
      : `Изменение затронет ${ids.length} выбранные записи.`,
    idempotency_key: String(idempotency_key || ''),
    audit: { required: true, scope: allRecords ? 'all' : 'selected' },
    emergency_stop: { available: true, action: 'stop' },
  };
}

export function summarizeBulkResults(results = []) {
  const perItem = results.map(item => ({
    id: item.id,
    status: item.status || 'unknown',
    reason: item.reason || null,
  }));
  const succeeded = perItem.filter(item => item.status === 'ok').length;
  const failed = perItem.length - succeeded;
  return {
    total: perItem.length,
    succeeded,
    failed,
    partial: succeeded > 0 && failed > 0,
    per_item: perItem,
  };
}

export function institutionQuery({ q = '', page = 1, limit = 20, expiring = false } = {}) {
  const params = new URLSearchParams();
  const normalized = String(q).trim().slice(0, 100);
  if (normalized) params.set('q', normalized);
  params.set('page', String(Math.max(1, Number(page) || 1)));
  params.set('limit', String(Math.min(200, Math.max(1, Number(limit) || 20))));
  if (expiring) params.set('expiring', '1');
  return `/api/admin/users?${params.toString()}`;
}
