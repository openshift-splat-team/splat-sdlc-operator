from __future__ import annotations

from temporalio import activity

from agents.common import storage
from agents.common.models import (
    JiraCommentResult,
    JiraEpic,
    JiraEpicUpdate,
    JiraStoryCreated,
    SDLCFeatureInput,
    StoryPlan,
)
from agents.common.settings import JiraAgentSettings
from agents.jira_agent import jira_write_client


@activity.defn
async def ensure_jira_epic(feature_input: SDLCFeatureInput) -> JiraEpic:
    settings = JiraAgentSettings()
    if feature_input.jira_epic_id:
        activity.logger.info("Fetching existing epic %s", feature_input.jira_epic_id)
        return jira_write_client.get_epic(feature_input.jira_epic_id, settings)

    activity.logger.info("Creating new epic for feature: %s", feature_input.feature_description[:60])
    update: JiraEpicUpdate = jira_write_client.create_epic(
        summary=feature_input.feature_description[:255],
        description=feature_input.feature_description,
        settings=settings,
    )
    return JiraEpic(key=update.key, summary=update.summary, description=update.description)


@activity.defn
async def create_design_doc_story(epic_key: str, pr_url: str) -> JiraStoryCreated:
    from agents.common.models import JiraStoryDraft

    settings = JiraAgentSettings()
    activity.logger.info("Creating design doc story for epic %s", epic_key)
    draft = JiraStoryDraft(
        title="Design Document Review",
        description=(
            f"Review and approve the OpenShift enhancement design document PR.\n\nPR: {pr_url}"
        ),
        acceptance_criteria=["Enhancement PR is approved and merged"],
        story_points=2,
        epic_key=epic_key,
    )
    return jira_write_client.create_story(draft, settings)


@activity.defn
async def post_story_proposals(epic_key: str, story_plan: StoryPlan) -> JiraCommentResult:
    settings = JiraAgentSettings()
    activity.logger.info("Posting story proposals to epic %s (%d stories)", epic_key, len(story_plan.stories))

    lines = ["*Proposed Stories for Review*\n"]
    for i, story in enumerate(story_plan.stories, 1):
        deps = f" (depends on: {', '.join(story.depends_on)})" if story.depends_on else ""
        lines.append(f"{i}. *{story.title}* [{story.story_points} pts]{deps}")
        lines.append(f"   _{story.description}_")
    lines.append("\nPlease reply with feedback or comment *stories approved* to proceed.")

    return jira_write_client.post_comment(epic_key, "\n".join(lines), settings)


@activity.defn
async def poll_epic_comments(epic_key: str) -> list[JiraCommentResult]:
    settings = JiraAgentSettings()
    return jira_write_client.get_comments(epic_key, settings)


@activity.defn
async def create_approved_stories(epic_key: str, story_plan: StoryPlan) -> list[JiraStoryCreated]:
    from agents.common.models import JiraStoryDraft

    settings = JiraAgentSettings()
    activity.logger.info("Creating %d stories for epic %s", len(story_plan.stories), epic_key)
    created: list[JiraStoryCreated] = []
    for story in story_plan.stories:
        draft = JiraStoryDraft(
            title=story.title,
            description=story.description,
            acceptance_criteria=story.acceptance_criteria,
            story_points=story.story_points,
            epic_key=epic_key,
        )
        created.append(jira_write_client.create_story(draft, settings))
    return created


@activity.defn
async def size_and_prioritize_stories(
    stories: list[JiraStoryCreated],
    story_plan: StoryPlan,
) -> None:
    settings = JiraAgentSettings()
    plan_by_title = {s.title: s for s in story_plan.stories}
    for created in stories:
        sized = plan_by_title.get(created.summary)
        if sized and sized.story_points:
            activity.logger.info("Setting %d pts on %s", sized.story_points, created.key)
            jira_write_client.set_story_points(created.key, sized.story_points, settings)


@activity.defn
async def set_story_dependencies(
    stories: list[JiraStoryCreated],
    story_plan: StoryPlan,
) -> None:
    settings = JiraAgentSettings()
    key_by_title = {c.summary: c.key for c in stories}
    for sized in story_plan.stories:
        from_key = key_by_title.get(sized.title)
        if not from_key:
            continue
        for dep_title in sized.depends_on:
            to_key = key_by_title.get(dep_title)
            if to_key:
                activity.logger.info("Linking %s is blocked by %s", from_key, to_key)
                jira_write_client.set_dependency_link(from_key, to_key, "is blocked by", settings)


@activity.defn
async def close_story_wont_do(story_key: str) -> None:
    settings = JiraAgentSettings()
    activity.logger.info("Closing story %s as Won't Do", story_key)
    jira_write_client.close_story(story_key, "Won't Do", settings)


@activity.defn
async def store_story_plan(story_plan: StoryPlan, run_id: str) -> str:
    settings = JiraAgentSettings()
    key = f"runs/{run_id}/story-plan.json"
    activity.logger.info("Storing story plan to S3 key %s", key)
    return storage.put_artifact(key, story_plan, settings)
