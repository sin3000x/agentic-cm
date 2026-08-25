from agentic_cm.orchestrator import (
    DeterministicPlannerAdapter,
    OpenAICompatiblePlannerAdapter,
    planner_from_environment,
)
from agentic_cm.path_agent import (
    DeterministicPathAgentAdapter,
    OpenAICompatiblePathAgentAdapter,
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
    assert isinstance(path_agent_from_environment(), OpenAICompatiblePathAgentAdapter)
    assert isinstance(
        synthesis_agent_from_environment(), OpenAICompatibleSynthesisAgentAdapter
    )


def test_single_adapter_setting_selects_deterministic_for_all_agent_runtimes(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENTIC_CM_ADAPTER", "deterministic")

    assert isinstance(planner_from_environment(), DeterministicPlannerAdapter)
    assert isinstance(path_agent_from_environment(), DeterministicPathAgentAdapter)
    assert isinstance(
        synthesis_agent_from_environment(), DeterministicSynthesisAgentAdapter
    )
