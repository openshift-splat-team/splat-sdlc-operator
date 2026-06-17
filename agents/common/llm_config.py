"""Per-agent LLM model/provider configuration loaded from a YAML file.

Call load() once at worker startup (if LLM_CONFIG_PATH is set).
get_override() is called inside llm.complete() to resolve per-agent settings.
Falls back to BaseAgentSettings env-var values when no override is configured.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml


@dataclass
class LLMOverride:
    model: str | None = None
    api_key: str | None = None
    api_base: str | None = None
    vertex_project: str | None = None
    vertex_location: str | None = None
    max_tokens: int | None = None
    max_tokens_structured: int | None = None
    context_budget: int | None = None


_default: LLMOverride = LLMOverride()
_overrides: dict[str, LLMOverride] = {}


def _parse_override(cfg: dict) -> LLMOverride:
    return LLMOverride(
        model=cfg.get("model") or None,
        api_key=cfg.get("api_key") or None,
        api_base=cfg.get("api_base") or None,
        vertex_project=cfg.get("vertex_project") or None,
        vertex_location=cfg.get("vertex_location") or None,
        max_tokens=cfg.get("max_tokens"),
        max_tokens_structured=cfg.get("max_tokens_structured"),
        context_budget=cfg.get("context_budget"),
    )


def load(path: str) -> None:
    """Parse the YAML config file and populate the module-level singleton."""
    global _default, _overrides
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    if d := data.get("default"):
        _default = _parse_override(d)

    _overrides = {
        task_queue: _parse_override(cfg)
        for task_queue, cfg in (data.get("agents") or {}).items()
    }


def _merge(agent_val: Any, default_val: Any) -> Any:
    return agent_val if agent_val is not None else default_val


def get_override(task_queue: str) -> LLMOverride:
    """Return merged override for task_queue; fields are None when not configured."""
    a = _overrides.get(task_queue)
    d = _default
    if not a:
        return d
    return LLMOverride(
        model=_merge(a.model, d.model),
        api_key=_merge(a.api_key, d.api_key),
        api_base=_merge(a.api_base, d.api_base),
        vertex_project=_merge(a.vertex_project, d.vertex_project),
        vertex_location=_merge(a.vertex_location, d.vertex_location),
        max_tokens=_merge(a.max_tokens, d.max_tokens),
        max_tokens_structured=_merge(a.max_tokens_structured, d.max_tokens_structured),
        context_budget=_merge(a.context_budget, d.context_budget),
    )
