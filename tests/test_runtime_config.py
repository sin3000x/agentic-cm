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


def test_adapter_selection_survives_backend_restart(client, monkeypatch):
    from agentic_cm.repository import CaseRepository
    from agentic_cm.service import CaseService

    monkeypatch.setenv("AGENTIC_CM_ADAPTER", "deterministic")
    monkeypatch.setenv("AGENTIC_CM_LLM_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("AGENTIC_CM_LLM_MODEL", "test-model")
    response = client.post("/api/runtime-config", json={"adapter": "openai-compatible"})
    assert response.status_code == 200
    database_path = api.service.repository.database_path
    restored = CaseService(CaseRepository(database_path))
    monkeypatch.setattr(api, "service", restored)
    response = client.get("/api/runtime-config")
    assert response.json()["adapter"] == "openai-compatible"
    assert response.headers["cache-control"] == "no-store"
    assert isinstance(restored.orchestrator.planner, OpenAICompatiblePlannerAdapter)
    assert client.post("/api/runtime-config", json={"adapter": "deterministic"}).status_code == 200
    assert CaseService(CaseRepository(database_path)).adapter == "deterministic"


def mock_model_provider(monkeypatch, handler):
    import httpx
    from agentic_cm import llm

    monkeypatch.setenv("AGENTIC_CM_LLM_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("AGENTIC_CM_LLM_API_KEY", "private-test-key")
    original = llm.build_openai_compatible_client

    def build(*args, **kwargs):
        return original(*args, **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    monkeypatch.setattr(llm, "build_openai_compatible_client", build)


def test_models_use_provider_auth_and_normalize_catalog(client, monkeypatch):
    import httpx

    monkeypatch.setenv("AGENTIC_CM_LLM_API_KEY_HEADER", "X-API-Key")
    monkeypatch.setenv("AGENTIC_CM_LLM_API_KEY_PREFIX", "")

    def handler(request):
        assert str(request.url) == "https://model.example/v1/models"
        assert request.headers["X-API-Key"] == "private-test-key"
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"data": [{"id": "z"}, {"id": "a"}, {"id": "a"}]})

    mock_model_provider(monkeypatch, handler)
    response = client.get("/api/models")
    assert response.status_code == 200
    assert response.json() == {"data": [{"id": "a"}, {"id": "z"}]}
    assert response.headers["cache-control"] == "no-store"
    assert "private-test-key" not in response.text


def test_model_selection_overrides_all_agents_and_survives_restart(client, monkeypatch):
    import httpx
    from agentic_cm.repository import CaseRepository
    from agentic_cm.service import CaseService

    mock_model_provider(monkeypatch, lambda _: httpx.Response(200, json={"data": [{"id": "chosen"}]}))
    monkeypatch.setenv("AGENTIC_CM_ORCHESTRATOR_LLM_MODEL", "planner-default")
    monkeypatch.setenv("AGENTIC_CM_PATH_LLM_MODEL", "path-default")
    monkeypatch.setenv("AGENTIC_CM_SYNTHESIS_LLM_MODEL", "synthesis-default")
    response = client.post("/api/runtime-config", json={"adapter": "openai-compatible", "model": "chosen"})
    assert response.status_code == 200
    assert response.json()["model"] == "chosen"
    restored = CaseService(CaseRepository(api.service.repository.database_path))
    assert restored.model == "chosen"
    assert restored.orchestrator.planner.profile == "openai-compatible/chosen"
    assert restored.path_agent.adapter.profile == "openai-compatible-path/chosen"
    assert restored.synthesis_agent.adapter.profile == "openai-compatible-synthesis/chosen"
    # Switching modes retains the chosen model.
    assert client.post("/api/runtime-config", json={"adapter": "deterministic"}).json()["model"] == "chosen"
    assert client.post("/api/runtime-config", json={"adapter": "openai-compatible"}).json()["model"] == "chosen"


def test_model_selection_rejects_unknown_or_busy_without_changing_runtime(client, monkeypatch):
    import httpx

    mock_model_provider(monkeypatch, lambda _: httpx.Response(200, json={"data": [{"id": "chosen"}]}))
    previous = api.service.orchestrator
    assert client.post("/api/runtime-config", json={"adapter": "openai-compatible", "model": "missing"}).status_code == 400
    case = api.service.list_cases()[0]
    api.service.repository.create_agent_run(
        run_id="active-model-run", case_id=case.id, agent_type="orchestrator",
        adapter_profile="deterministic", initiated_by="test",
    )
    assert client.post("/api/runtime-config", json={"adapter": "openai-compatible", "model": "chosen"}).status_code == 409
    assert api.service.orchestrator is previous
    assert api.service.repository.get_model_selection() is None


def test_provider_failure_does_not_expose_body_or_change_model(client, monkeypatch):
    import httpx

    mock_model_provider(monkeypatch, lambda _: httpx.Response(401, json={"error": "private-test-key"}))
    for response in [
        client.get("/api/models"),
        client.post("/api/runtime-config", json={"adapter": "openai-compatible", "model": "chosen"}),
    ]:
        assert response.status_code == 502
        assert "private-test-key" not in response.text
    assert api.service.repository.get_model_selection() is None
