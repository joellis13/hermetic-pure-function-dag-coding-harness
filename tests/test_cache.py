"""Tests for hermetic.data.cache — content-addressable cache."""
import pytest

from hermetic.data.cache import CacheManager


class TestCacheManager:
    def setup_method(self):
        self.cache = CacheManager()

    def test_get_miss_returns_none(self):
        assert self.cache.get("nonexistent") is None

    def test_set_and_get(self):
        key = self.cache.compute_hash({"a": 1})
        self.cache.set(key, "result")
        assert self.cache.get(key) == "result"

    def test_hash_determinism(self):
        """Same input must always produce the same hash."""
        data = {"issue_id": "GH-42", "instruction": "Do X"}
        assert self.cache.compute_hash(data) == self.cache.compute_hash(data)

    def test_hash_key_order_independent(self):
        """Hash must be identical regardless of dict key insertion order."""
        h1 = self.cache.compute_hash({"a": 1, "b": 2})
        h2 = self.cache.compute_hash({"b": 2, "a": 1})
        assert h1 == h2

    def test_different_inputs_produce_different_hashes(self):
        h1 = self.cache.compute_hash({"a": 1})
        h2 = self.cache.compute_hash({"a": 2})
        assert h1 != h2

    def test_hash_is_sha256_hex(self):
        h = self.cache.compute_hash("hello")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_overwrite(self):
        key = self.cache.compute_hash("key")
        self.cache.set(key, "v1")
        self.cache.set(key, "v2")
        assert self.cache.get(key) == "v2"

    def test_invalidate_existing(self):
        key = self.cache.compute_hash("x")
        self.cache.set(key, "val")
        assert self.cache.invalidate(key) is True
        assert self.cache.get(key) is None

    def test_invalidate_nonexistent(self):
        assert self.cache.invalidate("ghost") is False

    def test_clear(self):
        for i in range(5):
            k = self.cache.compute_hash(i)
            self.cache.set(k, i)
        assert len(self.cache) == 5
        self.cache.clear()
        assert len(self.cache) == 0

    def test_contains(self):
        k = self.cache.compute_hash("ping")
        assert k not in self.cache
        self.cache.set(k, "pong")
        assert k in self.cache

    def test_non_serializable_raises(self):
        with pytest.raises(TypeError):
            self.cache.compute_hash(object())  # not JSON-serializable

    def test_pydantic_model_serializable_via_model_dump(self):
        """Models must be .model_dump()'d before hashing."""
        from hermetic.schemas import IssueContext
        ctx = IssueContext(issue_id="GH-1", title="T", description="D")
        # model_dump() produces a JSON-serializable dict
        h = self.cache.compute_hash(ctx.model_dump())
        assert isinstance(h, str)
