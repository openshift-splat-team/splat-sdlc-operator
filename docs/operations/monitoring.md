# Monitoring and Observability

## Dashboard

See [Dashboard](dashboard.md) for the full reference on the web UI at
**http://localhost:8501** (workflows, service health, developer tools, token
usage, and settings).

## Temporal UI

The Temporal web interface at **http://localhost:8233** is the primary tool for
observing workflow execution.

### Workflow List

The main page shows all workflow executions with their status, type, start time,
and duration. Filter by workflow type (e.g. `FullSDLCWorkflow`,
`OpenShiftFeatureWorkflow`) or status.

### Execution Detail

Click a workflow to see:

- **Summary** -- workflow type, task queue, input/output payloads, timing
- **Event History** -- every event in order: workflow started, activity
  scheduled, activity completed, child workflow started, signals, timers
- **Pending Activities** -- activities currently in progress or waiting for retry
- **Call Stack** -- current position in the workflow code

### Workflow States

| State | Meaning |
|---|---|
| Running | Workflow is actively executing or waiting (timer, signal, child workflow) |
| Completed | All phases finished successfully |
| Failed | An activity exhausted retries or a workflow raised an error |
| Timed Out | Workflow exceeded its `execution_timeout` |
| Terminated | Manually stopped via the UI or `tctl` |
| Cancelled | Cancelled via signal |

## Worker Logs

Each worker container logs to stdout. View logs with:

```bash
# All workers
make dev-logs

# Single worker
podman-compose logs -f orchestrator
podman-compose logs -f requirements-agent
podman-compose logs -f github-agent
podman-compose logs -f openshift-agent
podman-compose logs -f jira-agent
podman-compose logs -f enhancement-agent
```

Worker logs include:

- Temporal connection status and task queue registration
- Activity start/completion with artifact keys
- LLM call details (model, token counts)
- Error tracebacks for failed activities

## RustFS Console

Browse stored artifacts at **http://localhost:9001** (credentials: `rustfsadmin`
/ `rustfsadmin`). The `sdlc-artifacts` bucket contains:

- `runs/{run_id}/` -- per-run artifacts (requirement specs, feature plans,
  enhancement docs, review results)
- `memory/{agent}/` -- agent memory indices

## Inspecting a Stuck Workflow

1. **Open the workflow** in Temporal UI at http://localhost:8233
2. **Check Pending Activities** -- if an activity is pending, note the task queue
   and check whether the corresponding worker is running
   (`podman-compose ps`)
3. **Review Event History** -- look for the last completed event; the next
   scheduled event is where execution stalled
4. **Check worker logs** -- `podman-compose logs -f <worker>` for errors or
   timeouts
5. **Verify dependencies** -- is the LLM reachable? Is RustFS healthy? Is Gitea
   or the Jira simulator responding?

## Health Checks

All infrastructure services have compose-level health checks:

```bash
# Check service health
podman-compose ps
```

Healthy services show `Up (healthy)`. If a worker is stuck in `Created`, its
dependency service may be unhealthy. See
[Troubleshooting](troubleshooting.md) for common fixes.

The [dashboard](dashboard.md) Service Status page (`http://localhost:8501/status`)
shows the same health information in a web UI, refreshed automatically every 10
seconds.
