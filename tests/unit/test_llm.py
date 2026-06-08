import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from agents.common.llm import complete, complete_structured
from agents.common.settings import BaseAgentSettings


class _Settings(BaseAgentSettings):
    temporal_task_queue: str = "test"
    llm_api_key: str = "test-key"

    class Config:
        env_file = None


def _mock_response(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("TEMPORAL_TASK_QUEUE", "test")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("S3_ACCESS_KEY", "rustfsadmin")
    monkeypatch.setenv("S3_SECRET_KEY", "rustfsadmin")
    return _Settings()


@pytest.mark.asyncio
async def test_complete_returns_content(settings):
    with patch("agents.common.llm.litellm.acompletion", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = _mock_response("hello world")
        result = await complete([{"role": "user", "content": "say hello"}], settings)
    assert result == "hello world"


@pytest.mark.asyncio
async def test_complete_structured_parses_json(settings):
    class MyModel(BaseModel):
        name: str
        value: int

    payload = json.dumps({"name": "test", "value": 42})

    with patch("agents.common.llm.litellm.acompletion", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = _mock_response(payload)
        result = await complete_structured(
            [{"role": "user", "content": "give me a model"}], settings, MyModel
        )
    assert result.name == "test"
    assert result.value == 42


@pytest.mark.asyncio
async def test_complete_structured_strips_markdown_fences(settings):
    class MyModel(BaseModel):
        ok: bool

    payload = "```json\n{\"ok\": true}\n```"

    with patch("agents.common.llm.litellm.acompletion", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = _mock_response(payload)
        result = await complete_structured(
            [{"role": "user", "content": "check"}], settings, MyModel
        )
    assert result.ok is True
