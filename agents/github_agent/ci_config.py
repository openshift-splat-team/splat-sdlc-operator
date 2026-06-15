"""Fetch and parse ci-operator configs from openshift/release."""
from __future__ import annotations

import fnmatch
import logging

import requests
import yaml

from agents.common import storage
from agents.common.models import CITest
from agents.common.settings import GitHubAgentSettings

logger = logging.getLogger(__name__)

_RELEASE_RAW = "https://raw.githubusercontent.com/openshift/release/master"
_INFRA_PATTERNS = {"e2e-*", "upgrade*", "conformance*"}


def _is_lightweight(test: dict) -> bool:
    if "steps" in test or "cluster_profile" in test:
        return False
    if "commands" not in test:
        return False
    name = test.get("as", "")
    for pat in _INFRA_PATTERNS:
        if fnmatch.fnmatch(name, pat):
            return False
    return True


def _apply_exclusions(tests: list[CITest], exclusions: list[str]) -> list[CITest]:
    if not exclusions:
        return tests
    return [
        t for t in tests
        if not any(fnmatch.fnmatch(t.name, pat) for pat in exclusions)
    ]


def fetch_ci_config(
    repo_name: str,
    branch: str,
    settings: GitHubAgentSettings,
) -> list[CITest]:
    """Fetch ci-operator config for a repo from openshift/release.

    Returns lightweight (non-infrastructure) test definitions.
    Results are cached in S3 by repo+branch.
    """
    cache_key = f"ci-config/openshift/{repo_name}-{branch}.json"

    # Check cache
    try:
        cached = storage.get_json(cache_key, settings)
    except Exception:
        cached = None
    if cached and isinstance(cached.get("tests"), list):
        tests = [CITest(**t) for t in cached["tests"]]
        logger.info("CI config cache hit for %s@%s (%d tests)", repo_name, branch, len(tests))
        return _apply_exclusions(tests, settings.test_exclusions)

    # Fetch from openshift/release
    config_url = (
        f"{_RELEASE_RAW}/ci-operator/config/openshift/{repo_name}"
        f"/openshift-{repo_name}-{branch}.yaml"
    )
    logger.info("Fetching CI config from %s", config_url)
    try:
        resp = requests.get(config_url, timeout=15)
    except requests.RequestException as exc:
        logger.warning("Failed to fetch CI config for %s: %s", repo_name, exc)
        return []

    if resp.status_code != 200:
        logger.warning("CI config not found for %s@%s (HTTP %d)", repo_name, branch, resp.status_code)
        return []

    try:
        config = yaml.safe_load(resp.text)
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse CI config for %s: %s", repo_name, exc)
        return []

    raw_tests = config.get("tests", [])
    tests: list[CITest] = []
    for t in raw_tests:
        if _is_lightweight(t):
            tests.append(CITest(
                name=t.get("as", "unknown"),
                commands=t.get("commands", "").strip(),
                container_from=t.get("container", {}).get("from", "src"),
            ))

    logger.info(
        "Parsed %d lightweight tests from %d total for %s@%s",
        len(tests), len(raw_tests), repo_name, branch,
    )

    # Cache the result
    try:
        storage.put_json(
            cache_key,
            {"tests": [t.model_dump() for t in tests]},
            settings,
        )
    except Exception:
        pass

    return _apply_exclusions(tests, settings.test_exclusions)
