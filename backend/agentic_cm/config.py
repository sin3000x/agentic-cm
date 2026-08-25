from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def load_runtime_environment() -> None:
    """Load repository-local development config without overriding real environment variables."""
    load_dotenv(REPOSITORY_ROOT / ".env", override=False)


def agent_adapter_from_environment() -> str:
    """Return the adapter family shared by every Agent runtime."""
    load_runtime_environment()
    return os.getenv("AGENTIC_CM_ADAPTER", "deterministic")
