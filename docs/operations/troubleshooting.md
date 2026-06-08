# Troubleshooting

## Common Errors

### "InvalidAccessKeyId" or S3 authentication errors

**Cause:** S3 credentials in `.env` do not match the RustFS container
configuration.

**Fix:** Ensure `S3_ACCESS_KEY` and `S3_SECRET_KEY` (or their `MINIO_` aliases)
match the RustFS container's `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD`. The
defaults are both `rustfsadmin`.

### "Failed decoding arguments for activity"

**Cause:** Temporal is replaying a workflow that was started before you changed
an activity's return type or argument signature. Temporal serializes
activity inputs/outputs and cannot deserialize payloads from the old schema.

**Fix:** Terminate the old workflow in the Temporal UI and start a new one.
During development, changing activity signatures frequently can cause this.
Avoid changing return types on activities that have in-flight workflows.

### "could not find free subnet" / network conflicts

**Cause:** VPN software (e.g. Tailscale, OpenVPN) occupies the same IP range
that Podman tries to allocate for container networks.

**Fix:** See the [README](../../README.md) for Podman DNS troubleshooting steps.
In short:

```bash
make dev-down
podman network rm agent-sdlc-workflow_sdlc 2>/dev/null
pkill -9 aardvark-dns 2>/dev/null
rm -rf /run/user/$(id -u)/containers/networks/aardvark-dns
make dev
```

### Worker containers stuck in "Created"

**Cause:** A dependency service (Temporal, RustFS, Ollama) is not yet healthy.
Workers have `depends_on` conditions that block startup until dependencies
pass their health checks.

**Fix:** Check which services are healthy:

```bash
podman-compose ps
```

Look for services showing `(health: starting)` or `(unhealthy)`. Common
culprits:

- **Temporal** -- PostgreSQL may still be initializing. Wait 30 seconds.
- **Ollama** -- model download can take minutes on first run. Check with
  `podman-compose logs -f ollama`.
- **RustFS** -- rarely fails; check `podman-compose logs minio`.

### LLM timeout or slow responses

**Cause:** The configured model is too large for available hardware, or Ollama
is still loading the model into memory.

**Fix:**

- Check Ollama status: `podman-compose logs -f ollama`
- Switch to a smaller model in `.env` (e.g. `qwen3:8b` instead of `qwen3:14b`)
- For cloud providers, verify your API key and network connectivity
- Increase `start_to_close_timeout` on the relevant activity if the model is
  inherently slow

### "No project ID could be determined" (google-auth warning)

**Cause:** The `google-auth` library logs this warning when Vertex AI
credentials are present but no project ID is set. It is harmless if you are not
using Vertex AI.

**Fix:** Ignore it, or set `VERTEX_PROJECT` in `.env` to suppress the warning.

## Restarting Workers

### Reload code changes (fast)

```bash
make dev-reload
```

Restarts worker containers without rebuilding. Use this when you change Python
source files (they are bind-mounted into containers).

### Rebuild containers (slow)

```bash
make dev-rebuild
```

Rebuilds the base image and restarts everything. Use this when you change
`pyproject.toml`, `uv.lock`, or `Dockerfile`.

## Resetting a Stuck Workflow

If a workflow is stuck and cannot recover:

1. Open the Temporal UI at http://localhost:8233
2. Find the workflow execution
3. Click **Terminate** and provide a reason
4. Start a new workflow with `make dev-trigger`

Terminating a workflow does not roll back side effects (Jira issues created,
PRs opened, artifacts stored). You may need to clean those up manually.

## Full Stack Reset

To start completely fresh:

```bash
make dev-down
podman volume rm agent-sdlc-workflow_temporal-db-data agent-sdlc-workflow_minio-data 2>/dev/null
make dev
make gitea-setup
make gitea-seed-repos
```

This destroys all Temporal history, stored artifacts, and Gitea data.
