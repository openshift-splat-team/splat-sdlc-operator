FROM sdlc/base:latest

RUN uv sync --no-dev
COPY agents/orchestrator ./agents/orchestrator

CMD ["uv", "run", "python", "-m", "agents.orchestrator.worker"]
