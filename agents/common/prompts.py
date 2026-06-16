"""Load and render Jinja2 prompt templates from the prompts/ directory."""
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

# Resolve prompts/ relative to the repo root (two levels up from this file)
_PROMPTS_DIR = Path(__file__).parents[2] / "prompts"

_env = Environment(
    loader=FileSystemLoader(str(_PROMPTS_DIR)),
    undefined=StrictUndefined,
    auto_reload=True,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)

# Matches <!-- role: system --> or <!-- role: user --> section markers
_SECTION_RE = re.compile(r"<!--\s*role:\s*(\w+)\s*-->")


def render(template_path: str, **variables: object) -> list[dict[str, str]]:
    """
    Load a prompt markdown file and render it into a messages list.

    template_path is relative to prompts/, e.g. "requirements_agent/produce_spec.md".

    Sections are delimited by HTML comment markers:
        <!-- role: system -->
        <!-- role: user -->

    Returns a list of {"role": ..., "content": ...} dicts ready for the LLM.
    """
    template = _env.get_template(template_path)
    rendered = template.render(**variables)

    messages: list[dict[str, str]] = []
    parts = _SECTION_RE.split(rendered)

    # split() with a capturing group gives: [pre, role1, body1, role2, body2, ...]
    # parts[0] is anything before the first marker (discard if empty)
    it = iter(parts[1:])  # skip pre-marker content
    for role, body in zip(it, it):
        content = body.strip()
        messages.append({"role": role.strip(), "content": content})

    if not messages:
        raise ValueError(f"No role sections found in prompt template: {template_path}")

    return messages
