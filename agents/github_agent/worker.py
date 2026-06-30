"""GitHub agent Temporal worker entrypoint."""
from __future__ import annotations

import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from agents.common import llm_config
from agents.common.memory_activities import extract_observations, recall_agent_memories, save_memory_entry
from agents.common.settings import GitHubAgentSettings
from agents.github_agent.activities import (
    apply_file_changes,
    check_is_gitea,
    create_feature_branch,
    create_pr,
    create_staging_pr,
    fetch_files_for_editing,
    fetch_pr,
    fetch_repo_ci_config,
    fetch_repo_context,
    fetch_type_index,
    fork_repository,
    generate_code_for_bundle,
    generate_test_fixes,
    mirror_repository,
    poll_ci_status,
    poll_pr_for_label_drop,
    post_comments,
    post_pr_comment,
    process_pr_comments,
    push_ci_workflow,
    remove_agent_hold,
    reset_agent_hold_label,
    run_repo_tests,
    run_review,
    store_created_pr,
    store_implementation_result,
    store_review,
    store_staging_plan,
    update_pr_description,
)
from agents.github_agent.workflows import (
    CodeGenerationWorkflow,
    CreatePRWorkflow,
    ForkReposWorkflow,
    MirrorReposWorkflow,
    ImplementFeatureWorkflow,
    MonitorPRWorkflow,
    ReviewWorkflow,
    SetupStagingReposWorkflow,
    ValidateCodeWorkflow,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = GitHubAgentSettings()
    if config_path := os.environ.get("LLM_CONFIG_PATH"):
        llm_config.load(config_path)
        logger.info("Loaded LLM config from %s", config_path)
    logger.info(
        "Connecting to Temporal at %s, task queue=%s",
        settings.temporal_host,
        settings.temporal_task_queue,
    )

    client = await Client.connect(
        settings.temporal_host,
        namespace=settings.temporal_namespace,
    )

    async with Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[
            ReviewWorkflow, CreatePRWorkflow, MirrorReposWorkflow, ForkReposWorkflow,
            SetupStagingReposWorkflow, MonitorPRWorkflow,
            ValidateCodeWorkflow, CodeGenerationWorkflow, ImplementFeatureWorkflow,
        ],
        activities=[
            fetch_pr, run_review, post_comments, store_review, create_pr, store_created_pr,
            mirror_repository, fork_repository, create_feature_branch, create_staging_pr,
            poll_pr_for_label_drop, process_pr_comments, apply_file_changes,
            post_pr_comment, reset_agent_hold_label,
            store_staging_plan,
            fetch_files_for_editing, fetch_repo_context, fetch_type_index, generate_code_for_bundle, update_pr_description,
            remove_agent_hold, store_implementation_result,
            fetch_repo_ci_config, run_repo_tests, generate_test_fixes,
            check_is_gitea, push_ci_workflow, poll_ci_status,
            save_memory_entry, recall_agent_memories, extract_observations,
        ],
    ):
        logger.info("GitHub agent worker running")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
