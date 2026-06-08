"""Temporal activities for agent memory operations."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from temporalio import activity

from agents.common import llm, memory
from agents.common.models import MemoryEntry
from agents.common.settings import BaseAgentSettings


@activity.defn
async def save_memory_entry(entry: MemoryEntry) -> str:
    settings = BaseAgentSettings()
    activity.logger.info("Saving memory [%s] for agent %s", entry.category, entry.agent)
    return memory.save_memory(entry, settings)


@activity.defn
async def recall_agent_memories(
    agent: str,
    category: str | None = None,
    tags: list[str] | None = None,
    limit: int = 20,
) -> list[MemoryEntry]:
    settings = BaseAgentSettings()
    activity.logger.info("Recalling memories for agent %s (category=%s)", agent, category)
    return memory.recall_memories(agent, settings, category=category, tags=tags, limit=limit)


@activity.defn
async def extract_observations(
    agent: str,
    run_id: str,
    work_summary: str,
) -> list[MemoryEntry]:
    settings = BaseAgentSettings()
    activity.logger.info("Extracting observations for agent %s from run %s", agent, run_id)

    messages = [
        {
            "role": "system",
            "content": (
                "You are analyzing the results of an automated workflow run. "
                "Extract reusable observations that would help future runs. "
                "Focus on: reviewer preferences learned, architectural decisions made, "
                "process insights, and patterns noticed.\n\n"
                "Return a JSON array of objects, each with:\n"
                '  "category": one of "reviewer_preference", "architectural_decision", '
                '"observation", "process_note"\n'
                '  "content": the observation in a clear, reusable sentence\n'
                '  "tags": list of relevant tags (repo names, tech areas, etc.)\n\n'
                "Return an empty array [] if no useful observations can be extracted. "
                "Do not invent observations not supported by the summary."
            ),
        },
        {
            "role": "user",
            "content": f"## Work Summary from Run {run_id}\n\n{work_summary}",
        },
    ]

    raw = await llm.complete(messages, settings, temperature=0.1)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
    if "[" in raw:
        raw = raw[raw.index("["):raw.rindex("]") + 1]

    items = json.loads(raw)
    entries: list[MemoryEntry] = []
    now = datetime.now(timezone.utc).isoformat()
    for item in items:
        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            agent=agent,
            category=item["category"],
            content=item["content"],
            tags=item.get("tags", []),
            source_run_id=run_id,
            created_at=now,
        )
        memory.save_memory(entry, settings)
        entries.append(entry)

    activity.logger.info("Extracted and saved %d observations", len(entries))
    return entries
