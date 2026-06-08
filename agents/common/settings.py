from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseAgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    temporal_host: str = "temporal-frontend:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = Field(..., description="Set per-agent via TEMPORAL_TASK_QUEUE env var")

    litellm_model: str = "openai/gpt-4o"
    llm_api_key: str = Field(default="", description="API key for the configured LLM provider; not required for Ollama")
    llm_api_base: str | None = Field(default=None, description="Override API base URL (e.g. http://localhost:11434 for Ollama)")
    vertex_project: str | None = Field(default=None, description="GCP project ID for Vertex AI (e.g. my-gcp-project)")
    vertex_location: str | None = Field(default=None, description="Vertex AI region (e.g. us-central1)")

    s3_endpoint: str = Field(default="rustfs:9000", validation_alias=AliasChoices("s3_endpoint", "minio_endpoint"))
    s3_access_key: str = Field(default="rustfsadmin", validation_alias=AliasChoices("s3_access_key", "minio_access_key"))
    s3_secret_key: str = Field(default="rustfsadmin", validation_alias=AliasChoices("s3_secret_key", "minio_secret_key"))
    s3_bucket: str = Field(default="sdlc-artifacts", validation_alias=AliasChoices("s3_bucket", "minio_bucket"))
    s3_secure: bool = Field(default=False, validation_alias=AliasChoices("s3_secure", "minio_secure"))


class OrchestratorSettings(BaseAgentSettings):
    temporal_task_queue: str = "orchestrator"


class JiraBaseSettings(BaseAgentSettings):
    jira_url: str = Field(..., description="e.g. https://yourorg.atlassian.net")
    jira_user: str = Field(..., description="Atlassian account email")
    jira_token: str = Field(..., description="Atlassian API token")


class RequirementsAgentSettings(JiraBaseSettings):
    temporal_task_queue: str = "requirements-agent"


class JiraAgentSettings(JiraBaseSettings):
    temporal_task_queue: str = "jira-agent"


class GitHubAgentSettings(BaseAgentSettings):
    temporal_task_queue: str = "github-agent"

    github_base_url: str = Field(default="https://api.github.com", description="GitHub API base URL; set to http://localhost:3000/api/v1 for local Gitea")
    github_token: str = Field(..., description="GitHub personal access token")
    staging_github_org: str = Field(default="", description="GitHub org where forks are created")


class EnhancementAgentSettings(BaseAgentSettings):
    temporal_task_queue: str = "enhancement-agent"

    github_base_url: str = Field(default="https://api.github.com", description="GitHub API base URL; set to http://localhost:3000/api/v1 for local Gitea")
    github_token: str = Field(..., description="GitHub PAT for enhancement repo operations")
    github_bot_user: str = Field(default="gitea", description="Username the bot posts as; its comments are excluded from reviewer feedback")
    staging_github_org: str = Field(..., description="GitHub org where enhancement forks are created")
    enhancement_repo: str = Field(default="openshift-splat-team/enhancements", description="owner/repo for enhancements")


class OpenShiftAgentSettings(BaseAgentSettings):
    temporal_task_queue: str = "openshift-agent"

    github_base_url: str = Field(default="https://api.github.com", description="GitHub API base URL; set to http://localhost:3000/api/v1 for local Gitea")
    github_token: str = Field(..., description="GitHub PAT for reading openshift org repos")

    mcp_server_url: str = Field(default="", description="SSE URL for the openshift-dep-tree MCP server (e.g. http://dep-tree:8000/sse)")
    mcp_server_command: str = Field(default="python3", description="Interpreter to launch the openshift-dep-tree MCP server subprocess (stdio fallback)")
    mcp_server_script: str = Field(default="", description="Absolute path to openshift-dep-tree mcp_server.py (stdio fallback)")
    mcp_data_dir: str = Field(default="", description="Override MCP_DATA_DIR for data file location; empty uses script's directory")
