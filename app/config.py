"""Application settings, read from environment variables / .env (python-dotenv).

Secrets live ONLY in the environment. Nothing here is ever written to the database.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _f(name: str, default: str = "") -> str:
    return os.getenv(name, default).split("#")[0].strip()


@dataclass(frozen=True)
class Settings:
    app_mode: str = "demo"
    database_url: str = "postgresql+psycopg2://sdlc:sdlc@localhost:5460/sdlc_rag"
    llm_provider: str = "mock"
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    azure_endpoint: str = ""
    azure_api_key: str = ""
    azure_deployment: str = ""
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    rag_threshold: float = 0.35
    rag_top_k: int = 10
    rag_keep_top: int = 5
    ado_mode: str = "mock"
    ado_org_url: str = ""
    ado_project: str = ""
    ado_pat: str = ""
    confluence_mode: str = "mock"
    confluence_base_url: str = ""
    confluence_space: str = ""
    confluence_user: str = ""
    confluence_api_token: str = ""
    test_runner: str = "mock"
    test_runner_command: str = "mvn -q test"
    release_poll_minutes: int = 5
    sample_data_dir: Path = field(default_factory=lambda: ROOT / "sample_data")
    workspace_dir: Path = field(default_factory=lambda: ROOT / "workspace")

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            app_mode=_f("APP_MODE", "demo"),
            database_url=_f("DATABASE_URL", cls.database_url),
            llm_provider=_f("LLM_PROVIDER", "mock"),
            groq_api_key=_f("GROQ_API_KEY"),
            groq_model=_f("GROQ_MODEL", "llama-3.1-8b-instant"),
            azure_endpoint=_f("AZURE_OPENAI_ENDPOINT"),
            azure_api_key=_f("AZURE_OPENAI_API_KEY"),
            azure_deployment=_f("AZURE_OPENAI_DEPLOYMENT"),
            embedding_model=_f("EMBEDDING_MODEL", cls.embedding_model),
            rag_threshold=float(_f("RAG_SIMILARITY_THRESHOLD", "0.35")),
            rag_top_k=int(_f("RAG_TOP_K", "10")),
            rag_keep_top=int(_f("RAG_KEEP_TOP", "5")),
            ado_mode=_f("ADO_MODE", "mock"),
            ado_org_url=_f("ADO_ORG_URL"),
            ado_project=_f("ADO_PROJECT"),
            ado_pat=_f("ADO_PAT"),
            confluence_mode=_f("CONFLUENCE_MODE", "mock"),
            confluence_base_url=_f("CONFLUENCE_BASE_URL"),
            confluence_space=_f("CONFLUENCE_SPACE"),
            confluence_user=_f("CONFLUENCE_USER"),
            confluence_api_token=_f("CONFLUENCE_API_TOKEN"),
            test_runner=_f("TEST_RUNNER", "mock"),
            test_runner_command=_f("TEST_RUNNER_COMMAND", "mvn -q test"),
            release_poll_minutes=int(_f("RELEASE_POLL_MINUTES", "5")),
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def reset_settings() -> None:
    """Re-read the environment (used by tests)."""
    global _settings
    _settings = None
