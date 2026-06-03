"""
Promptfoo custom Python provider.

Bridges promptfoo (Node.js) to the project's prompts.render() + llm.complete()
pipeline. Each test case passes a __template_path var that selects the Jinja2
template; remaining vars are the template variables.

Provider config (litellm_model, llm_api_base, temperature, etc.) comes from the
provider block in promptfooconfig.yaml, so model comparison works by defining
multiple providers with different configs.

Usage in promptfooconfig.yaml:
  providers:
    - id: file://evals/provider.py
      config:
        litellm_model: openai/Qwen3-14B
        llm_api_base: http://localhost:8000/v1
        llm_api_key: any
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.common.llm import complete, complete_structured
from agents.common.models import (
    CIRequirements,
    EnhancementDoc,
    OpenShiftFeaturePlan,
    RepoIdentificationResult,
    RequirementSpec,
    ReviewResult,
    StoryPlan,
)
from agents.common.prompts import render
from agents.common.settings import BaseAgentSettings

TEMPLATE_MODEL_MAP: dict[str, type] = {
    "requirements_agent/produce_spec.md": RequirementSpec,
    "requirements_agent/propose_stories.md": StoryPlan,
    "requirements_agent/refine_stories.md": StoryPlan,
    "openshift_agent/identify_repos.md": RepoIdentificationResult,
    "openshift_agent/analyze_feature.md": OpenShiftFeaturePlan,
    "openshift_agent/ci_requirements.md": CIRequirements,
    "github_agent/run_review.md": ReviewResult,
    "enhancement_agent/generate_doc.md": EnhancementDoc,
}

_DEP_MAP_TEMPLATES = {
    "openshift_agent/identify_repos.md",
    "openshift_agent/analyze_feature.md",
    "openshift_agent/ci_requirements.md",
}

_DEP_MAP_PATH = Path(__file__).parent.parent / "prompts" / "openshift_agent" / "knowledge" / "dependency_map.md"


class _EvalSettings(BaseAgentSettings):
    model_config = {"env_file": None, "extra": "ignore"}
    temporal_task_queue: str = "eval"


def _make_settings(config: dict) -> _EvalSettings:
    api_base = config.get("llm_api_base") or None
    return _EvalSettings(
        litellm_model=config.get("litellm_model", "openai/gpt-4o"),
        llm_api_key=config.get("llm_api_key", ""),
        llm_api_base=api_base,
    )


def _preprocess_vars(template_path: str, vars_: dict) -> dict:
    processed = dict(vars_)

    if template_path in _DEP_MAP_TEMPLATES and "dependency_map" not in processed:
        processed["dependency_map"] = _DEP_MAP_PATH.read_text()

    for key, val in list(processed.items()):
        if isinstance(val, str) and val.strip().startswith(("{", "[")):
            try:
                processed[key] = json.loads(val)
            except json.JSONDecodeError:
                pass

    return processed


def call_api(prompt, options, context):
    vars_ = dict(context.get("vars", {}))
    template_path = vars_.pop("__template_path", None)
    if not template_path:
        return {"output": "", "error": "Test case missing required '__template_path' var"}

    config = options.get("config", {})
    temperature = float(config.get("temperature", 0.2))
    max_tokens = int(config.get("max_tokens", 4096))

    settings = _make_settings(config)
    processed_vars = _preprocess_vars(template_path, vars_)
    messages = render(template_path, **processed_vars)

    response_model = TEMPLATE_MODEL_MAP.get(template_path)
    if response_model:
        result = asyncio.run(
            complete_structured(
                messages, settings, response_model,
                temperature=temperature, max_tokens=max_tokens,
            )
        )
        output = result.model_dump_json(indent=2)
    else:
        output = asyncio.run(
            complete(messages, settings, temperature=temperature, max_tokens=max_tokens)
        )

    return {"output": output}
