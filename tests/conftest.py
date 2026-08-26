"""Shared fixtures for the backend suite.

Two conventions worth knowing before adding tests here:

- Services are file-backed SQLite, never `:memory:`. `CaseRepository` opens a new
  connection per call, and an in-memory database does not survive across
  connections. `tmp_path` already gives each test its own directory, so a single
  `test.db` filename is enough for isolation.
- Model calls are stubbed with `httpx.MockTransport`, not by monkeypatching
  adapter internals. Adapters accept an injected `http_client`, so the real
  request-building and response-parsing paths still execute.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from agentic_cm.orchestrator import DeterministicPlannerAdapter
from agentic_cm.path_agent import DeterministicPathAgentAdapter
from agentic_cm.repository import CaseRepository
from agentic_cm.service import CaseService
from agentic_cm.synthesis_agent import DeterministicSynthesisAgentAdapter


DEMO_CASE_ID = "CM-2026-014"
OWNER_ACTOR = "陈澄"
OWNER_ROLE = "订单统筹经理"
OWNER = {"actor": OWNER_ACTOR, "role": OWNER_ROLE}


def make_service(tmp_path: Path) -> CaseService:
    """Build a deterministic-adapter service on a fresh database."""
    service = CaseService(
        CaseRepository(tmp_path / "test.db"),
        planner=DeterministicPlannerAdapter(),
        path_agent=DeterministicPathAgentAdapter(),
        synthesis_agent=DeterministicSynthesisAgentAdapter(),
    )
    service.ensure_demo_data()
    return service


@pytest.fixture
def service(tmp_path: Path) -> CaseService:
    return make_service(tmp_path)


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    """A TestClient bound to a fresh deterministic service."""
    from fastapi.testclient import TestClient

    from agentic_cm import api

    monkeypatch.setattr(api, "service", make_service(tmp_path))
    with TestClient(api.app) as test_client:
        yield test_client


def chat_completion_response(
    content: Any,
    *,
    model: str = "vendor-model-42",
    response_id: str = "response-1",
    created: int = 1,
    finish_reason: str = "stop",
) -> httpx.Response:
    """Wrap `content` in an OpenAI-compatible chat completion envelope."""
    message = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(
        200,
        json={
            "id": response_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": message},
            }],
        },
    )
