"""Single entry point for all LLM calls. No agent imports litellm directly."""
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any, TypeVar

import litellm
from pydantic import BaseModel

from agents.common.settings import BaseAgentSettings

T = TypeVar("T", bound=BaseModel)

litellm.drop_params = True  # ignore unsupported params silently

_log = logging.getLogger(__name__)


def _store_usage(
    run_id: str,
    step: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    settings: BaseAgentSettings,
) -> None:
    from agents.common.storage import get_json, put_json

    key = f"runs/{run_id}/token-usage.json"
    existing = get_json(key, settings)
    records: list[dict[str, Any]] = existing if isinstance(existing, list) else []
    records.append({
        "timestamp": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "step": step,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    })
    try:
        put_json(key, records, settings)
    except Exception:
        _log.warning("Failed to store token usage for %s", run_id, exc_info=True)


def _get_activity_context() -> tuple[str | None, str | None]:
    """Extract run_id and activity name from Temporal context, if available."""
    try:
        from temporalio import activity as _act
        info = _act.info()
        wf_id = info.workflow_id or ""
        parts = wf_id.split("-", 1)
        run_id = parts[0] if len(parts) >= 2 else wf_id
        return run_id, info.activity_type
    except Exception:
        return None, None


_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_MAX_TOKENS_STRUCTURED = 32768
_DEFAULT_CONTEXT_BUDGET = 29_000


def get_context_budget(settings: BaseAgentSettings) -> int:
    """Return the configured repo-context budget (bytes) for this agent's model."""
    from agents.common.llm_config import get_override

    override = get_override(settings.temporal_task_queue)
    return override.context_budget or _DEFAULT_CONTEXT_BUDGET


async def complete(
    messages: list[dict[str, str]],
    settings: BaseAgentSettings,
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    **kwargs: Any,
) -> str:
    from agents.common.llm_config import get_override

    override = get_override(settings.temporal_task_queue)
    model = override.model or settings.litellm_model
    api_key = override.api_key or settings.llm_api_key
    api_base = override.api_base or settings.llm_api_base

    vertex_project = override.vertex_project or settings.vertex_project
    vertex_location = override.vertex_location or settings.vertex_location

    if max_tokens is None:
        max_tokens = override.max_tokens or _DEFAULT_MAX_TOKENS

    extra: dict[str, Any] = {}
    if api_key:
        extra["api_key"] = api_key
    if api_base:
        extra["api_base"] = api_base
    if vertex_project:
        extra["vertex_project"] = vertex_project
    if vertex_location:
        extra["vertex_location"] = vertex_location

    response = await litellm.acompletion(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        **extra,
        **kwargs,
    )

    if response.usage:
        run_id, step = _get_activity_context()
        if run_id:
            _store_usage(
                run_id=run_id,
                step=step or "unknown",
                model=model,
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                total_tokens=response.usage.total_tokens or 0,
                settings=settings,
            )

    return response.choices[0].message.content or ""


async def complete_structured(
    messages: list[dict[str, str]],
    settings: BaseAgentSettings,
    response_model: type[T],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> T:
    if max_tokens is None:
        from agents.common.llm_config import get_override

        override = get_override(settings.temporal_task_queue)
        max_tokens = override.max_tokens_structured or _DEFAULT_MAX_TOKENS_STRUCTURED

    schema = response_model.model_json_schema()
    system_instruction = (
        "Respond ONLY with a valid JSON object matching this schema. "
        "Do not include markdown fences or any other text.\n\n"
        f"Schema:\n{json.dumps(schema, indent=2)}"
    )

    augmented = [{"role": "system", "content": system_instruction}, *messages]

    raw = await complete(augmented, settings, temperature=temperature, max_tokens=max_tokens)

    raw = raw.strip()
    # Strip complete <think>...</think> blocks (reasoning models e.g. Qwen3)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    # Strip unclosed <think> block — model ran out of tokens mid-thought, no JSON follows
    if "<think>" in raw:
        raw = raw[: raw.index("<think>")].strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
    # Clamp to the outermost JSON object, discarding any trailing text
    if "{" in raw:
        raw = raw[raw.index("{") : raw.rindex("}") + 1]

    return response_model.model_validate_json(raw)
