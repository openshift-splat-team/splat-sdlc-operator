from __future__ import annotations

from temporalio import activity

from agents.common import llm, prompts, storage
from agents.common.models import JiraEpic, OpenShiftFeaturePlan, RequirementSpec, StoryPlan
from agents.common.settings import RequirementsAgentSettings
from agents.requirements_agent import jira_client


@activity.defn
async def fetch_jira_epic(epic_key: str) -> JiraEpic:
    settings = RequirementsAgentSettings()
    activity.logger.info("Fetching Jira epic %s", epic_key)
    return jira_client.fetch_epic(epic_key, settings)


@activity.defn
async def produce_spec(epic: JiraEpic) -> RequirementSpec:
    settings = RequirementsAgentSettings()
    activity.logger.info("Producing spec for epic %s via LLM", epic.key)

    messages = prompts.render(
        "requirements_agent/produce_spec.md",
        epic_key=epic.key,
        epic_summary=epic.summary,
        epic_description=epic.description,
        stories=epic.stories,
        parent_key=epic.parent_key,
        parent_summary=epic.parent_summary,
        parent_description=epic.parent_description,
    )

    class _SpecPayload(RequirementSpec):
        epic_id: str = epic.key
        artifact_ref: str = ""

    result = await llm.complete_structured(messages, settings, _SpecPayload)
    result.epic_id = epic.key
    return result


@activity.defn
async def store_spec(spec: RequirementSpec, run_id: str) -> str:
    settings = RequirementsAgentSettings()
    key = f"runs/{run_id}/requirement-spec.json"
    activity.logger.info("Storing spec to S3 key %s", key)
    return storage.put_artifact(key, spec, settings)


@activity.defn
async def propose_stories(spec: RequirementSpec, feature_plan: OpenShiftFeaturePlan) -> StoryPlan:
    settings = RequirementsAgentSettings()
    activity.logger.info("Proposing stories for epic %s via LLM", spec.epic_id)

    messages = prompts.render(
        "requirements_agent/propose_stories.md",
        epic_id=spec.epic_id,
        title=spec.title,
        stories=spec.stories,
        acceptance_criteria=spec.acceptance_criteria,
        feature_plan=feature_plan.model_dump(),
    )
    result = await llm.complete_structured(messages, settings, StoryPlan)
    result.epic_id = spec.epic_id
    return result


@activity.defn
async def refine_stories(current_plan: StoryPlan, feedback_comments: list[str]) -> StoryPlan:
    settings = RequirementsAgentSettings()
    activity.logger.info(
        "Refining story plan for epic %s with %d feedback comments",
        current_plan.epic_id,
        len(feedback_comments),
    )

    messages = prompts.render(
        "requirements_agent/refine_stories.md",
        epic_id=current_plan.epic_id,
        current_plan=current_plan.model_dump(),
        feedback_comments=feedback_comments,
    )
    result = await llm.complete_structured(messages, settings, StoryPlan)
    result.epic_id = current_plan.epic_id
    return result
