"""
Promptfoo assertion: validate pr_sequence respects OpenShift tier hierarchy.

A step should not be blocked by a higher-numbered tier (Tier 0 must land
before Tier 1, etc.).

Usage in promptfooconfig.yaml:
  assert:
    - type: python
      value: file://evals/assertions/check_tier_ordering.py
"""
from __future__ import annotations

import json
import re


_TIER_RE = re.compile(r"Tier\s*(\d+)", re.IGNORECASE)


def _tier_num(tier_str: str) -> int:
    m = _TIER_RE.search(tier_str)
    return int(m.group(1)) if m else 99


def get_assert(output, context):
    try:
        data = json.loads(output) if isinstance(output, str) else output
    except json.JSONDecodeError:
        return {"pass": False, "score": 0.0, "reason": "Invalid JSON"}

    steps = data.get("pr_sequence", [])
    if not steps:
        return {"pass": True, "score": 1.0, "reason": "No pr_sequence to check"}

    step_map = {s["step"]: s for s in steps}

    for step in steps:
        blocked_by = step.get("blocked_by_step")
        if blocked_by is None:
            continue
        blocking = step_map.get(blocked_by)
        if not blocking:
            continue
        if _tier_num(blocking.get("tier", "")) > _tier_num(step.get("tier", "")):
            return {
                "pass": False,
                "score": 0.0,
                "reason": (
                    f"Step {step['step']} ({step.get('tier')}) is blocked by "
                    f"step {blocked_by} ({blocking.get('tier')}), violating tier ordering"
                ),
            }

    return {"pass": True, "score": 1.0, "reason": "Tier ordering respected"}
