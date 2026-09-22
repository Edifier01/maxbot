/**
 * Pure overview projections.  The panel must distinguish a waiting campaign
 * from a stopped campaign and must never infer provider success from a local
 * request that is still unknown.
 */

const ACTIVE_STATES = new Set(['running', 'auto_run']);

function isConnectionLost(snapshot) {
  return snapshot?.connection_fresh === false
    || snapshot?.connection_status === 'lost'
    || snapshot?.connection_status === 'offline';
}

export function deriveCampaignState(snapshot = {}) {
  if (isConnectionLost(snapshot)) {
    return {
      state: 'connection_lost',
      next_action: 'reconnect',
      stop: { enabled: false, label: 'Остановить' },
    };
  }

  if (snapshot.action_required) {
    return {
      state: 'action_required',
      next_action: 'resolve_action',
      stop: { enabled: Boolean(snapshot.running || snapshot.auto_run), label: 'Остановить' },
    };
  }

  if (snapshot.stopping || snapshot.stop_pending) {
    return {
      state: 'stopping',
      next_action: 'wait_stop',
      stop: { enabled: false, label: 'Останавливается…' },
    };
  }

  const active = ACTIVE_STATES.has(snapshot.state)
    || Boolean(snapshot.running || snapshot.auto_run);
  if (active && snapshot.in_send_window === false) {
    return {
      state: 'waiting_window',
      next_action: 'stop',
      stop: { enabled: true, label: 'Остановить' },
    };
  }

  if (active && (snapshot.limit_reached || snapshot.remaining === 0)) {
    return {
      state: 'waiting_limit',
      next_action: 'stop',
      stop: { enabled: true, label: 'Остановить' },
    };
  }

  if (active) {
    return {
      state: 'running',
      next_action: 'stop',
      stop: { enabled: true, label: 'Остановить' },
    };
  }

  return {
    state: 'stopped',
    next_action: 'start',
    stop: { enabled: false, label: 'Остановить' },
  };
}

export function classifyOperation(operation = {}) {
  if (operation.status === 'accepted' && operation.provider_message_id) {
    return 'accepted';
  }
  if (operation.status === 'unknown' || operation.outcome === 'unknown') {
    return 'unknown';
  }
  if (operation.status === 'failed_unsent') {
    return 'failed_unsent';
  }
  return operation.status || 'queued';
}

export function planCounters(snapshot = {}) {
  const target = Number(snapshot.target ?? snapshot.effective_target ?? 0);
  const accepted = Number(snapshot.accepted ?? snapshot.accepted_count ?? 0);
  const unknown = Number(snapshot.unknown ?? snapshot.unknown_count ?? 0);
  const remaining = Math.max(0, Number(snapshot.remaining ?? target - accepted - unknown));
  const libraryCount = Number(snapshot.library_count ?? 0);
  const daySelectionCount = Number(snapshot.day_selection_count ?? 0);

  return {
    target,
    accepted,
    unknown,
    remaining,
    library_count: libraryCount,
    day_selection_count: daySelectionCount,
    next_action: unknown > 0
      ? 'review_unknown'
      : remaining > 0
        ? 'continue_plan'
        : 'wait_next_window',
  };
}

export function groupTarget(groups = []) {
  return groups.reduce((total, group) => (
    total + Number(group.effective_target ?? group.target ?? 0)
  ), 0);
}

export function buildOverviewModel(snapshot = {}) {
  return {
    campaign: deriveCampaignState(snapshot),
    plan: planCounters(snapshot),
    group_target: groupTarget(snapshot.groups || []),
  };
}
