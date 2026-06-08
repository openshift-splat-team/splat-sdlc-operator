"""Single entry point for all LLM calls. No agent imports litellm directly."""
from __future__ import annotations

import json
import re
from typing import Any, TypeVar

import litellm
from pydantic import BaseModel

from agents.common.settings import BaseAgentSettings

T = TypeVar("T", bound=BaseModel)

litellm.drop_params = True  # ignore unsupported params silently


async def complete(
    messages: list[dict[str, str]],
    settings: BaseAgentSettings,
    *,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    **kwargs: Any,
) -> str:
    from agents.common.llm_config import get_override

    override = get_override(settings.temporal_task_queue)
    model = override.model or settings.litellm_model
    api_key = override.api_key or settings.llm_api_key
    api_base = override.api_base or settings.llm_api_base

    vertex_project = override.vertex_project or settings.vertex_project
    vertex_location = override.vertex_location or settings.vertex_location

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
    return response.choices[0].message.content or ""


async def complete_structured(
    messages: list[dict[str, str]],
    settings: BaseAgentSettings,
    response_model: type[T],
    *,
    temperature: float = 0.2,
    max_tokens: int = 32768,
) -> T:
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
