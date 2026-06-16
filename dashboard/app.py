"""SDLC Dashboard — service health, endpoint links, and workflow triggering."""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from pydantic_settings import SettingsConfigDict
from temporalio.client import Client

from agents.common.models import (
    CreatePRInput,
    EnhancementReviewInput,
    ImplementFeatureInput,
    OpenShiftFeatureInput,
    SDLCFeatureInput,
    WorkflowTrigger,
)
from agents.common.settings import BaseAgentSettings
from agents.orchestrator.workflows import SDLCOrchestratorWorkflow

from .health import ServiceStatus, get_health
from .templates import render_dashboard, render_settings_page, render_status_page

logger = logging.getLogger(__name__)


class DashboardSettings(BaseAgentSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        case_sensitive=False, extra="ignore",
    )

    temporal_task_queue: str = "orchestrator"

    temporal_ui_external_url: str = "http://localhost:8233"
    rustfs_external_url: str = "http://localhost:9001"
    gitea_external_url: str = "http://localhost:3000"
    jira_external_url: str = "http://localhost:8080"
    dep_tree_external_url: str = "http://localhost:8000"


settings = DashboardSettings()

app = FastAPI(title="SDLC Dashboard", docs_url=None, redoc_url=None)


def _external_urls() -> dict[str, str]:
    return {
        "Temporal UI": settings.temporal_ui_external_url,
        "RustFS (S3)": settings.rustfs_external_url,
        "Gitea": settings.gitea_external_url,
        "Jira Simulator": settings.jira_external_url,
        "Dep-Tree MCP": settings.dep_tree_external_url,
    }


# ── Health endpoints ──────────────────────────────────────────────────────────


def _status_to_dict(s: ServiceStatus) -> dict[str, Any]:
    return {"name": s.name, "healthy": s.healthy, "detail": s.detail, "url": s.url}


@app.get("/api/health")
async def api_health() -> JSONResponse:
    health = await get_health(settings.temporal_host, _external_urls())
    return JSONResponse({
        "infra": [_status_to_dict(s) for s in health["infra"]],
        "workers": [_status_to_dict(s) for s in health["workers"]],
    })


@app.get("/api/health/ready")
async def api_ready() -> JSONResponse:
    return JSONResponse({"status": "ok"})


# ── LLM settings ─────────────────────────────────────────────────────────────

_LLM_CONFIG_PATH = Path(
    os.environ.get("LLM_CONFIG_PATH", "./llm_config.yaml")
)

_LLM_CONFIG_HEADER = """\
# Per-agent LLM model configuration.
#
# Model string format follows LiteLLM conventions:
#   ollama/<model>              local Ollama
#   openai/<model>              OpenAI or any OpenAI-compatible server
#   anthropic/<model>           Anthropic Claude
#   vertex_ai/<model>           Google Vertex AI
"""

_AGENT_FIELDS = ("model", "api_key", "api_base", "vertex_project", "vertex_location")
_MASK = "****"


def _mask_keys(data: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for section_key in ("default", "agents"):
        section = data.get(section_key)
        if section is None:
            continue
        if section_key == "default":
            out["default"] = {
                k: (_MASK if k == "api_key" and v else v)
                for k, v in section.items()
                if k in _AGENT_FIELDS
            }
        else:
            out["agents"] = {}
            for agent, cfg in section.items():
                out["agents"][agent] = {
                    k: (_MASK if k == "api_key" and v else v)
                    for k, v in (cfg or {}).items()
                    if k in _AGENT_FIELDS
                }
    return out


@app.get("/api/settings/llm")
async def api_get_llm_settings() -> JSONResponse:
    import yaml  # noqa: PLC0415
    if not _LLM_CONFIG_PATH.exists():
        return JSONResponse({"default": {}, "agents": {}})
    try:
        data = yaml.safe_load(_LLM_CONFIG_PATH.read_text()) or {}
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to read config: {exc}",
        ) from exc
    return JSONResponse(_mask_keys(data))


