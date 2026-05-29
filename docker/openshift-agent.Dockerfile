FROM sdlc/base:latest

RUN uv sync --no-dev --extra review-agent
COPY agents/openshift_agent ./agents/openshift_agent
COPY prompts/openshift_agent ./prompts/openshift_agent

CMD ["uv", "run", "python", "-m", "agents.openshift_agent.worker"]
