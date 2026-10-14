"""Settings. Everything lives under ``var/`` (PLAN 5, storage option D).

The LLM key is read here and stays here: it is never sent to the frontend, and
never appears in an API response.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent
#: The static SvelteKit build the API serves (PLAN 5).
FRONTEND_BUILD = PROJECT_ROOT / "frontend" / "build"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEMO_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    var_dir: Path = Field(default=BACKEND_ROOT / "var")
    #: Where "export data files" writes the readable copy of the collection (PLAN 6, phase 2).
    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    #: Importers kept on this machine and out of git (``importers/local.py``).
    importers_dir: Path = Field(default=BACKEND_ROOT / "importers.local")
    #: A PDF goes to the model this many pages at a time (``importpipe/units.py``).
    pdf_pages_per_call: int = 5

    # LLM provider: OpenAI-compatible, base URL + key + model all configurable.
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr | None = None
    llm_model: str = "gpt-4o-mini"
    llm_timeout: float = 120.0
    #: json_schema | json_object | text — left unset until the probe runs (PLAN 3.6).
    llm_structured_output: str | None = None
    llm_vision: bool | None = None

    #: argon2 hash of the shared password; empty means the gate is open (dev only).
    #: Make one with ``memo hash-password``.
    auth_password_hash: str | None = None
    #: Signs the session cookie. Unset → a random one per process (sessions end on restart).
    secret_key: SecretStr | None = None
    session_days: int = 30
    #: Failed logins allowed per client within ``login_window_seconds``.
    login_attempts: int = 5
    login_window_seconds: int = 600
    #: Set when served over HTTPS (the home server); keeps the cookie off plain HTTP.
    cookie_secure: bool = False

    @property
    def db_path(self) -> Path:
        return self.var_dir / "memo.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def raw_dir(self) -> Path:
        """Uploaded photos and PDFs — big, write-once, cheap to lose."""
        return self.var_dir / "raw"

    @property
    def export_dir(self) -> Path:
        """Written only by the manual export action (PLAN 5), never on a write."""
        return self.data_dir

    def ensure_dirs(self) -> None:
        for path in (self.var_dir, self.raw_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
