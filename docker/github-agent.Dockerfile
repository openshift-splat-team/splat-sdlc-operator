FROM sdlc/base:latest

RUN uv sync --no-dev --extra review-agent
COPY agents/github_agent ./agents/github_agent

CMD ["uv", "run", "python", "-m", "agents.github_agent.worker"]
