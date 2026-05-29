"""Single entry point for all LLM calls. No agent imports litellm directly."""
from __future__ import annotations

import json
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
    extra: dict[str, Any] = {}
    if settings.llm_api_key:
        extra["api_key"] = settings.llm_api_key
    if settings.llm_api_base:
        extra["api_base"] = settings.llm_api_base

    response = await litellm.acompletion(
        model=settings.litellm_model,
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
    max_tokens: int = 4096,
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
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]

    return response_model.model_validate_json(raw)
