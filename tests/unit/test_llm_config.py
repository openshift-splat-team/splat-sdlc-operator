import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import agents.common.llm_config as llm_config_module
from agents.common.llm import complete
from agents.common.llm_config import LLMOverride, get_override, load
from agents.common.settings import BaseAgentSettings


# ── helpers ──────────────────────────────────────────────────────────────────


def _write_yaml(tmp_path: Path, content: str) -> str:
    p = tmp_path / "llm_config.yaml"
    p.write_text(textwrap.dedent(content))
    return str(p)


def _reset_singleton():
    llm_config_module._default = LLMOverride()
    llm_config_module._overrides = {}


def _mock_response(content: str):
    from unittest.mock import MagicMock
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


class _Settings(BaseAgentSettings):
    temporal_task_queue: str = "test-agent"
    litellm_model: str = "openai/default-model"
    llm_api_key: str = ""

    class Config:
        env_file = None


@pytest.fixture(autouse=True)
def reset_singleton():
    _reset_singleton()
    yield
    _reset_singleton()


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("TEMPORAL_TASK_QUEUE", "test-agent")
    monkeypatch.setenv("S3_ACCESS_KEY", "rustfsadmin")
    monkeypatch.setenv("S3_SECRET_KEY", "rustfsadmin")
    return _Settings()


# ── load() tests ──────────────────────────────────────────────────────────────


def test_load_parses_full_yaml(tmp_path):
    path = _write_yaml(tmp_path, """
        default:
          model: openai/gpt-4o
          api_key: sk-default
          api_base: null

        agents:
          requirements-agent:
            model: anthropic/claude-sonnet-4-6
            api_key: sk-ant-xxx
          jira-agent:
            model: openai/gpt-4o-mini
    """)
    load(path)

    override = get_override("requirements-agent")
    assert override.model == "anthropic/claude-sonnet-4-6"
    assert override.api_key == "sk-ant-xxx"
    assert override.api_base is None


def test_load_default_block(tmp_path):
    path = _write_yaml(tmp_path, """
        default:
          model: openai/gpt-4o
    """)
    load(path)

    # Unknown agent should fall back to default
    override = get_override("unknown-agent")
    assert override.model == "openai/gpt-4o"
    assert override.api_key is None


def test_load_empty_model_string_treated_as_none(tmp_path):
    path = _write_yaml(tmp_path, """
        agents:
          jira-agent:
            model: ""
    """)
    load(path)

    override = get_override("jira-agent")
    assert override.model is None


def test_load_missing_agents_section(tmp_path):
    path = _write_yaml(tmp_path, """
        default:
          model: openai/gpt-4o
    """)
    load(path)
    # No KeyError — absent agents section is handled gracefully
    assert get_override("any-agent").model == "openai/gpt-4o"


# ── get_override() fallback tests ─────────────────────────────────────────────


def test_get_override_no_config_returns_none_fields():
    override = get_override("requirements-agent")
    assert override.model is None
    assert override.api_key is None
    assert override.api_base is None


def test_agent_config_overrides_default(tmp_path):
    path = _write_yaml(tmp_path, """
        default:
          model: openai/gpt-4o
        agents:
          openshift-agent:
            model: openai/o1-preview
    """)
    load(path)

    assert get_override("openshift-agent").model == "openai/o1-preview"
    assert get_override("github-agent").model == "openai/gpt-4o"


def test_agent_inherits_default_api_key(tmp_path):
    path = _write_yaml(tmp_path, """
        default:
          api_key: sk-shared
        agents:
          github-agent:
            model: openai/gpt-4o
    """)
    load(path)

    override = get_override("github-agent")
    assert override.api_key == "sk-shared"
    assert override.model == "openai/gpt-4o"


# ── complete() integration ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_uses_override_model(tmp_path, settings):
    path = _write_yaml(tmp_path, """
        agents:
          test-agent:
            model: anthropic/claude-haiku-4-5
    """)
    load(path)

    with patch("agents.common.llm.litellm.acompletion", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = _mock_response("ok")
        await complete([{"role": "user", "content": "hi"}], settings)

    call_kwargs = mock_llm.call_args
    assert call_kwargs.kwargs["model"] == "anthropic/claude-haiku-4-5"


@pytest.mark.asyncio
async def test_complete_falls_back_to_settings_model_when_no_config(settings):
    # No llm_config loaded — singleton has None fields
    with patch("agents.common.llm.litellm.acompletion", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = _mock_response("ok")
        await complete([{"role": "user", "content": "hi"}], settings)

    call_kwargs = mock_llm.call_args
    assert call_kwargs.kwargs["model"] == "openai/default-model"
