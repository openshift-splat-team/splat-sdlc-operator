from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class WorkflowTrigger(BaseModel):
    task_type: Literal["requirements", "review", "create_pr", "openshift_feature", "full_sdlc"]
    jira_epic_id: str | None = None
    github_pr_url: str | None = None
    github_create_pr: "CreatePRInput | None" = None
    openshift_feature: "OpenShiftFeatureInput | None" = None
    full_sdlc: "SDLCFeatureInput | None" = None
    run_id: str = Field(..., description="Unique ID for this workflow run; used as artifact key prefix")


# ── Requirements agent models ─────────────────────────────────────────────────

class JiraStory(BaseModel):
    key: str
    summary: str
    description: str | None = None
    story_points: float | None = None
    status: str = "unknown"


class JiraEpic(BaseModel):
    key: str
    summary: str
    description: str | None = None
    stories: list[JiraStory] = []
    parent_key: str | None = None
    parent_summary: str | None = None
    parent_description: str | None = None


class Story(BaseModel):
    title: str
    description: str
    acceptance_criteria: list[str]


class RequirementSpec(BaseModel):
    epic_id: str
    title: str
    stories: list[Story]
    acceptance_criteria: list[str]
    artifact_ref: str = ""


# ── GitHub agent models ───────────────────────────────────────────────────────

class PRFile(BaseModel):
    filename: str
    patch: str | None = None
    status: str  # added, modified, removed


class PRData(BaseModel):
    url: str
    title: str
    body: str | None = None
    base_branch: str
    head_branch: str
    files: list[PRFile] = []
    diff: str = ""


class InlineComment(BaseModel):
    path: str
    line: int
    body: str
    severity: Literal["info", "warning", "error"] = "info"


class ReviewResult(BaseModel):
    pr_url: str
    summary: str
    inline_comments: list[InlineComment] = []
    approved: bool = False
    artifact_ref: str = ""


class CreatePRInput(BaseModel):
    repo: str = Field(..., description="owner/repo slug, e.g. acme/my-service")
    head_branch: str = Field(..., description="Branch containing the changes")
    base_branch: str = Field(default="main", description="Target branch for the PR")
    title: str
    body: str = ""
    draft: bool = False
    jira_issue_key: str | None = None  # if set, prepended to title and linked in body


class CreatedPR(BaseModel):
    url: str
    number: int
    title: str
    head_branch: str
    base_branch: str
    draft: bool
    artifact_ref: str = ""


# ── OpenShift agent models ────────────────────────────────────────────────────

class OpenShiftFeatureInput(BaseModel):
    feature_description: str
    target_ocp_version: str | None = None
    jira_epic_id: str | None = None
    jira_context: dict | None = None


class AffectedRepo(BaseModel):
    name: str
    tier: str
    reason: str
    change_type: Literal["new_types", "vendor_bump", "implementation", "ci_config", "tests"]
    required: bool = True


class RepoIdentificationResult(BaseModel):
    repos: list[AffectedRepo]
    primary_repo: str
    api_change_required: bool
    mco_involved: bool


class PRStep(BaseModel):
    step: int
    repo: str
    tier: str
    description: str
    blocked_by_step: int | None = None
    branch: str = "main"
    risk: Literal["low", "medium", "high"] = "low"
    ci_requirements: list[str] = []


class CIJob(BaseModel):
    repo: str
    job_name: str
    job_type: Literal["presubmit", "postsubmit", "periodic"]
    description: str
    must_pass_before_merge: bool = True


class ReleaseConfigChange(BaseModel):
    file: str
    description: str


class CIRequirements(BaseModel):
    required_jobs: list[CIJob] = []
    release_config_changes: list[ReleaseConfigChange] = []
    upgrade_test_required: bool = False
    reboot_test_required: bool = False
    notes: list[str] = []


class OpenShiftFeaturePlan(BaseModel):
    summary: str
    affected_tiers: list[str]
    pr_sequence: list[PRStep]
    estimated_timeline: str
    risks: list[str] = []
    notes: list[str] = []
    ci_requirements: CIRequirements = CIRequirements()
    artifact_ref: str = ""


# ── Jira write models ─────────────────────────────────────────────────────────

class JiraStoryDraft(BaseModel):
    title: str
    description: str
    acceptance_criteria: list[str] = []
    story_points: int | None = None
    epic_key: str


class JiraStoryCreated(BaseModel):
    key: str
    summary: str
    url: str
    epic_key: str


class JiraStoryUpdate(BaseModel):
    key: str
    status: str | None = None
    story_points: int | None = None
    depends_on: list[str] = []


class JiraCommentResult(BaseModel):
    comment_id: str
    body: str
    author: str


class JiraEpicUpdate(BaseModel):
    key: str
    summary: str
    description: str | None = None


# ── Enhancement / design doc models ──────────────────────────────────────────

class EnhancementDoc(BaseModel):
    title: str
    summary: str
    motivation: str
    goals: list[str] = []
    non_goals: list[str] = []
    proposal: str
    implementation_details: str
    risks: list[str] = []
    graduation_criteria: str = ""
    drawbacks: list[str] = []
    alternatives: list[str] = []
    artifact_ref: str = ""


class EnhancementPRInput(BaseModel):
    repo: str = Field(..., description="owner/repo slug for the enhancements repo")
    enhancement_doc: "EnhancementDoc | None" = None
    base_branch: str = "main"
    jira_epic_key: str
    jira_story_key: str | None = None


# ── Story planning models ─────────────────────────────────────────────────────

class SizedStory(BaseModel):
    title: str
    description: str
    acceptance_criteria: list[str] = []
    story_points: int = Field(..., description="Fibonacci: 1, 2, 3, 5, 8, 13")
    priority: int = Field(..., description="Relative priority order, 1 = highest")
    depends_on: list[str] = Field(default=[], description="Titles of stories this one depends on")


class StoryPlan(BaseModel):
    epic_id: str
    stories: list[SizedStory]
    sizing_rationale: str = ""
    artifact_ref: str = ""


# ── Staging / repo management models ─────────────────────────────────────────

class StagingRepo(BaseModel):
    source_org: str
    source_repo: str
    staging_org: str
    staging_repo: str
    fork_url: str = ""
    feature_branch: str = ""
    pr_url: str = ""
    pr_number: int = 0
    labels: list[str] = []


class StagingPlan(BaseModel):
    feature_id: str
    repos: list[StagingRepo]
    artifact_ref: str = ""


class PRMonitorEvent(BaseModel):
    repo_slug: str
    pr_number: int
    pr_url: str
    event_type: Literal["label_dropped", "comment", "closed"]
    new_comments: list[str] = []
    labels: list[str] = []


# ── Full SDLC trigger model ───────────────────────────────────────────────────

class SDLCFeatureInput(BaseModel):
    jira_epic_id: str | None = Field(default=None, description="Existing epic key; creates one if absent")
    feature_description: str
    target_ocp_version: str | None = None
    staging_github_org: str = Field(..., description="GitHub org where forks are created")
    enhancement_repo: str = "openshift-splat-team/enhancements"


# ── Orchestrator models ───────────────────────────────────────────────────────

class WorkflowResult(BaseModel):
    run_id: str
    task_type: str
    status: Literal["completed", "failed", "skipped"]
    artifact_ref: str = ""
    error: str | None = None
