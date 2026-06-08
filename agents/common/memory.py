"""Agent memory: save and recall observations across workflow runs."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from minio.error import S3Error

from agents.common.models import MemoryEntry, MemoryIndex
from agents.common.settings import BaseAgentSettings
from agents.common.storage import get_artifact, put_artifact


def _index_key(agent: str) -> str:
    return f"memory/{agent}/index.json"


def _load_index(agent: str, settings: BaseAgentSettings) -> MemoryIndex:
    try:
        return get_artifact(_index_key(agent), MemoryIndex, settings)  # type: ignore[return-value]
    except S3Error:
        return MemoryIndex(agent=agent)


def save_memory(entry: MemoryEntry, settings: BaseAgentSettings) -> str:
    if not entry.id:
        entry.id = str(uuid.uuid4())
    if not entry.created_at:
        entry.created_at = datetime.now(timezone.utc).isoformat()

    index = _load_index(entry.agent, settings)
    index.entries = [e for e in index.entries if e.id != entry.id]
    index.entries.append(entry)
    put_artifact(_index_key(index.agent), index, settings)
    return entry.id


def recall_memories(
    agent: str,
    settings: BaseAgentSettings,
    *,
    category: str | None = None,
    tags: list[str] | None = None,
    limit: int = 50,
) -> list[MemoryEntry]:
    index = _load_index(agent, settings)
    results = index.entries

    if category:
        results = [e for e in results if e.category == category]
    if tags:
        tag_set = set(tags)
        results = [e for e in results if tag_set.intersection(e.tags)]

    results.sort(key=lambda e: e.created_at, reverse=True)
    return results[:limit]


def format_memories_for_prompt(memories: list[MemoryEntry]) -> str:
    if not memories:
        return ""
    lines = ["## Relevant Memories from Previous Runs\n"]
    for m in memories:
        tag_str = f" [{', '.join(m.tags)}]" if m.tags else ""
        lines.append(f"- **[{m.category}]**{tag_str}: {m.content}")
    return "\n".join(lines)
