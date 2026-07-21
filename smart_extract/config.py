"""Central configuration, read once from the environment / .env file.

Every other module imports ``settings`` from here. Per CLAUDE.md §12, config
is never hardcoded elsewhere and secrets never live in source.

Usage:
    from smart_extract.config import settings
    print(settings.neo4j_uri)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = two levels up from this file (smart_extract/config.py -> repo/).
REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """All runtime configuration, populated from environment / .env.

    Field names map case-insensitively to the .env keys, e.g. ``NEO4J_URI``
    -> ``neo4j_uri``.
    """

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Neo4j ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "changeme"

    # --- LLM seam (OpenAI-compatible; model-agnostic) ---
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "llama-3.1-8b-instant"

    # --- Embedding seam (SPIKE: semantic retrieval, see docs/design-retrieve.md) ---
    # Embeddings often come from a DIFFERENT provider than chat (e.g. Groq serves
    # chat but not embeddings). These default to the chat seam's URL/key when left
    # blank, so a single OpenAI-compatible endpoint that serves both still works.
    llm_embed_base_url: str = ""
    llm_embed_api_key: str = ""
    llm_embed_model: str = "text-embedding-3-small"

    @property
    def embed_base_url(self) -> str:
        """Embedding endpoint, falling back to the chat seam's base URL."""
        return self.llm_embed_base_url or self.llm_base_url

    @property
    def embed_api_key(self) -> str:
        """Embedding key, falling back to the chat seam's key."""
        return self.llm_embed_api_key or self.llm_api_key

    # --- OCR (image/photo lane) ---
    # Path to the Tesseract engine. Empty => rely on PATH. On Windows the
    # UB-Mannheim installer's default is C:\Program Files\Tesseract-OCR\.
    tesseract_cmd: str = ""

    # --- Data ---
    data_dir: str = "data"

    @property
    def data_path(self) -> Path:
        """Absolute path to the data directory (relative paths resolve to repo root)."""
        p = Path(self.data_dir)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def raw_dir(self) -> Path:
        """Where the frozen arXiv corpus lives."""
        return self.data_path / "raw"

    @property
    def gold_dir(self) -> Path:
        """Where the hand-labelled gold set lives."""
        return self.data_path / "gold"

    @property
    def photo_dir(self) -> Path:
        """Where photographed/scanned copies of the corpus live (Phase 2 eval)."""
        return self.data_path / "photo"

    @property
    def resolved_tesseract_cmd(self) -> str | None:
        """Best path to the Tesseract binary, or None to fall back to PATH.

        Order: explicit ``TESSERACT_CMD`` setting -> common Windows install
        location -> None (let pytesseract use whatever is on PATH).
        """
        if self.tesseract_cmd:
            return self.tesseract_cmd
        default_win = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        if default_win.exists():
            return str(default_win)
        return None


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read .env only once per process)."""
    return Settings()


# Module-level singleton for convenient import.
settings = get_settings()