@app.put("/api/settings/llm")
async def api_put_llm_settings(request: Any) -> JSONResponse:
    import yaml  # noqa: PLC0415
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Expected JSON object")

    existing: dict[str, Any] = {}
    if _LLM_CONFIG_PATH.exists():
        existing = yaml.safe_load(
            _LLM_CONFIG_PATH.read_text(),
        ) or {}

    new_default = body.get("default", {})
    for k in _AGENT_FIELDS:
        val = new_default.get(k)
        if k == "api_key" and val == _MASK:
            new_default[k] = (existing.get("default") or {}).get(
                "api_key", "",
            )

    new_agents: dict[str, Any] = {}
    for agent, cfg in body.get("agents", {}).items():
        agent_cfg = dict(cfg) if cfg else {}
        if agent_cfg.get("api_key") == _MASK:
            agent_cfg["api_key"] = (
                (existing.get("agents") or {}).get(agent) or {}
            ).get("api_key", "")
        new_agents[agent] = agent_cfg

    output = {"default": new_default, "agents": new_agents}
    try:
        content = _LLM_CONFIG_HEADER + "\n" + yaml.dump(
            output, default_flow_style=False, sort_keys=False,
        )
        _LLM_CONFIG_PATH.write_text(content)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to write config: {exc}",
        ) from exc
    return JSONResponse({"saved": True, "restart_required": True})


# ── Workflow listing ──────────────────────────────────────────────────────────

SDLC_PHASES: list[tuple[str, str, list[str]]] = [
    ("A", "Ensure Epic", ["ensure-epic"]),
    ("B", "Enhancement", ["enhancement", "design-story"]),
    ("C", "Approval Gate", ["wait-enhancement"]),
    ("D", "Mirror & Fork", ["mirror-repos", "fork-repos"]),
    ("E", "Feature Analysis", ["openshift-feature"]),
    ("F", "Story Refinement", ["story-refinement"]),
    ("G", "Create Stories", ["create-stories"]),
    ("H", "Setup Staging", ["setup-staging"]),
    ("I", "Implement", ["implement-feature"]),
    ("J", "Monitor PRs", []),
]

_TASK_TYPE_LABELS: dict[str, str] = {
    "requirements": "Requirements",
    "review": "PR Review",
    "create_pr": "Create PR",
    "openshift_feature": "OpenShift Feature",
    "full_sdlc": "Full SDLC",
    "implement_feature": "Implement Feature",
    "enhancement_review": "Enhancement Review",
}

_wf_cache: dict[str, Any] = {
    "data": None, "children": {}, "ts": 0.0,
}


def _infer_phase(
    run_id: str,
    child_ids: set[str],
) -> tuple[str, str]:
    """Return (phase_letter, phase_label) for a full_sdlc run."""
    if any(cid.startswith(f"{run_id}-monitor-") for cid in child_ids):
        return "J", "Monitor PRs"
    latest_phase = "A"
    latest_label = "Ensure Epic"
    for letter, label, suffixes in SDLC_PHASES:
        if not suffixes:
            continue
        if any(f"{run_id}-{sfx}" in child_ids for sfx in suffixes):
            latest_phase = letter
            latest_label = label
    return latest_phase, latest_label


