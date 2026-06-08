# Kubernetes Secrets

These Secrets must be created manually before deploying agent workloads.
**Never commit actual credentials to this repo.**

Run the following commands with your real values substituted:

```bash
# LLM credentials (all agents)
kubectl create secret generic llm-credentials \
  --namespace sdlc \
  --from-literal=LLM_API_KEY=sk-... \
  --from-literal=LITELLM_MODEL=openai/gpt-4o

# GitHub credentials (review-agent only)
kubectl create secret generic github-credentials \
  --namespace sdlc \
  --from-literal=GITHUB_TOKEN=ghp_...

# Jira credentials (requirements-agent only)
kubectl create secret generic jira-credentials \
  --namespace sdlc \
  --from-literal=JIRA_URL=https://yourorg.atlassian.net \
  --from-literal=JIRA_USER=user@example.com \
  --from-literal=JIRA_TOKEN=...

# S3 credentials (all agents — use defaults for local Kind dev)
kubectl create secret generic s3-credentials \
  --namespace sdlc \
  --from-literal=S3_ACCESS_KEY=rustfsadmin \
  --from-literal=S3_SECRET_KEY=rustfsadmin \
  --from-literal=S3_BUCKET=sdlc-artifacts
```

Or use `make secrets-template` to print these commands with placeholder values.

## Production notes

- Use an external secrets manager (AWS Secrets Manager, Vault, Sealed Secrets) instead of
  manually creating Secrets in production clusters.
- Rotate the `GITHUB_TOKEN` and `JIRA_TOKEN` regularly.
- The `LLM_API_KEY` should be scoped to the minimum required model access.
