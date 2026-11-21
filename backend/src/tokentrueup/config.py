from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env",), extra="ignore")

    database_url: str = "postgresql://postgres:tokentrueup@localhost:5433/tokentrueup"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    backfill_rows: int = 20_000_000
    backfill_days: int = 95

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


settings = Settings()
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"
