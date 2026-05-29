FROM sdlc/base:latest

RUN uv sync --no-dev --extra requirements-agent
COPY agents/requirements_agent ./agents/requirements_agent

CMD ["uv", "run", "python", "-m", "agents.requirements_agent.worker"]
