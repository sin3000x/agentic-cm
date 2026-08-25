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


def path_execution_mode_from_environment() -> str:
    """Return the platform-owned scheduling mode for selected Path Agents."""
    load_runtime_environment()
    mode = os.getenv("AGENTIC_CM_PATH_EXECUTION_MODE", "parallel").strip().lower()
    if mode not in {"parallel", "serial"}:
        raise ValueError(
            "AGENTIC_CM_PATH_EXECUTION_MODE must be 'parallel' or 'serial'"
        )
    return mode


def path_max_concurrency_from_environment() -> int:
    """Return the maximum number of Path Agents allowed to run concurrently."""
    load_runtime_environment()
    raw_value = os.getenv("AGENTIC_CM_PATH_MAX_CONCURRENCY", "4").strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError("AGENTIC_CM_PATH_MAX_CONCURRENCY must be a positive integer") from exc
    if value < 1:
        raise ValueError("AGENTIC_CM_PATH_MAX_CONCURRENCY must be a positive integer")
    return value