async def _list_workflows() -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Return (workflow entries, child_id->status map)."""
    try:
        client = await Client.connect(
            settings.temporal_host,
            namespace=settings.temporal_namespace,
        )
    except Exception:
        logger.warning("Cannot connect to Temporal for workflow list")
        return [], {}

    results: list[dict[str, Any]] = []
    child_statuses: dict[str, str] = {}
    try:
        async for wf in client.list_workflows():
            wf_id = wf.id
            wf_status = "UNKNOWN"
            if wf.status is not None:
                wf_status = wf.status.name.replace(
                    "WORKFLOW_EXECUTION_STATUS_", ""
                )

            if not wf_id.startswith("sdlc-"):
                child_statuses[wf_id] = wf_status
                continue

            parts = wf_id.split("-", 2)
            if len(parts) < 3:
                continue
            task_type = parts[1]
            run_id = parts[2]

            start_iso = ""
            if wf.execution_time:
                start_iso = wf.execution_time.isoformat()

            temporal_url = (
                f"{settings.temporal_ui_external_url}/namespaces/"
                f"{settings.temporal_namespace}/workflows/{wf_id}"
            )

            entry: dict[str, Any] = {
                "workflow_id": wf_id,
                "task_type": task_type,
                "task_type_label": _TASK_TYPE_LABELS.get(
                    task_type, task_type
                ),
                "run_id": run_id,
                "status": wf_status,
                "start_time": start_iso,
                "current_phase": None,
                "current_phase_label": None,
                "temporal_ui_url": temporal_url,
            }
            results.append(entry)
    except Exception:
        logger.warning("Failed to list workflows", exc_info=True)
        return [], {}

    child_ids = set(child_statuses.keys())
    for entry in results:
        if entry["task_type"] != "full_sdlc":
            continue
        run_id = entry["run_id"]
        run_children = {
            cid for cid in child_ids
            if cid.startswith(f"{run_id}-")
        }
        if run_children:
            phase, label = _infer_phase(run_id, run_children)
            entry["current_phase"] = phase
            entry["current_phase_label"] = label

    from agents.common.storage import get_json  # noqa: PLC0415

    for entry in results:
        usage = get_json(
            f"runs/{entry['run_id']}/token-usage.json", settings,
        )
        if isinstance(usage, list) and usage:
            entry["total_tokens"] = sum(
                r.get("total_tokens", 0) for r in usage
            )
        else:
            entry["total_tokens"] = 0

        status_data = get_json(
            f"runs/{entry['run_id']}/status.json", settings,
        )
        if isinstance(status_data, dict):
            entry["status_message"] = status_data.get("message")
            entry["status_timestamp"] = status_data.get("timestamp")
        else:
            entry["status_message"] = None
            entry["status_timestamp"] = None

    results.sort(key=lambda e: e["start_time"], reverse=True)
    return results, child_statuses


@app.get("/api/workflows")
async def api_workflows() -> JSONResponse:
    now = time.monotonic()
    if _wf_cache["data"] is not None and now - _wf_cache["ts"] < 10.0:
        return JSONResponse({"workflows": _wf_cache["data"]})
    data, children = await _list_workflows()
    _wf_cache["data"] = data
    _wf_cache["children"] = children
    _wf_cache["ts"] = now
    return JSONResponse({"workflows": data})


# ── Workflow status ───────────────────────────────────────────────────────────


@app.get("/api/workflows/{run_id}/status")
async def api_workflow_status(run_id: str) -> JSONResponse:
    from agents.common.storage import get_json  # noqa: PLC0415
    status_data = get_json(f"runs/{run_id}/status.json", settings)
    if not isinstance(status_data, dict):
        return JSONResponse({"status": None})
    return JSONResponse({"status": status_data})


# ── Workflow PR details ───────────────────────────────────────────────────────


def _infer_pr_status(
    run_id: str, repo_slug: str, children: dict[str, str],
) -> str:
    """Infer a short status word for a staging PR."""
    slug = repo_slug.replace("/", "-")
    monitor_key = f"{run_id}-monitor-{slug}"
    codegen_key = f"{run_id}-codegen-{slug}"

    if monitor_key in children:
        return "Monitoring"

    codegen_status = children.get(codegen_key)
    if codegen_status == "RUNNING":
        validate_prefix = f"{codegen_key}-validate"
        if any(k.startswith(validate_prefix) for k in children):
            return "Testing"
        return "Generating"
    if codegen_status == "COMPLETED":
        return "Complete"
    if codegen_status in ("FAILED", "TIMED_OUT"):
        return "Failed"

    return "Pending"


@app.get("/api/workflows/{run_id}/prs")
async def api_workflow_prs(run_id: str) -> JSONResponse:
    from agents.common.storage import get_json  # noqa: PLC0415

    children: dict[str, str] = _wf_cache.get("children", {})
    prs: list[dict[str, Any]] = []

    created_pr = get_json(f"runs/{run_id}/created-pr.json", settings)
    if created_pr:
        repo = ""
        url = created_pr.get("url", "")
        if url:
            parts = url.rstrip("/").split("/")
            if len(parts) >= 4:
                repo = f"{parts[-4]}/{parts[-3]}"
        prs.append({
            "type": "enhancement",
            "repo": repo,
            "url": url,
            "title": created_pr.get("title", ""),
            "number": created_pr.get("number", 0),
            "status": "",
        })

    staging = get_json(
        f"runs/{run_id}/staging-plan.json", settings,
    )
    if staging:
        for r in staging.get("repos", []):
            pr_url = r.get("pr_url", "")
            if not pr_url:
                continue
            repo_slug = (
                f"{r.get('source_org', '')}"
                f"/{r.get('source_repo', '')}"
            )
            prs.append({
                "type": "staging",
                "repo": repo_slug,
                "url": pr_url,
                "title": "",
                "number": r.get("pr_number", 0),
                "status": _infer_pr_status(
                    run_id, repo_slug, children,
                ),
            })

    return JSONResponse({"prs": prs})


# ── Workflow metadata ─────────────────────────────────────────────────────────

def _f(
    name: str,
    label: str,
    *,
    required: bool = True,
    placeholder: str = "",
    default: str = "",
    multiline: bool = False,
    field_type: str = "",
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "name": name, "label": label, "required": required,
    }
    if placeholder:
        d["placeholder"] = placeholder
    if default:
        d["default"] = default
    if multiline:
        d["multiline"] = True
    if field_type:
        d["type"] = field_type
    return d


_ENH_REPO = "openshift-splat-team/enhancements"

WORKFLOW_TYPES: dict[str, dict[str, Any]] = {
    "requirements": {
        "label": "Requirements",
        "description": "Generate requirements spec from a Jira epic",
        "fields": [
            _f("jira_epic_id", "Jira Epic ID", placeholder="SDLC-1"),
        ],
    },
    "review": {
        "label": "PR Review",
        "description": "Review a GitHub pull request",
        "fields": [
            _f("github_pr_url", "PR URL",
               placeholder="http://gitea:3000/org/repo/pulls/1"),
        ],
    },
    "create_pr": {
        "label": "Create PR",
        "description": "Create a pull request in a repository",
        "fields": [
            _f("repo", "Repository (owner/repo)",
               placeholder="acme/my-service"),
            _f("head_branch", "Head Branch",
               placeholder="feature-branch"),
            _f("base_branch", "Base Branch", required=False,
               placeholder="main", default="main"),
            _f("title", "PR Title",
               placeholder="Add new feature"),
            _f("body", "PR Body", required=False,
               placeholder="Description...", multiline=True),
            _f("draft", "Draft PR", required=False,
               field_type="checkbox"),
            _f("jira_issue_key", "Jira Issue Key",
               required=False, placeholder="SDLC-1"),
        ],
    },
    "openshift_feature": {
        "label": "OpenShift Feature",
        "description": "Analyze feature impact on OpenShift repos",
        "fields": [
            _f("feature_description", "Feature Description",
               placeholder="Describe the feature...", multiline=True),
            _f("target_ocp_version", "Target OCP Version",
               required=False, placeholder="4.17"),
            _f("jira_epic_id", "Jira Epic ID",
               required=False, placeholder="SDLC-1"),
            _f("repos", "Repos (comma-separated)", required=False,
               placeholder="openshift/repo1, openshift/repo2"),
        ],
    },
    "full_sdlc": {
        "label": "Full SDLC",
        "description": "End-to-end feature delivery: epic, enhancement, code, repos",
        "fields": [
            _f("feature_description", "Feature Description",
               placeholder="Describe the feature...", multiline=True),
            _f("jira_epic_id", "Jira Epic ID", required=False,
               placeholder="SDLC-1 (creates one if blank)"),
            _f("target_ocp_version", "Target OCP Version",
               required=False, placeholder="4.17"),
            _f("staging_github_org", "Staging GitHub Org",
               placeholder="rvanderp3"),
            _f("enhancement_repo", "Enhancement Repo",
               required=False, placeholder=_ENH_REPO, default=_ENH_REPO),
        ],
    },
    "implement_feature": {
        "label": "Implement Feature",
        "description": "Generate code for a feature in staging repos",
        "fields": [
            _f("feature_id", "Feature ID",
               placeholder="abc12345"),
            _f("staging_plan_ref", "Staging Plan Ref (S3 key)",
               placeholder="runs/abc12345/staging-plan.json"),
            _f("feature_plan_ref", "Feature Plan Ref (S3 key)",
               placeholder="runs/abc12345/feature-plan.json"),
            _f("feature_description", "Feature Description",
               placeholder="Describe the feature...", multiline=True),
        ],
    },
    "enhancement_review": {
        "label": "Enhancement Review",
        "description": "Review enhancement PRs with human approval gates",
        "fields": [
            _f("source_run_id", "Source Run ID",
               placeholder="abc12345"),
            _f("jira_epic_id", "Jira Epic ID",
               placeholder="SDLC-1"),
            _f("feature_description", "Feature Description",
               placeholder="Describe the feature...", multiline=True),
            _f("target_ocp_version", "Target OCP Version",
               required=False, placeholder="4.17"),
            _f("staging_github_org", "Staging GitHub Org",
               placeholder="rvanderp3"),
            _f("enhancement_repo", "Enhancement Repo",
               required=False, placeholder=_ENH_REPO, default=_ENH_REPO),
        ],
    },
}


@app.get("/api/workflows/types")
async def api_workflow_types() -> JSONResponse:
    return JSONResponse(WORKFLOW_TYPES)


# ── Workflow triggering ───────────────────────────────────────────────────────


class TriggerRequest(BaseModel):
    task_type: str
    inputs: dict[str, Any] = {}


class TriggerResponse(BaseModel):
    workflow_id: str
    run_id: str
    task_type: str
    temporal_ui_url: str


def _build_trigger(task_type: str, inputs: dict[str, Any], run_id: str) -> WorkflowTrigger:
    kwargs: dict[str, Any] = {"task_type": task_type, "run_id": run_id}

    if task_type == "requirements":
        kwargs["jira_epic_id"] = inputs["jira_epic_id"]

    elif task_type == "review":
        kwargs["github_pr_url"] = inputs["github_pr_url"]

    elif task_type == "create_pr":
        kwargs["github_create_pr"] = CreatePRInput(
            repo=inputs["repo"],
            head_branch=inputs["head_branch"],
            base_branch=inputs.get("base_branch", "main"),
            title=inputs["title"],
            body=inputs.get("body", ""),
            draft=inputs.get("draft", False),
            jira_issue_key=inputs.get("jira_issue_key"),
        )

    elif task_type == "openshift_feature":
        repos_raw = inputs.get("repos", "")
        repos = [r.strip() for r in repos_raw.split(",") if r.strip()] if repos_raw else []
        kwargs["openshift_feature"] = OpenShiftFeatureInput(
            feature_description=inputs["feature_description"],
            target_ocp_version=inputs.get("target_ocp_version") or None,
            jira_epic_id=inputs.get("jira_epic_id") or None,
            repos=repos,
        )

    elif task_type == "full_sdlc":
        kwargs["full_sdlc"] = SDLCFeatureInput(
            feature_description=inputs["feature_description"],
            jira_epic_id=inputs.get("jira_epic_id") or None,
            target_ocp_version=inputs.get("target_ocp_version") or None,
            staging_github_org=inputs["staging_github_org"],
            enhancement_repo=inputs.get("enhancement_repo", "openshift-splat-team/enhancements"),
        )

    elif task_type == "implement_feature":
        kwargs["implement_feature"] = ImplementFeatureInput(
            feature_id=inputs["feature_id"],
            staging_plan_ref=inputs["staging_plan_ref"],
            feature_plan_ref=inputs["feature_plan_ref"],
            feature_description=inputs["feature_description"],
        )

    elif task_type == "enhancement_review":
        kwargs["enhancement_review"] = EnhancementReviewInput(
            source_run_id=inputs["source_run_id"],
            jira_epic_id=inputs["jira_epic_id"],
            feature_description=inputs["feature_description"],
            target_ocp_version=inputs.get("target_ocp_version") or None,
            staging_github_org=inputs["staging_github_org"],
            enhancement_repo=inputs.get("enhancement_repo", "openshift-splat-team/enhancements"),
        )

    else:
        raise ValueError(f"Unknown task type: {task_type}")

    return WorkflowTrigger(**kwargs)


@app.post("/api/workflows/trigger")
async def api_trigger(req: TriggerRequest) -> TriggerResponse:
    if req.task_type not in WORKFLOW_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown task type: {req.task_type}")

    run_id = str(uuid.uuid4())[:8]
    try:
        trigger = _build_trigger(req.task_type, req.inputs, run_id)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid inputs: {exc}") from exc

    try:
        client = await Client.connect(
            settings.temporal_host, namespace=settings.temporal_namespace,
        )
        workflow_id = f"sdlc-{req.task_type}-{run_id}"
        await client.start_workflow(
            SDLCOrchestratorWorkflow.run,
            trigger,
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Temporal error: {exc}") from exc

    temporal_url = (
        f"{settings.temporal_ui_external_url}/namespaces/"
        f"{settings.temporal_namespace}/workflows/{workflow_id}"
    )
    return TriggerResponse(
        workflow_id=workflow_id,
        run_id=run_id,
        task_type=req.task_type,
        temporal_ui_url=temporal_url,
    )


# ── Developer endpoints ───────────────────────────────────────────────────────


@app.get("/api/dev/runs/{run_id}/artifacts")
async def api_dev_artifacts(run_id: str) -> JSONResponse:
    from minio import Minio  # noqa: PLC0415

    from agents.common.storage import get_json  # noqa: PLC0415

    client = Minio(
        settings.s3_endpoint,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        secure=settings.s3_secure,
    )
    prefix = f"runs/{run_id}/"
    artifacts: list[dict[str, Any]] = []
    try:
        for obj in client.list_objects(
            settings.s3_bucket, prefix=prefix, recursive=True,
        ):
            short_key = obj.object_name.removeprefix(prefix)
            data = get_json(obj.object_name, settings)
            artifacts.append({
                "key": short_key,
                "full_key": obj.object_name,
                "size": obj.size,
                "data": data,
            })
    except Exception:
        logger.warning(
            "Failed to list artifacts for %s", run_id, exc_info=True,
        )
    return JSONResponse({"artifacts": artifacts})


RERUN_STEPS: dict[str, dict[str, str]] = {
    "generate_code": {
        "label": "Code Generation",
        "task_queue": "github-agent",
        "requires": "staging-plan.json, openshift-feature-plan.json",
    },
    "analyze_feature": {
        "label": "Feature Analysis",
        "task_queue": "openshift-agent",
        "requires": "enhancement-doc.json",
    },
}


@app.post("/api/dev/runs/{run_id}/rerun/{step}")
async def api_dev_rerun(run_id: str, step: str) -> JSONResponse:
    if step not in RERUN_STEPS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown step: {step}. "
            f"Valid: {', '.join(RERUN_STEPS)}",
        )

    from agents.common.storage import get_json  # noqa: PLC0415

    rerun_id = f"{run_id}-rerun-{str(uuid.uuid4())[:4]}"

    if step == "generate_code":
        staging = get_json(
            f"runs/{run_id}/staging-plan.json", settings,
        )
        feature_plan = get_json(
            f"runs/{run_id}/openshift-feature-plan.json", settings,
        )
        enh_doc = get_json(
            f"runs/{run_id}/enhancement-doc.json", settings,
        )
        if not staging or not feature_plan:
            raise HTTPException(
                status_code=422,
                detail="Missing staging-plan or feature-plan artifacts",
            )
        description = ""
        if enh_doc:
            description = enh_doc.get("summary", "")

        from agents.common.models import (  # noqa: PLC0415
            ImplementFeatureInput,
        )

        trigger = WorkflowTrigger(
            task_type="implement_feature",
            run_id=rerun_id,
            implement_feature=ImplementFeatureInput(
                feature_id=rerun_id,
                staging_plan_ref=f"runs/{run_id}/staging-plan.json",
                feature_plan_ref=(
                    f"runs/{run_id}/openshift-feature-plan.json"
                ),
                feature_description=description,
            ),
        )

    elif step == "analyze_feature":
        enh_doc = get_json(
            f"runs/{run_id}/enhancement-doc.json", settings,
        )
        if not enh_doc:
            raise HTTPException(
                status_code=422,
                detail="Missing enhancement-doc artifact",
            )
        trigger = WorkflowTrigger(
            task_type="openshift_feature",
            run_id=rerun_id,
            openshift_feature=OpenShiftFeatureInput(
                feature_description=enh_doc.get("summary", ""),
                repos=enh_doc.get("repos_to_fork", []),
            ),
        )

    else:
        raise HTTPException(status_code=400, detail="Not implemented")

    try:
        client = await Client.connect(
            settings.temporal_host,
            namespace=settings.temporal_namespace,
        )
        workflow_id = f"sdlc-{trigger.task_type}-{rerun_id}"
        await client.start_workflow(
            SDLCOrchestratorWorkflow.run,
            trigger,
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Temporal error: {exc}",
        ) from exc

    temporal_url = (
        f"{settings.temporal_ui_external_url}/namespaces/"
        f"{settings.temporal_namespace}/workflows/{workflow_id}"
    )
    return JSONResponse({
        "workflow_id": workflow_id,
        "rerun_id": rerun_id,
        "step": step,
        "temporal_ui_url": temporal_url,
    })


_PROMPTS_DIR = __import__("pathlib").Path(__file__).parents[1] / "prompts"


@app.put("/api/dev/runs/{run_id}/artifacts/{key:path}")
async def api_dev_save_artifact(
    run_id: str, key: str, request: Any,
) -> JSONResponse:
    from agents.common.storage import put_json  # noqa: PLC0415

    body = await request.json()
    full_key = f"runs/{run_id}/{key}"
    try:
        put_json(full_key, body, settings)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save: {exc}",
        ) from exc
    return JSONResponse({"saved": full_key})


@app.get("/api/dev/prompts")
async def api_dev_prompts() -> JSONResponse:
    templates: list[dict[str, str]] = []
    if not _PROMPTS_DIR.is_dir():
        return JSONResponse({"templates": templates})
    for md_file in sorted(_PROMPTS_DIR.rglob("*.md")):
        rel = str(md_file.relative_to(_PROMPTS_DIR))
        templates.append({
            "path": rel,
            "content": md_file.read_text(encoding="utf-8"),
        })
    return JSONResponse({"templates": templates})


@app.put("/api/dev/prompts/{path:path}")
async def api_dev_save_prompt(
    path: str, request: Any,
) -> JSONResponse:
    body = await request.body()
    target = _PROMPTS_DIR / path
    if not target.resolve().is_relative_to(_PROMPTS_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not target.suffix == ".md":
        raise HTTPException(
            status_code=400, detail="Only .md files allowed",
        )
    try:
        target.write_text(body.decode("utf-8"), encoding="utf-8")
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save: {exc}",
        ) from exc
    return JSONResponse({"saved": path})


@app.get("/api/dev/runs/{run_id}/tokens")
async def api_dev_tokens(run_id: str) -> JSONResponse:
    from agents.common.storage import get_json  # noqa: PLC0415

    data = get_json(f"runs/{run_id}/token-usage.json", settings)
    records: list[dict[str, Any]] = data if isinstance(data, list) else []
    return JSONResponse({"records": records})


# ── UI ────────────────────────────────────────────────────────────────────────


@app.get("/", include_in_schema=False)
async def root() -> HTMLResponse:
    return HTMLResponse(render_dashboard(WORKFLOW_TYPES, _external_urls()))


@app.get("/ui", include_in_schema=False)
async def ui() -> HTMLResponse:
    return HTMLResponse(render_dashboard(WORKFLOW_TYPES, _external_urls()))


@app.get("/status", include_in_schema=False)
async def status_page() -> HTMLResponse:
    return HTMLResponse(render_status_page(_external_urls()))


@app.get("/dev", include_in_schema=False)
async def dev_page() -> HTMLResponse:
    from .templates import render_dev_page  # noqa: PLC0415
    return HTMLResponse(render_dev_page(_external_urls()))


@app.get("/dev/tokens", include_in_schema=False)
async def dev_tokens_page() -> HTMLResponse:
    from .templates import render_tokens_page  # noqa: PLC0415
    return HTMLResponse(render_tokens_page(_external_urls()))


@app.get("/dev/context", include_in_schema=False)
async def dev_context_page() -> HTMLResponse:
    from .templates import render_context_page  # noqa: PLC0415
    return HTMLResponse(render_context_page(_external_urls()))


@app.get("/settings", include_in_schema=False)
async def settings_page() -> HTMLResponse:
    return HTMLResponse(render_settings_page(_external_urls()))
