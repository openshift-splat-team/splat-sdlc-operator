"""
Promptfoo assertion: validate repo names follow the openshift/* pattern.

Usage in promptfooconfig.yaml:
  assert:
    - type: python
      value: file://evals/assertions/check_repo_names.py
"""
from __future__ import annotations

import json
import re

_VALID_ORG_RE = re.compile(r"^(openshift|operator-framework)/")


def get_assert(output, context):
    try:
        data = json.loads(output) if isinstance(output, str) else output
    except json.JSONDecodeError:
        return {"pass": False, "score": 0.0, "reason": "Invalid JSON"}

    repos = data.get("repos", [])
    if not repos:
        return {"pass": False, "score": 0.0, "reason": "No repos in output"}

    invalid = [
        name for r in repos
        for name in [r.get("name", "")]
        if not _VALID_ORG_RE.match(name)
    ]
    if invalid:
        return {"pass": False, "score": 0.0, "reason": f"Invalid repo names: {invalid}"}

    return {"pass": True, "score": 1.0, "reason": "All repo names valid"}
