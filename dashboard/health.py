"""Health checking for infrastructure services and Temporal workers."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import aiohttp
from temporalio.client import Client
from temporalio.service import RPCError


@dataclass
class ServiceStatus:
    name: str
    healthy: bool
    detail: str = ""
    url: str | None = None


INFRA_SERVICES: list[dict[str, str]] = [
    {
        "name": "Temporal",
        "probe_url": "",
        "external_url": "",
        "kind": "temporal",
    },
    {
        "name": "RustFS (S3)",
        "probe_url": "http://rustfs:9000/health/ready",
        "external_url": "http://localhost:9001",
        "kind": "http",
    },
    {
        "name": "Ollama",
        "probe_url": "http://ollama:11434/api/tags",
        "external_url": "http://localhost:11434",
        "kind": "http",
    },
    {
        "name": "Gitea",
        "probe_url": "http://gitea:3000/api/v1/version",
        "external_url": "http://localhost:3000",
        "kind": "http",
    },
    {
        "name": "Jira Simulator",
        "probe_url": "http://jira-simulator:8080/rest/api/2/serverInfo",
        "external_url": "http://localhost:8080",
        "kind": "http",
    },
    {
        "name": "Dep-Tree MCP",
        "probe_url": "http://dep-tree:8000/sse",
        "external_url": "http://localhost:8000",
        "kind": "http",
    },
]

WORKER_TASK_QUEUES: list[dict[str, str]] = [
    {"name": "Orchestrator", "task_queue": "orchestrator"},
    {"name": "Requirements Agent", "task_queue": "requirements-agent"},
    {"name": "GitHub Agent", "task_queue": "github-agent"},
    {"name": "OpenShift Agent", "task_queue": "openshift-agent"},
    {"name": "Jira Agent", "task_queue": "jira-agent"},
    {"name": "Enhancement Agent", "task_queue": "enhancement-agent"},
]


@dataclass
class HealthCache:
    infra: list[ServiceStatus] = field(default_factory=list)
    workers: list[ServiceStatus] = field(default_factory=list)
    timestamp: float = 0.0
    ttl: float = 5.0

    def is_fresh(self) -> bool:
        return time.monotonic() - self.timestamp < self.ttl


_cache = HealthCache()


async def _probe_http(url: str, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status < 400:
                    return True, f"HTTP {resp.status}"
                return False, f"HTTP {resp.status}"
    except Exception as exc:
        return False, str(exc)[:80]


async def _check_infra(temporal_host: str, external_urls: dict[str, str]) -> list[ServiceStatus]:
    results: list[ServiceStatus] = []

    for svc in INFRA_SERVICES:
        ext_url = external_urls.get(svc["name"], svc["external_url"])
        if svc["kind"] == "temporal":
            try:
                client = await Client.connect(temporal_host, namespace="default")
                info = await client.service_client.check_health()
                _ = info
                results.append(ServiceStatus(
                    name=svc["name"], healthy=True, detail="connected",
                    url=external_urls.get("Temporal UI", "http://localhost:8233"),
                ))
            except Exception as exc:
                results.append(ServiceStatus(
                    name=svc["name"], healthy=False, detail=str(exc)[:80],
                    url=external_urls.get("Temporal UI", "http://localhost:8233"),
                ))
        else:
            ok, detail = await _probe_http(svc["probe_url"])
            results.append(ServiceStatus(
                name=svc["name"], healthy=ok, detail=detail, url=ext_url,
            ))

    return results


async def _check_workers(temporal_host: str) -> list[ServiceStatus]:
    results: list[ServiceStatus] = []
    try:
        client = await Client.connect(temporal_host, namespace="default")
    except Exception as exc:
        return [
            ServiceStatus(name=w["name"], healthy=False, detail=f"Temporal unreachable: {exc}"[:80])
            for w in WORKER_TASK_QUEUES
        ]

    for w in WORKER_TASK_QUEUES:
        try:
            resp = await client.service_client.workflow_service.describe_task_queue(
                _build_describe_request(w["task_queue"], "default")
            )
            poller_count = len(resp.pollers)
            if poller_count > 0:
                results.append(ServiceStatus(
                    name=w["name"], healthy=True,
                    detail=f"{poller_count} poller(s)",
                ))
            else:
                results.append(ServiceStatus(
                    name=w["name"], healthy=False, detail="no pollers",
                ))
        except RPCError as exc:
            results.append(ServiceStatus(
                name=w["name"], healthy=False, detail=str(exc)[:80],
            ))

    return results


def _build_describe_request(task_queue: str, namespace: str):  # type: ignore[no-untyped-def]
    from temporalio.api.enums.v1 import TaskQueueType
    from temporalio.api.taskqueue.v1 import TaskQueue
    from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest

    return DescribeTaskQueueRequest(
        namespace=namespace,
        task_queue=TaskQueue(name=task_queue),
        task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
    )


async def get_health(
    temporal_host: str = "temporal:7233",
    external_urls: dict[str, str] | None = None,
) -> dict[str, list[ServiceStatus]]:
    global _cache
    if _cache.is_fresh():
        return {"infra": _cache.infra, "workers": _cache.workers}

    ext = external_urls or {}
    infra, workers = await asyncio.gather(
        _check_infra(temporal_host, ext),
        _check_workers(temporal_host),
    )
    _cache = HealthCache(infra=infra, workers=workers, timestamp=time.monotonic())
    return {"infra": infra, "workers": workers}
