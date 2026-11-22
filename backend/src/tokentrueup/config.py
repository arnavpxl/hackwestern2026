from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env",), extra="ignore")

    database_url: str = "postgresql://postgres:tokentrueup@localhost:5433/tokentrueup"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    backfill_rows: int = 20_000_000
    backfill_days: int = 95
    cookie_secure: bool = False  # set TTU_COOKIE_SECURE=true when served over HTTPS
    ttu_encryption_key: str = ""  # TTU_ENCRYPTION_KEY: master key for stored provider keys (see vault.py)
    web_origins: str ="http://localhost:3000,http://127.0.0.1:3000"  # comma-separated, for CORS with cookies
    ttu_smtp_host: str = ""
    ttu_smtp_port: int = 587
    ttu_smtp_username: str = ""
    ttu_smtp_password: str = ""
    ttu_smtp_from: str = ""
    ttu_smtp_message_stream: str = ""
    ttu_smtp_starttls: bool = True
    ttu_smtp_ssl: bool = False
    ttu_app_url: str = "http://localhost:3000"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def email_enabled(self) -> bool:
        return bool(self.ttu_smtp_host and self.ttu_smtp_from)


settings = Settings()
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"
