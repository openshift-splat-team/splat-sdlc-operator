#!/usr/bin/env python3
"""Submit a workflow to the SDLC orchestrator for local dev/testing."""
from __future__ import annotations

import asyncio
import sys
import uuid

from temporalio.client import Client

from agents.common.models import WorkflowTrigger
from agents.common.settings import OrchestratorSettings
from agents.orchestrator.workflows import SDLCOrchestratorWorkflow
from agents.requirements_agent.jira_client import parse_issue_key

TASK_TYPES = ("requirements", "review", "create_pr", "openshift_feature", "full_sdlc", "enhancement_review")


def prompt(label: str, default: str | None = None, optional: bool = False) -> str | None:
    suffix = f" [{default}]" if default else (" (optional)" if optional else "")
    value = input(f"{label}{suffix}: ").strip()
    if not value:
        return default
    return value


async def main() -> None:
    settings = OrchestratorSettings()

    print("SDLC Workflow Trigger")
    print("---------------------")
    print(f"Task types: {', '.join(TASK_TYPES)}")
    cli_task = sys.argv[1] if len(sys.argv) > 1 else None
    if cli_task:
        task_type = cli_task.lower()
    else:
        task_type = prompt("Task type", default="full_sdlc").lower()

    if task_type not in TASK_TYPES:
        print(f"Unknown task type: {task_type}", file=sys.stderr)
        sys.exit(1)

    jira_epic_id: str | None = None
    github_pr_url: str | None = None
    github_create_pr = None
    openshift_feature = None
    full_sdlc = None
    enhancement_review = None

    if task_type == "requirements":
        raw = prompt("Jira epic key or URL")
        jira_epic_id = parse_issue_key(raw) if raw else None

    elif task_type == "review":
        github_pr_url = prompt("GitHub PR URL")

    elif task_type == "create_pr":
        from agents.common.models import CreatePRInput
        repo = prompt("Repo (owner/repo)")
        head = prompt("Head branch")
        base = prompt("Base branch", default="main")
        title = prompt("PR title")
        body = prompt("PR body", optional=True) or ""
        jira_key = prompt("Jira issue key", optional=True)
        draft = (prompt("Draft PR? [y/N]") or "n").lower() == "y"
        github_create_pr = CreatePRInput(
            repo=repo, head_branch=head, base_branch=base,
            title=title, body=body, jira_issue_key=jira_key, draft=draft,
        )

    elif task_type == "openshift_feature":
        from agents.common.models import OpenShiftFeatureInput
        description = prompt("Feature description")
        version = prompt("Target OCP version (e.g. 4.17)", optional=True)
        raw_epic = prompt("Jira epic key or URL", optional=True)
        epic = parse_issue_key(raw_epic) if raw_epic else None
        openshift_feature = OpenShiftFeatureInput(
            feature_description=description,
            target_ocp_version=version,
            jira_epic_id=epic,
        )

    elif task_type == "full_sdlc":
        from dotenv import dotenv_values

        from agents.common.models import SDLCFeatureInput
        from agents.common.settings import RequirementsAgentSettings
        from agents.requirements_agent.jira_client import fetch_epic
        env = dotenv_values(".env")
        raw_epic = prompt("Jira epic key or URL (optional — creates one if blank)", optional=True)
        epic_id = parse_issue_key(raw_epic) if raw_epic else None
        description: str | None = None
        if epic_id:
            print(f"Fetching feature description from Jira epic {epic_id}...")
            jira_settings = RequirementsAgentSettings()
            epic = fetch_epic(epic_id, jira_settings)
            description = epic.summary
            if epic.description:
                description = f"{epic.summary}\n\n{epic.description}"
            print(f"Feature description: {description[:120]}{'...' if len(description) > 120 else ''}")
        if not description:
            description = prompt("Feature description")
        jira_version = epic.target_ocp_version if epic_id else None
        if jira_version:
            print(f"Target OCP version from Jira: {jira_version}")
        version = prompt(
            "Target OCP version (e.g. 4.17)",
            default=jira_version or env.get("TARGET_OCP_VERSION"),
            optional=True,
        )
        staging_org = prompt("Staging GitHub org", default=env.get("STAGING_GITHUB_ORG", "rvanderp3"))
        enhancement_repo = prompt(
            "Enhancement repo",
            default=env.get("ENHANCEMENT_REPO", "openshift-splat-team/enhancements"),
        )
        full_sdlc = SDLCFeatureInput(
            jira_epic_id=epic_id,
            feature_description=description,
            target_ocp_version=version,
            staging_github_org=staging_org,
            enhancement_repo=enhancement_repo,
        )

    elif task_type == "enhancement_review":
        from dotenv import dotenv_values

        from agents.common.models import EnhancementReviewInput
        from agents.common.settings import RequirementsAgentSettings
        from agents.requirements_agent.jira_client import fetch_epic
        env = dotenv_values(".env")
        source_run_id = prompt("Source run ID (from a previous full_sdlc run)")
        if not source_run_id:
            print("Source run ID is required.", file=sys.stderr)
            sys.exit(1)
        raw_epic = prompt("Jira epic key or URL")
        if not raw_epic:
            print("Jira epic key is required.", file=sys.stderr)
            sys.exit(1)
        epic_id = parse_issue_key(raw_epic)
        print(f"Fetching feature description from Jira epic {epic_id}...")
        jira_settings = RequirementsAgentSettings()
        epic = fetch_epic(epic_id, jira_settings)
        description = epic.summary
        if epic.description:
            description = f"{epic.summary}\n\n{epic.description}"
        print(f"Feature description: {description[:120]}{'...' if len(description) > 120 else ''}")
        jira_version = epic.target_ocp_version
        if jira_version:
            print(f"Target OCP version from Jira: {jira_version}")
        version = prompt(
            "Target OCP version (e.g. 4.17)",
            default=jira_version or env.get("TARGET_OCP_VERSION"),
            optional=True,
        )
        staging_org = prompt("Staging GitHub org", default=env.get("STAGING_GITHUB_ORG", "rvanderp3"))
        enhancement_repo = prompt(
            "Enhancement repo",
            default=env.get("ENHANCEMENT_REPO", "openshift-splat-team/enhancements"),
        )
        enhancement_review = EnhancementReviewInput(
            source_run_id=source_run_id,
            jira_epic_id=epic_id,
            feature_description=description,
            target_ocp_version=version,
            staging_github_org=staging_org,
            enhancement_repo=enhancement_repo,
        )

    run_id = str(uuid.uuid4())[:8]
    trigger = WorkflowTrigger(
        task_type=task_type,  # type: ignore[arg-type]
        jira_epic_id=jira_epic_id,
        github_pr_url=github_pr_url,
        github_create_pr=github_create_pr,
        openshift_feature=openshift_feature,
        full_sdlc=full_sdlc,
        enhancement_review=enhancement_review,
        run_id=run_id,
    )

    print(f"\nConnecting to Temporal at {settings.temporal_host}...")
    client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)

    handle = await client.start_workflow(
        SDLCOrchestratorWorkflow.run,
        trigger,
        id=f"sdlc-{task_type}-{run_id}",
        task_queue=settings.temporal_task_queue,
    )

    print(f"\nWorkflow started: {handle.id}")
    print(f"Run ID:          {handle.first_execution_run_id}")
    print(f"Temporal UI:     http://localhost:8233/namespaces/default/workflows/{handle.id}")
    print("\nWaiting for result...")

    result = await handle.result()
    print(f"\nResult: {result}")


if __name__ == "__main__":
    asyncio.run(main())
