from __future__ import annotations

import os
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Literal, cast

from dotenv import load_dotenv


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

AgentType = Literal["orchestrator", "path", "synthesis"]
ReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh", "max"]


@dataclass(frozen=True)
class AgentLLMConfig:
    """Agent-specific model and thinking controls with global fallbacks."""

    model: str
    thinking_enabled: bool
    reasoning_effort: ReasoningEffort


def load_runtime_environment() -> None:
    """Load repository-local development config without overriding real environment variables."""
    load_dotenv(REPOSITORY_ROOT / ".env", override=False)


def agent_adapter_from_environment() -> str:
    """Return the adapter family shared by every Agent runtime."""
    load_runtime_environment()
    return os.getenv("AGENTIC_CM_ADAPTER", "deterministic")


def deterministic_delay_seconds_from_environment() -> float:
    """Return the simulated thinking delay used only by deterministic adapters."""
    load_runtime_environment()
    raw_value = os.getenv("AGENTIC_CM_DETERMINISTIC_DELAY_SECONDS", "3").strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(
            "AGENTIC_CM_DETERMINISTIC_DELAY_SECONDS must be a non-negative finite number"
        ) from exc
    if value < 0 or not isfinite(value):
        raise ValueError(
            "AGENTIC_CM_DETERMINISTIC_DELAY_SECONDS must be a non-negative finite number"
        )
    return value


def llm_timeout_seconds_from_environment() -> float:
    """Return the request timeout shared by OpenAI-compatible Agent runtimes."""
    load_runtime_environment()
    raw_value = os.getenv("AGENTIC_CM_LLM_TIMEOUT_SECONDS", "45").strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(
            "AGENTIC_CM_LLM_TIMEOUT_SECONDS must be a positive finite number"
        ) from exc
    if value <= 0 or not isfinite(value):
        raise ValueError(
            "AGENTIC_CM_LLM_TIMEOUT_SECONDS must be a positive finite number"
        )
    return value


def agent_llm_config_from_environment(agent_type: AgentType) -> AgentLLMConfig:
    """Resolve one Agent's model and thinking settings."""
    load_runtime_environment()
    prefix = f"AGENTIC_CM_{agent_type.upper()}"
    model = os.getenv(f"{prefix}_LLM_MODEL", os.getenv("AGENTIC_CM_LLM_MODEL", ""))
    thinking_enabled = _environment_bool(
        f"{prefix}_THINKING_ENABLED",
        fallback_name="AGENTIC_CM_LLM_THINKING_ENABLED",
        default=False,
    )
    raw_effort = os.getenv(
        f"{prefix}_REASONING_EFFORT",
        os.getenv("AGENTIC_CM_LLM_REASONING_EFFORT", "high"),
    ).strip().lower()
    allowed_efforts = {"minimal", "low", "medium", "high", "xhigh", "max"}
    if raw_effort not in allowed_efforts:
        raise ValueError(
            f"{prefix}_REASONING_EFFORT must be one of: "
            f"{', '.join(sorted(allowed_efforts))}"
        )
    return AgentLLMConfig(
        model=model,
        thinking_enabled=thinking_enabled,
        reasoning_effort=cast(ReasoningEffort, raw_effort),
    )


def _environment_bool(
    name: str,
    *,
    fallback_name: str,
    default: bool,
) -> bool:
    raw_value = os.getenv(name, os.getenv(fallback_name))
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


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
