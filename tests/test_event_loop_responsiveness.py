"""T20 bounded-cache and cancellation-safe local checks."""

from __future__ import annotations

from app import auth, auth_rate_limit


def test_session_and_rate_limit_caches_have_explicit_bounds() -> None:
    assert auth.SESSION_CACHE_MAX > 0
    assert auth_rate_limit.MEMORY_MAX_KEYS > 0
    auth.clear_session_cache()
    auth_rate_limit.reset_for_tests()
    assert auth.session_cache_size() == 0
    assert auth_rate_limit.memory_bucket_count() == 0


def test_memory_rate_limit_buckets_are_evicted_at_bound() -> None:
    auth_rate_limit.reset_for_tests()
    limit = auth_rate_limit.MEMORY_MAX_KEYS
    for index in range(limit + 10):
        auth_rate_limit.check_auth_rate_limit(f"fixture:{index}", 1, 900)
    assert auth_rate_limit.memory_bucket_count() <= limit
