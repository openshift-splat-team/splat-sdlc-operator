FROM docker.io/python:3.11-slim

RUN pip install uv==0.4.18 --no-cache-dir

WORKDIR /app

# Install all deps at build time for layer caching.
# agents/ is volume-mounted at runtime; PYTHONPATH makes it importable directly.
COPY pyproject.toml uv.lock ./
RUN uv sync --no-install-project \
    --extra requirements-agent \
    --extra github-agent \
    --extra jira-agent \
    --extra enhancement-agent \
    --extra openshift-agent \
    --extra vertex-ai \
    --extra dashboard

# Fallback source copy (overridden by volume mount in compose)
COPY agents ./agents
COPY prompts ./prompts
COPY scripts ./scripts

ENV PYTHONPATH=/app
ENV PATH="/app/.venv/bin:$PATH"
