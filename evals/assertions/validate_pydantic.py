"""
Promptfoo assertion: validate LLM output against a Pydantic model.

Usage in promptfooconfig.yaml:
  assert:
    - type: python
      value: file://evals/assertions/validate_pydantic.py
      config:
        model: RepoIdentificationResult
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.common import models


def get_assert(output, context):
    model_name = context.get("config", {}).get("model")
    if not model_name:
        return {"pass": False, "score": 0.0, "reason": "No 'model' specified in assertion config"}

    model_class = getattr(models, model_name, None)
    if model_class is None:
        return {"pass": False, "score": 0.0, "reason": f"Unknown model: {model_name}"}

    try:
        parsed = json.loads(output) if isinstance(output, str) else output
        model_class.model_validate(parsed)
        return {"pass": True, "score": 1.0, "reason": f"Valid {model_name}"}
    except json.JSONDecodeError as e:
        return {"pass": False, "score": 0.0, "reason": f"Invalid JSON: {e}"}
    except Exception as e:
        return {"pass": False, "score": 0.0, "reason": f"Pydantic validation failed for {model_name}: {e}"}
