from agentic_cm import api
from agentic_cm.orchestrator import OpenAICompatiblePlannerAdapter


def test_select_adapter_uses_environment_and_does_not_expose_credentials(client, monkeypatch):
    monkeypatch.setenv("AGENTIC_CM_LLM_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("AGENTIC_CM_LLM_MODEL", "test-model")
    monkeypatch.setenv("AGENTIC_CM_LLM_API_KEY", "private-test-key")
    response = client.post("/api/runtime-config", json={"adapter": "openai-compatible"})
    assert response.status_code == 200
    assert response.json()["adapter"] == "openai-compatible"
    assert isinstance(api.service.orchestrator.planner, OpenAICompatiblePlannerAdapter)
    assert "private-test-key" not in response.text
    assert client.get("/api/runtime-config").json()["adapter"] == "openai-compatible"
    response = client.post("/api/runtime-config", json={"adapter": "deterministic"})
    assert response.status_code == 200
    assert response.json()["adapter"] == "deterministic"


def test_invalid_configuration_preserves_runtime(client, monkeypatch):
    previous = api.service.orchestrator
    monkeypatch.setenv("AGENTIC_CM_LLM_BASE_URL", "")
    response = client.post("/api/runtime-config", json={"adapter": "openai-compatible"})
    assert response.status_code in {400, 409}
    assert api.service.orchestrator is previous
    assert client.post("/api/runtime-config", json={"adapter": "unknown"}).status_code == 422


def test_cannot_switch_while_agent_is_running(client):
    case = api.service.list_cases()[0]
    api.service.repository.create_agent_run(
        run_id="active-run", case_id=case.id, agent_type="orchestrator",
        adapter_profile="deterministic", initiated_by="test",
    )
    response = client.post("/api/runtime-config", json={"adapter": "deterministic"})
    assert response.status_code == 409
