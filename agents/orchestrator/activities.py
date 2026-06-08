"""Orchestrator activities for loading cross-agent artifacts."""
from __future__ import annotations

from temporalio import activity

from agents.common import storage
from agents.common.models import EnhancementDoc, OpenShiftFeaturePlan, StagingPlan
from agents.common.settings import OrchestratorSettings


@activity.defn
async def load_feature_plan(artifact_ref: str) -> OpenShiftFeaturePlan:
    settings = OrchestratorSettings()
    activity.logger.info("Loading feature plan from %s", artifact_ref)
    return storage.get_artifact(artifact_ref, OpenShiftFeaturePlan, settings)


@activity.defn
async def load_staging_plan(artifact_ref: str) -> StagingPlan:
    settings = OrchestratorSettings()
    activity.logger.info("Loading staging plan from %s", artifact_ref)
    return storage.get_artifact(artifact_ref, StagingPlan, settings)


@activity.defn
async def load_enhancement_doc(artifact_ref: str) -> EnhancementDoc:
    settings = OrchestratorSettings()
    activity.logger.info("Loading enhancement doc from %s", artifact_ref)
    return storage.get_artifact(artifact_ref, EnhancementDoc, settings)
