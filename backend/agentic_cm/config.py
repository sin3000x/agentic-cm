from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def load_runtime_environment() -> None:
    """Load repository-local development config without overriding real environment variables."""
    load_dotenv(REPOSITORY_ROOT / ".env", override=False)
