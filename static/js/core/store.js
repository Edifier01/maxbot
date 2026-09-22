export function createRevisionStore() {
  let revision = -1;
  let value = null;
  return {
    get revision() { return revision; },
    get value() { return value; },
    accept(next, nextRevision) {
      const candidate = Number(nextRevision);
      if (!Number.isFinite(candidate) || candidate < revision) return false;
      revision = candidate;
      value = next;
      return true;
    },
    clear() {
      revision = -1;
      value = null;
    },
  };
}
