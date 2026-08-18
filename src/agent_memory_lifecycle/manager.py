from __future__ import annotations

import hashlib
import math
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from .model import Memory, MemoryInput, MemoryScope, RetrievedMemory
from .store import SQLiteMemoryStore


class MemoryLifecycle:
    def __init__(
        self,
        store: SQLiteMemoryStore,
        clock: Callable[[], datetime] | None = None,
        redact: Callable[[str], str] | None = None,
    ) -> None:
        self._store, self._clock = store, clock or (lambda: datetime.now(UTC))
        self._redact = redact or (lambda value: value)

    def remember(self, item: MemoryInput) -> Memory:
        if not item.tenant_id or not item.owner_id or not item.content.strip():
            raise ValueError("tenant, owner, and content are required")
        if not 0 <= item.importance <= 1 or (
            item.ttl_seconds is not None and item.ttl_seconds <= 0
        ):
            raise ValueError("invalid importance or TTL")
        now = self._clock()
        content = self._redact(item.content)
        normalized = " ".join(content.casefold().split())
        fingerprint = hashlib.sha256(normalized.encode()).hexdigest()
        expires = now + timedelta(seconds=item.ttl_seconds) if item.ttl_seconds else None
        return self._store.upsert(
            Memory(
                str(uuid.uuid4()),
                item.tenant_id,
                item.scope,
                item.owner_id,
                content,
                fingerprint,
                item.importance,
                now,
                expires,
                item.metadata,
            )
        )

    def retrieve(
        self, tenant_id: str, scope: MemoryScope, owner_id: str, query: str, token_budget: int
    ) -> list[RetrievedMemory]:
        if token_budget < 0:
            raise ValueError("token budget must not be negative")
        query_terms = set(re.findall(r"\w+", query.casefold()))
        results, used = [], 0
        candidates = self._store.list(tenant_id, scope, owner_id, self._clock())
        scored = sorted(
            candidates,
            key=lambda memory: (
                -_score(memory, query_terms),
                -memory.importance,
                -memory.created_at.timestamp(),
                memory.id,
            ),
        )
        for memory in scored:
            tokens = max(1, math.ceil(len(memory.content) / 4))
            if used + tokens > token_budget:
                continue
            results.append(RetrievedMemory(memory, _score(memory, query_terms), tokens))
            used += tokens
        return results

    def expire(self) -> int:
        return self._store.expire(self._clock())

    def delete(self, tenant_id: str, memory_id: str) -> bool:
        return self._store.delete(tenant_id, memory_id)

    def forget(
        self, tenant_id: str, scope: MemoryScope | None = None, owner_id: str | None = None
    ) -> int:
        return self._store.forget(tenant_id, scope, owner_id)


def _score(memory: Memory, terms: set[str]) -> float:
    words = set(re.findall(r"\w+", memory.content.casefold()))
    overlap = len(terms & words) / max(1, len(terms))
    return round((0.8 * overlap) + (0.2 * memory.importance), 6)
