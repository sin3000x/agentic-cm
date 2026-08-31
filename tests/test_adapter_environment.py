import pytest

import agentic_cm.config as config_module
from agentic_cm.config import (
    agent_llm_config_from_environment,
    path_execution_mode_from_environment,
    path_max_concurrency_from_environment,
)
from agentic_cm.orchestrator import (
    DeterministicPlannerAdapter,
    OpenAICompatiblePlannerAdapter,
    planner_from_environment,
)
from agentic_cm.path_agent import (
    DeepAgentPathAdapter,
    path_agent_from_environment,
)
from agentic_cm.synthesis_agent import (
    DeterministicSynthesisAgentAdapter,
    OpenAICompatibleSynthesisAgentAdapter,
    synthesis_agent_from_environment,
)


def test_single_adapter_setting_selects_all_agent_runtimes(monkeypatch) -> None:
    monkeypatch.setenv("AGENTIC_CM_ADAPTER", "openai-compatible")
    monkeypatch.setenv("AGENTIC_CM_LLM_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("AGENTIC_CM_LLM_MODEL", "test-model")

    assert isinstance(planner_from_environment(), OpenAICompatiblePlannerAdapter)
    assert isinstance(path_agent_from_environment(), DeepAgentPathAdapter)
    assert isinstance(
        synthesis_agent_from_environment(), OpenAICompatibleSynthesisAgentAdapter
    )


def test_agent_specific_models_and_thinking_settings_are_independent(monkeypatch) -> None:
    monkeypatch.setenv("AGENTIC_CM_ADAPTER", "openai-compatible")
    monkeypatch.setenv("AGENTIC_CM_LLM_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("AGENTIC_CM_LLM_MODEL", "fallback-model")
    monkeypatch.setenv("AGENTIC_CM_ORCHESTRATOR_LLM_MODEL", "planner-model")
    monkeypatch.setenv("AGENTIC_CM_PATH_LLM_MODEL", "path-model")
    monkeypatch.setenv("AGENTIC_CM_SYNTHESIS_LLM_MODEL", "synthesis-model")
    monkeypatch.setenv("AGENTIC_CM_ORCHESTRATOR_THINKING_ENABLED", "true")
    monkeypatch.setenv("AGENTIC_CM_ORCHESTRATOR_REASONING_EFFORT", "max")
    monkeypatch.setenv("AGENTIC_CM_PATH_THINKING_ENABLED", "false")
    monkeypatch.setenv("AGENTIC_CM_SYNTHESIS_THINKING_ENABLED", "true")
    monkeypatch.setenv("AGENTIC_CM_SYNTHESIS_REASONING_EFFORT", "low")

    planner = planner_from_environment()
    path_agent = path_agent_from_environment()
    synthesis_agent = synthesis_agent_from_environment()
    planner_config = agent_llm_config_from_environment("orchestrator")
    path_config = agent_llm_config_from_environment("path")
    synthesis_config = agent_llm_config_from_environment("synthesis")

    assert planner.profile == "openai-compatible/planner-model"
    assert path_agent.profile == "openai-compatible-path/path-model"
    assert synthesis_agent.profile == "openai-compatible-synthesis/synthesis-model"
    assert (planner_config.thinking_enabled, planner_config.reasoning_effort) == (True, "max")
    assert path_config.thinking_enabled is False
    assert (synthesis_config.thinking_enabled, synthesis_config.reasoning_effort) == (True, "low")


def test_llm_timeout_setting_applies_to_every_openai_compatible_agent(monkeypatch) -> None:
    monkeypatch.setenv("AGENTIC_CM_ADAPTER", "openai-compatible")
    monkeypatch.setenv("AGENTIC_CM_LLM_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("AGENTIC_CM_LLM_MODEL", "test-model")
    monkeypatch.setenv("AGENTIC_CM_LLM_TIMEOUT_SECONDS", "12.5")

    adapters = (
        planner_from_environment(),
        path_agent_from_environment(),
        synthesis_agent_from_environment(),
    )

    assert [
        adapters[0]._endpoint.client.sdk.timeout,
        adapters[1]._model.request_timeout,
        adapters[2]._endpoint.client.sdk.timeout,
    ] == [
        12.5,
        12.5,
        12.5,
    ]


def test_llm_timeout_defaults_to_45_seconds(monkeypatch) -> None:
    monkeypatch.setattr(config_module, "load_runtime_environment", lambda: None)
    monkeypatch.setenv("AGENTIC_CM_ADAPTER", "openai-compatible")
    monkeypatch.setenv("AGENTIC_CM_LLM_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("AGENTIC_CM_LLM_MODEL", "test-model")
    monkeypatch.delenv("AGENTIC_CM_LLM_TIMEOUT_SECONDS", raising=False)

    adapters = (
        planner_from_environment(),
        path_agent_from_environment(),
        synthesis_agent_from_environment(),
    )

    assert [
        adapters[0]._endpoint.client.sdk.timeout,
        adapters[1]._model.request_timeout,
        adapters[2]._endpoint.client.sdk.timeout,
    ] == [
        45.0,
        45.0,
        45.0,
    ]


@pytest.mark.parametrize(
    "factory",
    [
        planner_from_environment,
        path_agent_from_environment,
        synthesis_agent_from_environment,
    ],
)
@pytest.mark.parametrize("value", ["0", "-1", "not-a-number", "nan", "inf"])
def test_invalid_llm_timeout_fails_closed(monkeypatch, factory, value: str) -> None:
    monkeypatch.setenv("AGENTIC_CM_ADAPTER", "openai-compatible")
    monkeypatch.setenv("AGENTIC_CM_LLM_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("AGENTIC_CM_LLM_MODEL", "test-model")
    monkeypatch.setenv("AGENTIC_CM_LLM_TIMEOUT_SECONDS", value)

    with pytest.raises(ValueError):
        factory()


def test_thinking_defaults_to_disabled_and_model_uses_global_fallback(monkeypatch) -> None:
    monkeypatch.setenv("AGENTIC_CM_ADAPTER", "openai-compatible")
    monkeypatch.setenv("AGENTIC_CM_LLM_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("AGENTIC_CM_LLM_MODEL", "fallback-model")
    for agent in ("ORCHESTRATOR", "PATH", "SYNTHESIS"):
        monkeypatch.delenv(f"AGENTIC_CM_{agent}_LLM_MODEL", raising=False)
        monkeypatch.delenv(f"AGENTIC_CM_{agent}_THINKING_ENABLED", raising=False)
    monkeypatch.delenv("AGENTIC_CM_LLM_THINKING_ENABLED", raising=False)

    adapters = (
        planner_from_environment(),
        path_agent_from_environment(),
        synthesis_agent_from_environment(),
    )

    assert all(
        agent_llm_config_from_environment(agent_type).thinking_enabled is False
        for agent_type in ("orchestrator", "path", "synthesis")
    )
    assert [adapter.profile for adapter in adapters] == [
        "openai-compatible/fallback-model",
        "openai-compatible-path/fallback-model",
        "openai-compatible-synthesis/fallback-model",
    ]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AGENTIC_CM_PATH_THINKING_ENABLED", "sometimes"),
        ("AGENTIC_CM_PATH_REASONING_EFFORT", "extreme"),
    ],
)
def test_invalid_agent_thinking_configuration_fails_closed(
    monkeypatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError):
        agent_llm_config_from_environment("path")


def test_path_execution_mode_and_concurrency_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv("AGENTIC_CM_PATH_EXECUTION_MODE", raising=False)
    monkeypatch.delenv("AGENTIC_CM_PATH_MAX_CONCURRENCY", raising=False)
    assert path_execution_mode_from_environment() == "parallel"
    assert path_max_concurrency_from_environment() == 4
    monkeypatch.setenv("AGENTIC_CM_PATH_EXECUTION_MODE", "serial")
    assert path_execution_mode_from_environment() == "serial"
    with pytest.raises(ValueError):
        monkeypatch.setenv("AGENTIC_CM_PATH_EXECUTION_MODE", "unsupported")
        path_execution_mode_from_environment()
    with pytest.raises(ValueError):
        monkeypatch.setenv("AGENTIC_CM_PATH_MAX_CONCURRENCY", "0")
        path_max_concurrency_from_environment()


def test_single_adapter_setting_selects_deterministic_for_all_agent_runtimes(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENTIC_CM_ADAPTER", "deterministic")

    assert isinstance(planner_from_environment(), DeterministicPlannerAdapter)
    assert isinstance(path_agent_from_environment(), DeepAgentPathAdapter)
    assert isinstance(
        synthesis_agent_from_environment(), DeterministicSynthesisAgentAdapter
    )


@pytest.mark.parametrize("value", ["-1", "not-a-number", "nan", "inf"])
def test_invalid_deterministic_delay_fails_closed(
    monkeypatch, value: str
) -> None:
    monkeypatch.setenv("AGENTIC_CM_ADAPTER", "deterministic")
    monkeypatch.setenv("AGENTIC_CM_DETERMINISTIC_DELAY_SECONDS", value)

    with pytest.raises(ValueError):
        planner_from_environment()
