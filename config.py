"""
Application configuration for CP-Agent.

All runtime configuration is loaded from environment variables (via a `.env`
file in the project root) using `pydantic-settings`. This gives us:

* Type-validated configuration (fails fast on misconfiguration).
* A single source of truth injected into every agent/service.
* Easy overriding via real environment variables in CI/production.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = directory containing this file.
PROJECT_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Values are read from environment variables / a `.env` file. See
    `.env.example` for the full list of supported variables.
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Codeforces ---
    codeforces_handle: str = Field(
        default="", description="Your Codeforces handle used to poll submissions."
    )
    codeforces_api_base: str = Field(default="https://codeforces.com/api")

    # --- LeetCode ---
    leetcode_username: str = Field(default="")
    leetcode_enabled: bool = Field(default=False)
    leetcode_session: str = Field(
        default="",
        description=(
            "Value of the LEETCODE_SESSION cookie from a logged-in browser session. "
            "Required to auto-fetch submitted code (skips needing a local file). "
            "Keep secret -- never commit this."
        ),
    )

    # --- GitHub ---
    github_token: str = Field(
        default="", description="Personal access token with `repo` scope."
    )
    github_username: str = Field(default="")
    github_repo_name: str = Field(default="")

    # --- OpenAI (documentation generation) ---
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o-mini")

    # --- Local paths ---
    local_solutions_dir: Path = Field(
        default=PROJECT_ROOT / "solutions",
        description="Directory CP-Agent watches for newly saved solution files.",
    )
    repo_path: Path = Field(
        default=PROJECT_ROOT / "repo",
        description="Local path of the git-managed portfolio repository.",
    )
    database_path: Path = Field(default=PROJECT_ROOT / "memory" / "solved.db")
    prompts_dir: Path = Field(default=PROJECT_ROOT / "prompts")
    logs_dir: Path = Field(default=PROJECT_ROOT / "logs")

    # --- Agent behaviour ---
    poll_interval_seconds: int = Field(
        default=60, ge=5, description="How often to poll judges for new AC verdicts."
    )
    max_retries: int = Field(default=3, ge=0)
    retry_backoff_seconds: float = Field(default=2.0, ge=0.1)
    dry_run: bool = Field(
        default=False,
        description="If true, agents log intended actions but never write to git/GitHub.",
    )
    auto_push: bool = Field(default=True)

    @field_validator("local_solutions_dir", "repo_path", "database_path", "prompts_dir", "logs_dir")
    @classmethod
    def _resolve_path(cls, value: Path) -> Path:
        return Path(value).expanduser().resolve()

    def ensure_directories(self) -> None:
        """Create all directories this app depends on, if missing."""
        self.local_solutions_dir.mkdir(parents=True, exist_ok=True)
        self.repo_path.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.repo_path / "Codeforces").mkdir(parents=True, exist_ok=True)
        (self.repo_path / "LeetCode").mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Factory used across the app so settings can be trivially mocked in tests."""
    return Settings()