from __future__ import annotations

import re

from temporalio import activity

from agents.common import llm, prompts, storage
from agents.common.models import (
    CreatedPR,
    EnhancementDoc,
    EnhancementPRInput,
    JiraEpic,
    OpenShiftFeaturePlan,
)
from agents.common.settings import EnhancementAgentSettings
from agents.enhancement_agent import enhancement_client


def _feature_slug(title: str) -> str:
    """Convert doc title to a filesystem-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:80]


@activity.defn
async def generate_enhancement_doc(
    epic: JiraEpic,
    feature_plan: OpenShiftFeaturePlan,
    target_ocp_version: str | None,
) -> EnhancementDoc:
    settings = EnhancementAgentSettings()
    activity.logger.info("Generating enhancement doc for epic %s", epic.key)

    messages = prompts.render(
        "enhancement_agent/generate_doc.md",
        epic_key=epic.key,
        epic_summary=epic.summary,
        epic_description=epic.description or "",
        feature_plan=feature_plan.model_dump(),
        target_ocp_version=target_ocp_version or "next",
        parent_key=epic.parent_key,
        parent_summary=epic.parent_summary,
        parent_description=epic.parent_description,
    )
    return await llm.complete_structured(messages, settings, EnhancementDoc)


@activity.defn
async def submit_enhancement_pr(
    doc: EnhancementDoc,
    pr_input: EnhancementPRInput,
    feature_branch: str,
) -> CreatedPR:
    settings = EnhancementAgentSettings()
    activity.logger.info("Submitting enhancement PR to %s", pr_input.repo)

    feature_slug = _feature_slug(doc.title)

    fork_slug = enhancement_client.fork_enhancement_repo(
        pr_input.repo, settings.staging_github_org, settings
    )
    enhancement_client.create_enhancement_branch(fork_slug, feature_branch, settings)
    enhancement_client.commit_enhancement_doc(fork_slug, feature_branch, doc, feature_slug, settings)

    return enhancement_client.create_enhancement_pr(
        fork_slug=fork_slug,
        branch=feature_branch,
        base_repo=pr_input.repo,
        base_branch=pr_input.base_branch,
        doc=doc,
        jira_story_key=pr_input.jira_story_key,
        settings=settings,
    )


@activity.defn
async def poll_enhancement_pr_state(repo_slug: str, pr_number: int) -> dict:
    settings = EnhancementAgentSettings()
    activity.logger.info("Polling PR state: %s#%d", repo_slug, pr_number)
    return enhancement_client.get_pr_state(repo_slug, pr_number, settings)


@activity.defn
async def store_enhancement_doc(doc: EnhancementDoc, run_id: str) -> str:
    settings = EnhancementAgentSettings()
    key = f"runs/{run_id}/enhancement-doc.json"
    activity.logger.info("Storing enhancement doc to MinIO key %s", key)
    return storage.put_artifact(key, doc, settings)
