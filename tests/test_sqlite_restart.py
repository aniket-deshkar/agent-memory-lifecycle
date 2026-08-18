from datetime import UTC, datetime

from agent_memory_lifecycle import MemoryInput, MemoryLifecycle, MemoryScope, SQLiteMemoryStore


def test_sqlite_persists_across_process_like_reopen(tmp_path):
    path = tmp_path / "memory.sqlite"
    first = SQLiteMemoryStore(path)
    MemoryLifecycle(first, lambda: datetime(2026, 1, 1, tzinfo=UTC)).remember(
        MemoryInput("tenant", MemoryScope.SEMANTIC, "agent", "persistent fact")
    )
    first.close()
    second = SQLiteMemoryStore(path)
    try:
        found = MemoryLifecycle(second, lambda: datetime(2026, 1, 2, tzinfo=UTC)).retrieve(
            "tenant", MemoryScope.SEMANTIC, "agent", "fact", 100
        )
        assert found[0].memory.content == "persistent fact"
    finally:
        second.close()
