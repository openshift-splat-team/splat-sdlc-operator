# Adding a New Workflow Task Type

This guide explains how to add a new task type that can be triggered through the SDLC orchestrator. A task type is a top-level workflow operation (e.g., `requirements`, `review`, `full_sdlc`) that the orchestrator dispatches to the appropriate agent.

## 1. Add the Task Type Literal

In `agents/common/models.py`, add the new value to the `WorkflowTrigger.task_type` literal:

```python
class WorkflowTrigger(BaseModel):
    task_type: Literal[
        "requirements", "review", "create_pr", "openshift_feature",
        "full_sdlc", "implement_feature", "enhancement_review",
        "my_new_task",  # <-- add here
    ]
```

## 2. Add an Input Model

In `agents/common/models.py`, define a Pydantic model for the new task's input:

```python
class MyNewTaskInput(BaseModel):
    target_id: str = Field(..., description="Identifier for the target resource")
    description: str
    options: list[str] = []
```

## 3. Add the Field to WorkflowTrigger

Add an optional field on `WorkflowTrigger` to carry the input:

```python
class WorkflowTrigger(BaseModel):
    task_type: Literal[...]
    # ... existing fields ...
    my_new_task: MyNewTaskInput | None = None
    run_id: str = Field(..., description="Unique ID for this workflow run")
```

## 4. Handle the Task Type in the Orchestrator

In `agents/orchestrator/workflows.py`, add an `elif` branch in `SDLCOrchestratorWorkflow.run()`:

```python
elif trigger.task_type == "my_new_task":
    if not trigger.my_new_task:
        raise ValueError("my_new_task required for my_new_task task")

    artifact_ref = await workflow.execute_child_workflow(
        MyNewTaskWorkflow.run,
        args=[trigger.my_new_task, trigger.run_id],
        id=f"{trigger.run_id}-my-new-task",
        task_queue="target-agent",
        execution_timeout=timedelta(minutes=15),
    )
    return WorkflowResult(
        run_id=trigger.run_id,
        task_type="my_new_task",
        status="completed",
        artifact_ref=artifact_ref,
    )
```

Add the workflow import inside the `with workflow.unsafe.imports_passed_through():` block at the top of the file.

## 5. Register in the Trigger Script

In `scripts/trigger.py`, add the new task type to the `TASK_TYPES` tuple:

```python
TASK_TYPES = (
    "requirements", "review", "create_pr", "openshift_feature",
    "full_sdlc", "enhancement_review",
    "my_new_task",  # <-- add here
)
```

## 6. Add CLI Prompting Logic

In `scripts/trigger.py`, add an `elif` block in `main()` to collect user input for the new task:

```python
elif task_type == "my_new_task":
    from agents.common.models import MyNewTaskInput
    target_id = prompt("Target ID")
    description = prompt("Description")
    options_raw = prompt("Options (comma-separated)", optional=True)
    options = [o.strip() for o in options_raw.split(",")] if options_raw else []
    my_new_task = MyNewTaskInput(
        target_id=target_id,
        description=description,
        options=options,
    )
```

Then include `my_new_task=my_new_task` in the `WorkflowTrigger(...)` constructor at the bottom of `main()`. Initialize the variable to `None` at the top of the function alongside the other task-specific variables.

## 7. Implement the Workflow

Create or extend the workflow class in the appropriate agent's `workflows.py`. If this is a new agent, follow the [Adding an Agent](adding-an-agent.md) guide. If adding to an existing agent, add the workflow class and register it in that agent's `worker.py`:

```python
# In agents/<agent>/worker.py, add to the Worker() constructor:
workflows=[ExistingWorkflow, MyNewTaskWorkflow],
```

## Checklist

- [ ] `task_type` literal added to `WorkflowTrigger` in `models.py`
- [ ] Input model defined in `models.py`
- [ ] Optional field added to `WorkflowTrigger`
- [ ] `elif` branch added to `SDLCOrchestratorWorkflow.run()` in `orchestrator/workflows.py`
- [ ] Workflow import added under `workflow.unsafe.imports_passed_through()` in orchestrator
- [ ] Task type added to `TASK_TYPES` in `scripts/trigger.py`
- [ ] CLI prompting logic added to `main()` in `scripts/trigger.py`
- [ ] Workflow class implemented and registered in the target agent's worker
- [ ] Prompt templates added (if the workflow uses LLM calls)
- [ ] Test the new task type: `python -m scripts.trigger my_new_task`
