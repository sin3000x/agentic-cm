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

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from agentic_cm.orchestrator import DeterministicPlannerAdapter, PlannerOutput, PlannerPath, PlannerSkillChoice
from agentic_cm.path_agent import DeterministicPathAgentAdapter
from agentic_cm.repository import CaseRepository
from agentic_cm.service import CaseService
from agentic_cm.synthesis_agent import DeterministicSynthesisAgentAdapter


DEMO_CASE_ID = "CM-2026-014"
OWNER_ACTOR = "陈澄"
OWNER_ROLE = "订单统筹经理"
OWNER = {"actor": OWNER_ACTOR, "role": OWNER_ROLE}


def make_service(tmp_path: Path, **overrides) -> CaseService:
    """Build a deterministic-adapter service on a fresh database."""
    service = CaseService(
        CaseRepository(tmp_path / "test.db"),
        planner=overrides.get("planner", DeterministicPlannerAdapter()),
        path_agent=overrides.get("path_agent", DeterministicPathAgentAdapter()),
        synthesis_agent=overrides.get("synthesis_agent", DeterministicSynthesisAgentAdapter()),
        **{key: value for key, value in overrides.items() if key not in {"planner", "path_agent", "synthesis_agent"}},
    )
    service.ensure_demo_data()
    return service


def orchestrate(service: CaseService, case_id: str = DEMO_CASE_ID):
    return asyncio.run(service.orchestrate_case(case_id, actor=OWNER_ACTOR, role=OWNER_ROLE))


def approve_and_execute(service: CaseService, path_ids: list[str] | None = None):
    orchestrate(service)
    service.approve_manifest(DEMO_CASE_ID, path_ids or ["PATH-01"], actor=OWNER_ACTOR, role=OWNER_ROLE)
    target_ids = path_ids or ["PATH-01"]
    if len(target_ids) == 1:
        return asyncio.run(service.execute_path(
            DEMO_CASE_ID, target_ids[0], actor=OWNER_ACTOR, role=OWNER_ROLE
        ))
    return asyncio.run(service.execute_paths(
        DEMO_CASE_ID, target_ids, actor=OWNER_ACTOR, role=OWNER_ROLE
    ))


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


def planner_choice_for(definition: str) -> tuple[str, str]:
    return {
        "MaterialSubstitution": ("material-substitution-analysis", "需要完整评估替代方案。"),
        "SupplyExpediting": ("supply-expediting-analysis", "需要分析供应加速选项。"),
        "OrderSplit": ("order-split-analysis", "需要分析订单拆分选项。"),
    }.get(definition, ("review-bundle", "需要分析当前路径。"))


class AllMatchedSkillPathsPlanner:
    async def propose(self, context, candidates, skill_catalog, trace):
        return PlannerOutput(
            paths=tuple(
                PlannerPath(
                    definition=candidate["definition"],
                    rationale=f"{candidate['definition']} 的候选能力与当前 Case 匹配",
                    skills=[
                        PlannerSkillChoice(id=skill_id, reason=reason)
                        for skill_id, reason in [planner_choice_for(candidate["definition"])]
                    ],
                )
                for candidate in candidates
            ),
            planner_profile="test/all-matched-skill-paths",
        )


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
