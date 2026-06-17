"""Generate Gitea Actions workflow YAML from CITest definitions."""
from __future__ import annotations

import re

import yaml

from agents.common.models import CITest


def _sanitize_job_key(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9-]", "-", name).strip("-").lower()[:64]


def generate_ci_workflow(tests: list[CITest], go_image: str) -> str:
    jobs = {}
    for test in tests:
        key = _sanitize_job_key(test.name)
        if key in jobs:
            key = f"{key}-{len(jobs)}"
        jobs[key] = {
            "runs-on": "ubuntu-latest",
            "container": {"image": go_image},
            "steps": [
                {
                    "name": "checkout",
                    "run": "git clone --depth 1 --branch ${GITHUB_REF_NAME} ${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}.git .\n",
                },
                {
                    "name": test.name,
                    "run": test.commands,
                    "env": {
                        "GOFLAGS": "-mod=vendor",
                        "ARTIFACT_DIR": "/tmp/artifacts",
                    },
                },
            ],
        }

    workflow = {
        "name": "CI",
        "on": ["push"],
        "jobs": jobs,
    }
    return yaml.safe_dump(workflow, sort_keys=False, default_flow_style=False)
