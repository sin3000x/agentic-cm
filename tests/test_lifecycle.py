import asyncio

import pytest

from agentic_cm.domain import (
    CaseStatus,
    CommitmentDecision,
    NodeStatus,
    OrchestrationPhase,
    OwnerDecisionAction,
    PathAttemptState,
)
from agentic_cm.path_agent import DeterministicPathAgentAdapter
from agentic_cm.service import InvalidTransitionError
from conftest import (
    DEMO_CASE_ID,
    OWNER,
    OWNER_ACTOR,
    OWNER_ROLE,
    AllMatchedSkillPathsPlanner,
    approve_and_execute,
    make_service,
    orchestrate,
)


class _ConcurrencyProbe:
    profile = "concurrency-probe"

    def __init__(self) -> None:
        self.delegate = DeterministicPathAgentAdapter()
        self.active = 0
        self.max_active = 0

    async def generate(self, context, trace):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.03)
            return await self.delegate.generate(context, trace)
        finally:
            self.active -= 1


def test_http_golden_path_runs_from_orchestration_to_owner_decision(client) -> None:
    owner = dict(OWNER)
    assert client.post(f"/api/cases/{DEMO_CASE_ID}/orchestrate", json=owner).status_code == 200
    assert client.post(
        f"/api/cases/{DEMO_CASE_ID}/manifest/approve",
        json={"selected_path_ids": ["PATH-01"], **owner},
    ).status_code == 200

    path_result = client.post(
        f"/api/cases/{DEMO_CASE_ID}/paths/execute",
        json={"path_ids": ["PATH-01"], **owner},
    )
    assert path_result.status_code == 200
    revision = path_result.json()["case"]["path_attempts"][0]["solution_revision"]
    assert [option["id"] for option in revision["options"]] == ["A", "B"]

    approval = client.post(
        f"/api/cases/{DEMO_CASE_ID}/paths/PATH-01/commitments/SUPPLY/approve",
        json={"actor": "王淼", "role": "主计划"},
    )
    assert approval.status_code == 200
    assert approval.json()["manifest"] is None
    assert [path["id"] for path in approval.json()["workflow_paths"]] == ["PATH-01"]
    assert client.post(
        f"/api/cases/{DEMO_CASE_ID}/paths/PATH-01/commitments/TECH/decision",
        json={"actor": "林乔", "role": "研发", "decision": "APPROVE"},
    ).status_code == 200
    final_commitment = client.post(
        f"/api/cases/{DEMO_CASE_ID}/paths/PATH-01/commitments/CUSTOMER/decision",
        json={"actor": "赵宁", "role": "供应经理", "decision": "APPROVE"},
    )
    assert final_commitment.status_code == 200
    assert final_commitment.json()["phase"] == "FINAL_REVIEW"

    synthesized = client.post(f"/api/cases/{DEMO_CASE_ID}/synthesize", json=owner)
    assert synthesized.status_code == 200
    assert synthesized.json()["synthesis_report"]["path_assessments"][0]["status"] == "SUCCEEDED"

    decision = client.post(
        f"/api/cases/{DEMO_CASE_ID}/owner-decision",
        json={**owner, "action": "KEEP_OPEN"},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "OPEN"


def test_commitment_approve_revise_and_reject(tmp_path) -> None:
    service = make_service(tmp_path)
    approve_and_execute(service)

    supply = service.get_inbox("主计划")[0]
    assert supply["approval_context"]["revision"] == 1
    assert supply["approval_context"]["role_report"]["role"] == "主计划"
    assert "role_reports" not in supply["approval_context"]

    case = service.approve_commitment(
        DEMO_CASE_ID, "PATH-01", "SUPPLY", actor="王淼", role="主计划"
    )
    supply_node = next(node for node in case.commitment_nodes if node.id == "SUPPLY")
    customer = next(node for node in case.commitment_nodes if node.id == "CUSTOMER")
    assert supply_node.status is NodeStatus.READY
    assert customer.status is NodeStatus.BLOCKED
    assert not service.get_inbox("主计划")

    case = service.decide_commitment(
        DEMO_CASE_ID, "PATH-01", "TECH",
        decision=CommitmentDecision.REVISE, actor="林乔", role="研发",
    )
    assert case.phase is OrchestrationPhase.PATH_EXPLORATION
    assert case.path_attempts[0].state is PathAttemptState.REVISING
    assert service.get_inbox("研发") == []

    asyncio.run(service.execute_path(DEMO_CASE_ID, "PATH-01", actor=OWNER_ACTOR, role=OWNER_ROLE))
    service.approve_commitment(DEMO_CASE_ID, "PATH-01", "TECH", actor="林乔", role="研发")
    case = service.decide_commitment(
        DEMO_CASE_ID, "PATH-01", "CUSTOMER",
        decision=CommitmentDecision.REJECT, actor="赵宁", role="供应经理",
    )
    assert case.path_attempts[0].state is PathAttemptState.REJECTED
    assert case.phase is OrchestrationPhase.FINAL_REVIEW


def test_owner_close_keep_open_and_modify(tmp_path) -> None:
    service = make_service(tmp_path)

    def reach_synthesis():
        approve_and_execute(service)
        for node_id, actor, role in (
            ("SUPPLY", "王淼", "主计划"),
            ("TECH", "林乔", "研发"),
            ("CUSTOMER", "赵宁", "供应经理"),
        ):
            service.approve_commitment(DEMO_CASE_ID, "PATH-01", node_id, actor=actor, role=role)
        asyncio.run(service.synthesize_case(DEMO_CASE_ID, actor=OWNER_ACTOR, role=OWNER_ROLE))

    reach_synthesis()
    kept = service.decide_case(
        DEMO_CASE_ID, action=OwnerDecisionAction.KEEP_OPEN, actor=OWNER_ACTOR, role=OWNER_ROLE
    )
    assert kept.status is CaseStatus.OPEN
    assert kept.phase is OrchestrationPhase.FINAL_REVIEW
    closed = service.decide_case(
        DEMO_CASE_ID, action=OwnerDecisionAction.CLOSE, actor=OWNER_ACTOR, role=OWNER_ROLE
    )
    assert closed.status is CaseStatus.CLOSED

    service.reset_demo("supply-chain-golden-path-v1")
    reach_synthesis()
    modified = service.decide_case(
        DEMO_CASE_ID,
        action=OwnerDecisionAction.MODIFY,
        actor=OWNER_ACTOR,
        role=OWNER_ROLE,
        guidance="下一轮同时探索拆分路径。",
    )
    assert modified.phase is OrchestrationPhase.INTAKE
    assert modified.manifest is None
    assert modified.human_proposal.content == "下一轮同时探索拆分路径。"


def test_illegal_transitions_do_not_write(tmp_path) -> None:
    service = make_service(tmp_path)
    with pytest.raises(InvalidTransitionError):
        service.approve_manifest(DEMO_CASE_ID, ["PATH-01"], actor=OWNER_ACTOR, role=OWNER_ROLE)
    orchestrate(service)
    version = service.get_case(DEMO_CASE_ID).version
    with pytest.raises(InvalidTransitionError):
        service.approve_manifest(DEMO_CASE_ID, [], actor=OWNER_ACTOR, role=OWNER_ROLE)
    assert service.get_case(DEMO_CASE_ID).version == version
    service.approve_manifest(DEMO_CASE_ID, ["PATH-01"], actor=OWNER_ACTOR, role=OWNER_ROLE)
    with pytest.raises(InvalidTransitionError):
        service.approve_manifest(DEMO_CASE_ID, ["PATH-01"], actor=OWNER_ACTOR, role=OWNER_ROLE)


def test_path_batch_limits_parallelism(tmp_path) -> None:
    probe = _ConcurrencyProbe()
    service = make_service(
        tmp_path,
        planner=AllMatchedSkillPathsPlanner(),
        path_agent=probe,
        path_execution_mode="parallel",
        path_max_concurrency=2,
    )
    orchestrate(service)
    approved = service.approve_manifest(DEMO_CASE_ID, actor=OWNER_ACTOR, role=OWNER_ROLE)
    path_ids = [attempt.path_id for attempt in approved.path_attempts]
    case = asyncio.run(service.execute_paths(
        DEMO_CASE_ID, path_ids, actor=OWNER_ACTOR, role=OWNER_ROLE
    ))
    assert probe.max_active == 2
    assert case.phase is OrchestrationPhase.PROFESSIONAL_COMMITMENT
    assert all(attempt.solution_revision for attempt in case.path_attempts)
