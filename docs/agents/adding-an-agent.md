# Adding a New Agent

This guide walks through adding a new Temporal worker agent to the project. Each agent is a self-contained Python package that registers its workflows and activities with a dedicated Temporal task queue.

## 1. Create the Agent Directory

```
agents/<name>/
    __init__.py
    worker.py
    workflows.py
    activities.py
```

## 2. Add a Settings Class

In `agents/common/settings.py`, add a settings class that extends `BaseAgentSettings` (or `JiraBaseSettings` if the agent needs Jira credentials). Set `temporal_task_queue` to a unique queue name.

```python
class MyAgentSettings(BaseAgentSettings):
    temporal_task_queue: str = "my-agent"

    # Add agent-specific fields:
    my_api_url: str = Field(..., description="URL for external service")
    my_api_token: str = Field(..., description="Auth token")
```

All settings are loaded from environment variables or `.env` file. The `BaseAgentSettings` base class already provides `temporal_host`, `temporal_namespace`, `litellm_model`, `llm_api_key`, `llm_api_base`, and S3 storage fields.

## 3. Create the Worker Entry Point

`agents/<name>/worker.py` connects to Temporal and starts the worker process:

```python
"""My agent Temporal worker entrypoint."""
from __future__ import annotations

import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from agents.common import llm_config
from agents.common.memory_activities import (
    extract_observations, recall_agent_memories, save_memory_entry,
)
from agents.common.settings import MyAgentSettings
from agents.<name>.activities import my_activity_1, my_activity_2
from agents.<name>.workflows import MyWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = MyAgentSettings()
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
        workflows=[MyWorkflow],
        activities=[
            my_activity_1, my_activity_2,
            save_memory_entry, recall_agent_memories, extract_observations,
        ],
    ):
        logger.info("My agent worker running")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
```

Every worker should register the three shared memory activities (`save_memory_entry`, `recall_agent_memories`, `extract_observations`) in addition to its own.

## 4. Define Workflows

`agents/<name>/workflows.py` contains `@workflow.defn` classes. Use `workflow.unsafe.imports_passed_through()` for model imports to satisfy Temporal's sandbox:

```python
from __future__ import annotations
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from agents.common.models import MyInput, MyOutput
    from agents.<name>.activities import my_activity_1, my_activity_2

@workflow.defn
class MyWorkflow:
    @workflow.run
    async def run(self, input: MyInput) -> MyOutput:
        result = await workflow.execute_activity(
            my_activity_1,
            input,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=5),
                backoff_coefficient=2.0,
                maximum_attempts=5,
                non_retryable_error_types=["ValueError"],
            ),
        )
        return result
```

## 5. Define Activities

`agents/<name>/activities.py` contains `@activity.defn` functions. Each activity instantiates its own settings and uses the shared `llm` and `prompts` modules:

```python
from temporalio import activity
from agents.common import llm, prompts
from agents.common.settings import MyAgentSettings
from agents.common.models import MyInput, MyOutput


@activity.defn
async def my_activity_1(input: MyInput) -> MyOutput:
    settings = MyAgentSettings()
    activity.logger.info("Processing %s", input.id)
    messages = prompts.render("my_agent/my_prompt.md", data=input.model_dump())
    return await llm.complete_structured(messages, settings, MyOutput)
```

## 6. Add Models

Add input/output Pydantic models to `agents/common/models.py`:

```python
class MyInput(BaseModel):
    id: str
    description: str

class MyOutput(BaseModel):
    result: str
    artifact_ref: str = ""
```

## 7. Add to compose.yaml

Add a service block using the `x-worker` anchor:

```yaml
  my-agent:
    <<: *worker
    command: python -m agents.my_agent.worker
    environment:
      - TEMPORAL_HOST=temporal:7233
      - TEMPORAL_TASK_QUEUE=my-agent
      - S3_ENDPOINT=rustfs:9000
      - LLM_API_BASE=${LLM_API_BASE:-}
      - GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcp-credentials.json
```

The `*worker` anchor provides the build context, `.env` loading, volume mounts for `agents/`, `prompts/`, and `scripts/`, and dependency on Temporal, RustFS, and Ollama services.

## 8. Wire into the Orchestrator

In `agents/orchestrator/workflows.py`, add the child workflow dispatch inside `SDLCOrchestratorWorkflow.run()`:

```python
elif trigger.task_type == "my_task":
    if not trigger.my_input:
        raise ValueError("my_input required for my_task task")

    artifact_ref = await workflow.execute_child_workflow(
        MyWorkflow.run,
        args=[trigger.my_input],
        id=f"{trigger.run_id}-my-task",
        task_queue="my-agent",
        execution_timeout=timedelta(minutes=15),
    )
    return WorkflowResult(
        run_id=trigger.run_id,
        task_type="my_task",
        status="completed",
        artifact_ref=artifact_ref,
    )
```

## 9. Add Prompt Templates

Create prompt templates in `prompts/<name>/`. See the [Prompt Template Guide](../prompts/guide.md) for format details.

## 10. Add Kubernetes Manifests

For production deployment, add manifests under `deploy/manifests/<name>/` following the pattern of existing agents (Deployment, ServiceAccount, ConfigMap for environment).
