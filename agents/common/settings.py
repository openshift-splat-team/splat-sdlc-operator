from pydantic import Field
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

    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "sdlc-artifacts"
    minio_secure: bool = False


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

    github_token: str = Field(..., description="GitHub personal access token")
    staging_github_org: str = Field(default="", description="GitHub org where forks are created")


class EnhancementAgentSettings(BaseAgentSettings):
    temporal_task_queue: str = "enhancement-agent"

    github_token: str = Field(..., description="GitHub PAT for enhancement repo operations")
    staging_github_org: str = Field(..., description="GitHub org where enhancement forks are created")
    enhancement_repo: str = Field(default="openshift-splat-team/enhancements", description="owner/repo for enhancements")


class OpenShiftAgentSettings(BaseAgentSettings):
    temporal_task_queue: str = "openshift-agent"

    github_token: str = Field(..., description="GitHub PAT for reading openshift org repos")
