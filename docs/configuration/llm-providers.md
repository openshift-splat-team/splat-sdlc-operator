# LLM Provider Configuration

All LLM calls in the system go through a single abstraction layer in
`agents/common/llm.py`. No agent imports LiteLLM directly.

## How LiteLLM Abstracts Providers

The system uses [LiteLLM](https://docs.litellm.ai/) to normalize API calls
across providers. Model names follow LiteLLM's `provider/model` convention:

| Provider | Model Format | Example |
|---|---|---|
| Ollama (local) | `openai/<model>` | `openai/qwen3:14b` |
| OpenAI | `openai/gpt-4o` | `openai/gpt-4o` |
| Anthropic | `anthropic/claude-sonnet-4-6` | `anthropic/claude-sonnet-4-6` |
| Vertex AI | `vertex_ai/gemini-2.5-pro` | `vertex_ai/gemini-2.5-pro` |

`litellm.drop_params = True` is set globally so unsupported provider-specific
parameters are silently ignored rather than causing errors.

## Global Configuration (Environment Variables)

Set these in `.env` (or as container environment variables):

| Variable | Default | Description |
|---|---|---|
| `LITELLM_MODEL` | `openai/gpt-4o` | Default model for all agents |
| `LLM_API_KEY` | (empty) | API key; not required for Ollama |
| `LLM_API_BASE` | (none) | Override API base URL (e.g. `http://localhost:11434` for Ollama) |
| `VERTEX_PROJECT` | (none) | GCP project ID for Vertex AI |
| `VERTEX_LOCATION` | (none) | Vertex AI region (e.g. `us-central1`) |

## Per-Agent Overrides (llm_config.yaml)

To route specific agents to different models or providers, create a YAML config
and set `LLM_CONFIG_PATH` in your `.env`:

```bash
LLM_CONFIG_PATH=./llm_config.yaml
```

### File Structure

```yaml
default:
  model: openai/gpt-4o
  api_key: sk-...

agents:
  openshift-agent:
    model: anthropic/claude-sonnet-4-6
    api_key: sk-ant-...
  enhancement-agent:
    model: vertex_ai/gemini-2.5-pro
    vertex_project: my-gcp-project
    vertex_location: us-central1
```

### Available Fields

Each block (`default` or agent-specific) supports:

- `model` -- LiteLLM model identifier
- `api_key` -- provider API key
- `api_base` -- base URL override
- `vertex_project` -- GCP project (Vertex AI only)
- `vertex_location` -- GCP region (Vertex AI only)

### Resolution Order

When `llm.complete()` is called, settings resolve in this order:

1. **Agent-specific override** from `llm_config.yaml` `agents.<task-queue>` block
2. **Default override** from `llm_config.yaml` `default` block
3. **Environment variables** (`LITELLM_MODEL`, `LLM_API_KEY`, etc.)
4. **Hardcoded defaults** in `BaseAgentSettings`

The `get_override()` function in `agents/common/llm_config.py` merges agent and
default blocks. Any field omitted in an agent block inherits from `default`.

## Provider-Specific Setup

### Ollama (Default)

Ollama runs as a compose service. No API key needed:

```env
LITELLM_MODEL=openai/qwen3:14b
LLM_API_BASE=http://ollama:11434
```

### OpenAI

```env
LITELLM_MODEL=openai/gpt-4o
LLM_API_KEY=sk-...
```

### Anthropic

```env
LITELLM_MODEL=anthropic/claude-sonnet-4-6
LLM_API_KEY=sk-ant-...
```

### Vertex AI (Google Cloud)

```env
LITELLM_MODEL=vertex_ai/gemini-2.5-pro
VERTEX_PROJECT=my-gcp-project
VERTEX_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS_FILE=./gcp-credentials.json
```

The compose stack mounts the credentials file into containers at
`/secrets/gcp-credentials.json`.

## Structured Output

`complete_structured()` requests JSON output conforming to a Pydantic model's
schema. It works by:

1. Injecting a system message with the JSON schema and instructions to respond
   with valid JSON only
2. Calling `complete()` to get the raw LLM response
3. Stripping `<think>...</think>` blocks from reasoning models (e.g. Qwen3)
4. Extracting JSON from markdown fences if present
5. Parsing the result through `model.model_validate_json()`

This approach works across all providers without requiring native structured
output support.
