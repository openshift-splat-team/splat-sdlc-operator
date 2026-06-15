"""Run CI test commands in ephemeral Podman/Docker containers."""
from __future__ import annotations

import logging
import time

import docker

from agents.common.models import CITest, TestResult
from agents.common.settings import GitHubAgentSettings

logger = logging.getLogger(__name__)

_MAX_OUTPUT = 4096
_DEFAULT_TIMEOUT = 300


def _truncate(text: str, limit: int = _MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[output truncated]"


def run_tests(
    clone_url: str,
    branch: str,
    tests: list[CITest],
    settings: GitHubAgentSettings,
) -> list[TestResult]:
    """Run each CI test in an ephemeral container and return results."""
    socket_url = f"unix://{settings.container_socket}"
    try:
        client = docker.DockerClient(base_url=socket_url)
        client.ping()
    except Exception as exc:
        logger.warning("Container runtime unavailable (%s); skipping tests", exc)
        return []
    results: list[TestResult] = []

    for test in tests:
        logger.info("Running test '%s': %s", test.name, test.commands[:80])
        t0 = time.time()

        script = (
            f"set -e\n"
            f"git clone --depth 1 --branch {branch} {clone_url} /workspace\n"
            f"cd /workspace\n"
            f"{test.commands}\n"
        )

        try:
            container = client.containers.run(
                image=settings.go_builder_image,
                command=["bash", "-c", script],
                detach=True,
                remove=False,
                environment={"GOFLAGS": "-mod=vendor", "ARTIFACT_DIR": "/tmp/artifacts"},
                mem_limit="4g",
                network_mode="bridge",
            )

            exit_info = container.wait(timeout=_DEFAULT_TIMEOUT)
            exit_code = exit_info.get("StatusCode", -1)
            logs = container.logs().decode("utf-8", errors="replace")

            try:
                container.remove(force=True)
            except Exception:
                pass

            elapsed = time.time() - t0
            passed = exit_code == 0
            level = logging.INFO if passed else logging.WARNING
            logger.log(level, "Test '%s' %s (exit=%d, %.1fs)", test.name, "PASSED" if passed else "FAILED", exit_code, elapsed)

            results.append(TestResult(
                test_name=test.name,
                passed=passed,
                exit_code=exit_code,
                stdout=_truncate(logs),
                stderr="",
                duration_secs=round(elapsed, 1),
            ))

        except Exception as exc:
            elapsed = time.time() - t0
            logger.error("Test '%s' errored: %s", test.name, exc)
            results.append(TestResult(
                test_name=test.name,
                passed=False,
                exit_code=-1,
                stdout="",
                stderr=_truncate(str(exc)),
                duration_secs=round(elapsed, 1),
            ))

    return results
