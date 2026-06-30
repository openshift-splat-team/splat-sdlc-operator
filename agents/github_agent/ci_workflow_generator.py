"""Generate Gitea Actions workflow YAML from CITest definitions."""
from __future__ import annotations

import logging
import re

import yaml

from agents.common.models import CITest

log = logging.getLogger(__name__)

_GOLANGCI_LINT_V2 = "v2.7.0"
_GOLANGCI_LINT_V1 = "v1.64.8"

_CHECKOUT_CMD = (
    "git clone --depth 1 --branch ${GITHUB_REF_NAME} "
    "${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}.git .\n"
)

_GOLANGCI_CONFIGS = {".golangci.yml", ".golangci.yaml", ".golangci.toml", ".golangci.json"}

_TOOL_INSTALLERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bshellcheck\b"), "apt-get update -qq && apt-get install -y -qq shellcheck\n"),
    (re.compile(r"\byaml[-_]?lint\b"), "pip install --quiet yamllint\n"),
    (re.compile(r"\bgolint\b"), "go install golang.org/x/lint/golint@latest\n"),
    (re.compile(r"\bcommitchecker\b"), "go install github.com/openshift-eng/openshift-tests-private/cmd/commitchecker@latest\n"),
]


def _build_setup_cmd(commands: str) -> str:
    """Return install commands for external tools referenced in *commands*."""
    parts: list[str] = []
    for pattern, installer in _TOOL_INSTALLERS:
        if pattern.search(commands):
            parts.append(installer)
    return "".join(parts)


def detect_go_image(go_mod_content: str | None, fallback: str) -> str:
    """Parse go.mod to find the required Go version and return a matching container image."""
    if not go_mod_content:
        return fallback
    for line in go_mod_content.splitlines():
        line = line.strip()
        if line.startswith("go ") and not line.startswith("go."):
            version = line.split()[1]
            parts = version.split(".")
            if len(parts) >= 2:
                return f"golang:{parts[0]}.{parts[1]}"
    return fallback


def _sanitize_job_key(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9-]", "-", name).strip("-").lower()[:64]


def _detect_lint_version(config_content: str | None) -> tuple[str, str] | None:
    """Detect golangci-lint version from config content.

    Returns (install_path, version) or None if the job should be skipped
    (e.g. custom plugin referenced).
    """
    if config_content and re.search(r"\.so\b", config_content) and re.search(r"\bplugin\b|\bcustom\b", config_content):
        log.info("golangci-lint config references custom plugin — skipping lint job")
        return None
    if config_content and re.search(r"^version\s*:", config_content, re.MULTILINE):
        return (f"github.com/golangci/golangci-lint/v2/cmd/golangci-lint@{_GOLANGCI_LINT_V2}", _GOLANGCI_LINT_V2)
    return (f"github.com/golangci/golangci-lint/cmd/golangci-lint@{_GOLANGCI_LINT_V1}", _GOLANGCI_LINT_V1)


def generate_ci_workflow(
    tests: list[CITest],
    go_image: str,
    repo_files: list[str] | None = None,
    golangci_lint_config: str | None = None,
) -> str:
    jobs: dict = {}

    is_go_module = repo_files is None or "go.mod" in repo_files

    if is_go_module:
        jobs["vet"] = {
            "runs-on": "ubuntu-latest",
            "container": {"image": go_image},
            "steps": [
                {"name": "checkout", "run": _CHECKOUT_CMD},
                {
                    "name": "go vet",
                    "run": "go vet ./...",
                    "env": {"GOFLAGS": "-mod=vendor"},
                },
            ],
        }

    has_lint_config = is_go_module and bool(_GOLANGCI_CONFIGS & set(repo_files or []))
    if has_lint_config:
        lint_info = _detect_lint_version(golangci_lint_config)
        if lint_info is not None:
            install_path, version = lint_info
            jobs["golangci-lint"] = {
                "runs-on": "ubuntu-latest",
                "container": {"image": go_image},
                "steps": [
                    {"name": "checkout", "run": _CHECKOUT_CMD},
                    {
                        "name": "golangci-lint",
                        "run": (
                            f"go install {install_path}\n"
                            "golangci-lint run ./...\n"
                        ),
                        "env": {"GOFLAGS": ""},
                    },
                ],
            }
        else:
            log.info("Skipping golangci-lint job (custom plugin detected)")

    for test in tests:
        key = _sanitize_job_key(test.name)
        if key in jobs:
            key = f"{key}-{len(jobs)}"

        steps = [{"name": "checkout", "run": _CHECKOUT_CMD}]

        setup_cmd = _build_setup_cmd(test.commands)
        if setup_cmd:
            steps.append({"name": "install-tools", "run": setup_cmd})

        steps.append({
            "name": test.name,
            "run": test.commands,
            "env": {
                "GOFLAGS": "-mod=vendor",
                "ARTIFACT_DIR": "/tmp/artifacts",
            },
        })

        jobs[key] = {
            "runs-on": "ubuntu-latest",
            "container": {"image": go_image},
            "steps": steps,
        }

    for job in jobs.values():
        job["if"] = "github.event.label.name == 'ok-to-test'"

    workflow = {
        "name": "CI",
        "on": {"pull_request": {"types": ["labeled"]}},
        "jobs": jobs,
    }
    return yaml.safe_dump(workflow, sort_keys=False, default_flow_style=False)
