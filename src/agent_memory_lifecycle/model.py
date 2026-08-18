from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class MemoryScope(StrEnum):
    WORKING = "working"
    SESSION = "session"
    USER = "user"
    SEMANTIC = "semantic"


@dataclass(frozen=True)
class Memory:
    id: str
    tenant_id: str
    scope: MemoryScope
    owner_id: str
    content: str
    fingerprint: str
    importance: float
    created_at: datetime
    expires_at: datetime | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryInput:
    tenant_id: str
    scope: MemoryScope
    owner_id: str
    content: str
    importance: float = 0.5
    ttl_seconds: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievedMemory:
    memory: Memory
    score: float
    estimated_tokens: int
