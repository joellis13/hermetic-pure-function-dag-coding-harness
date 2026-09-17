"""
Content-Addressable Cache — deterministic memoization for hermetic node inputs.

The cache is intentionally in-process and ephemeral in Phase 1. A disk/SQLite
backend is introduced in Story 5 (State Machine).

Usage:
    cache = CacheManager()
    key = cache.compute_hash({"issue_id": "GH-42", "instruction": "..."})
    if (hit := cache.get(key)) is not None:
        return hit
    result = expensive_operation()
    cache.set(key, result)
    return result
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


class CacheManager:
    """
    Thread-safe (GIL-protected), in-process, content-addressable cache.

    Keys are SHA-256 hex digests of the canonical JSON serialization of
    any JSON-serializable input. Values are arbitrary Python objects.
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_hash(self, input_data: Any) -> str:
        """
        Return the SHA-256 hex digest of the canonical JSON serialization
        of `input_data`.

        Serialization is deterministic: keys are sorted, no extra whitespace.
        Raises `TypeError` if `input_data` is not JSON-serializable.
        """
        canonical = json.dumps(input_data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get(self, hash_key: str) -> Any | None:
        """Return the cached value for `hash_key`, or None on a miss."""
        return self._store.get(hash_key)

    def set(self, hash_key: str, data: Any) -> None:
        """Store `data` under `hash_key`. Overwrites any existing entry."""
        self._store[hash_key] = data

    def invalidate(self, hash_key: str) -> bool:
        """Remove a cache entry. Returns True if it existed."""
        return self._store.pop(hash_key, None) is not None

    def clear(self) -> None:
        """Evict all entries."""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, hash_key: str) -> bool:
        return hash_key in self._store
