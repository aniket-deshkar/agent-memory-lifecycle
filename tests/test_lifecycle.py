from datetime import UTC, datetime, timedelta

import pytest

from agent_memory_lifecycle import (
    MemoryInput,
    MemoryLifecycle,
    MemoryScope,
    RegexRedactor,
    SQLiteMemoryStore,
)


class MutableClock:
    def __init__(self):
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def setup():
    store, clock = SQLiteMemoryStore(), MutableClock()
    yield MemoryLifecycle(store, clock), store, clock
    store.close()


def item(content="Customer prefers tea", **changes):
    values = {
        "tenant_id": "tenant-a",
        "scope": MemoryScope.USER,
        "owner_id": "user-1",
        "content": content,
    }
    values.update(changes)
    return MemoryInput(**values)


def test_persists_and_retrieves_scoped_memory(setup):
    lifecycle, _, _ = setup
    saved = lifecycle.remember(item())
    found = lifecycle.retrieve("tenant-a", MemoryScope.USER, "user-1", "tea", 100)
    assert found[0].memory.id == saved.id
    assert found[0].score > 0


def test_isolates_tenants_scopes_and_owners(setup):
    lifecycle, _, _ = setup
    lifecycle.remember(item())
    assert lifecycle.retrieve("tenant-b", MemoryScope.USER, "user-1", "tea", 100) == []
    assert lifecycle.retrieve("tenant-a", MemoryScope.SESSION, "user-1", "tea", 100) == []
    assert lifecycle.retrieve("tenant-a", MemoryScope.USER, "user-2", "tea", 100) == []


def test_expires_and_removes_ttl_memory(setup):
    lifecycle, _, clock = setup
    lifecycle.remember(item(ttl_seconds=10))
    clock.advance(10)
    assert lifecycle.retrieve("tenant-a", MemoryScope.USER, "user-1", "tea", 100) == []
    assert lifecycle.expire() == 1


def test_deduplicates_normalized_content_and_keeps_deterministic_winner(setup):
    lifecycle, _, clock = setup
    first = lifecycle.remember(item("  Customer PREFERS tea ", importance=0.8))
    clock.advance(1)
    lower = lifecycle.remember(item("customer prefers tea", importance=0.2))
    higher = lifecycle.remember(item("customer prefers tea", importance=0.9))
    assert lower.id == first.id
    assert lower.importance == 0.8
    assert higher.id == first.id
    assert higher.importance == 0.9


def test_retrieval_respects_token_budget_and_relevance(setup):
    lifecycle, _, _ = setup
    lifecycle.remember(item("tea preference", importance=0.4))
    lifecycle.remember(item("coffee preference", importance=1.0))
    results = lifecycle.retrieve("tenant-a", MemoryScope.USER, "user-1", "tea", 4)
    assert [result.memory.content for result in results] == ["tea preference"]
    assert sum(result.estimated_tokens for result in results) <= 4


def test_zero_budget_returns_nothing(setup):
    lifecycle, _, _ = setup
    lifecycle.remember(item())
    assert lifecycle.retrieve("tenant-a", MemoryScope.USER, "user-1", "tea", 0) == []
    with pytest.raises(ValueError):
        lifecycle.retrieve("tenant-a", MemoryScope.USER, "user-1", "tea", -1)


def test_delete_requires_matching_tenant(setup):
    lifecycle, _, _ = setup
    saved = lifecycle.remember(item())
    assert not lifecycle.delete("tenant-b", saved.id)
    assert lifecycle.delete("tenant-a", saved.id)


def test_forget_can_target_owner_and_scope(setup):
    lifecycle, _, _ = setup
    lifecycle.remember(item("one"))
    lifecycle.remember(item("two", owner_id="user-2"))
    lifecycle.remember(item("three", scope=MemoryScope.SESSION))
    assert lifecycle.forget("tenant-a", MemoryScope.USER, "user-1") == 1
    assert len(lifecycle.retrieve("tenant-a", MemoryScope.USER, "user-2", "", 100)) == 1
    assert lifecycle.forget("tenant-a") == 2


def test_redacts_before_fingerprinting_and_storage():
    store, clock = SQLiteMemoryStore(), MutableClock()
    lifecycle = MemoryLifecycle(store, clock, RegexRedactor([r"[\w.]+@[\w.]+"], "[EMAIL]"))
    try:
        saved = lifecycle.remember(item("Contact alice@example.com"))
        assert saved.content == "Contact [EMAIL]"
        assert (
            "alice"
            not in lifecycle.retrieve("tenant-a", MemoryScope.USER, "user-1", "contact", 100)[
                0
            ].memory.content
        )
    finally:
        store.close()


@pytest.mark.parametrize(
    "bad", [item(content=""), item(tenant_id=""), item(importance=1.1), item(ttl_seconds=0)]
)
def test_validates_input(setup, bad):
    with pytest.raises(ValueError):
        setup[0].remember(bad)
