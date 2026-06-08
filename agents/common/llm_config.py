"""Per-agent LLM model/provider configuration loaded from a YAML file.

Call load() once at worker startup (if LLM_CONFIG_PATH is set).
get_override() is called inside llm.complete() to resolve per-agent settings.
Falls back to BaseAgentSettings env-var values when no override is configured.
"""
from __future__ import annotations

from dataclasses import dataclass

import yaml


@dataclass
class LLMOverride:
    model: str | None = None
    api_key: str | None = None
    api_base: str | None = None
    vertex_project: str | None = None
    vertex_location: str | None = None


_default: LLMOverride = LLMOverride()
_overrides: dict[str, LLMOverride] = {}


def load(path: str) -> None:
    """Parse the YAML config file and populate the module-level singleton."""
    global _default, _overrides
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    if d := data.get("default"):
        _default = LLMOverride(
            model=d.get("model") or None,
            api_key=d.get("api_key") or None,
            api_base=d.get("api_base") or None,
            vertex_project=d.get("vertex_project") or None,
            vertex_location=d.get("vertex_location") or None,
        )

    _overrides = {
        task_queue: LLMOverride(
            model=cfg.get("model") or None,
            api_key=cfg.get("api_key") or None,
            api_base=cfg.get("api_base") or None,
            vertex_project=cfg.get("vertex_project") or None,
            vertex_location=cfg.get("vertex_location") or None,
        )
        for task_queue, cfg in (data.get("agents") or {}).items()
    }


def get_override(task_queue: str) -> LLMOverride:
    """Return merged override for task_queue; fields are None when not configured."""
    agent_cfg = _overrides.get(task_queue)
    return LLMOverride(
        model=(agent_cfg.model if agent_cfg and agent_cfg.model else _default.model),
        api_key=(agent_cfg.api_key if agent_cfg and agent_cfg.api_key else _default.api_key),
        api_base=(agent_cfg.api_base if agent_cfg and agent_cfg.api_base else _default.api_base),
        vertex_project=(agent_cfg.vertex_project if agent_cfg and agent_cfg.vertex_project else _default.vertex_project),
        vertex_location=(agent_cfg.vertex_location if agent_cfg and agent_cfg.vertex_location else _default.vertex_location),
    )
