import asyncio

import pytest

from agentic_cm.domain import (
    Case,
    CaseStatus,
    CommitmentDecision,
    InformationQuestion,
    NodeStatus,
    OrchestrationPhase,
    OwnerDecisionAction,
    PathAgentResult,
    PathAttemptState,
    RoleReport,
)
from agentic_cm.service import InvalidTransitionError
from conftest import (
    DEMO_CASE_ID,
    OWNER,
    OWNER_ACTOR,
    OWNER_ROLE,
    AllMatchedSkillPathsPlanner,
    approve_and_execute,
    deterministic_path_adapter,
    make_service,
    orchestrate,
)


class _ConcurrencyProbe:
    profile = "concurrency-probe"

    def __init__(self) -> None:
        self.delegate = deterministic_path_adapter()
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
    assert revision["recommendation"]
    assert {item["role"] for item in revision["role_reports"]} == {"主计划", "研发", "供应经理"}

    approval = client.post(
        f"/api/cases/{DEMO_CASE_ID}/paths/PATH-01/commitments/SUPPLY/approve",
        json={"actor": "王淼", "role": "主计划", "expected_revision": 1},
    )
    assert approval.status_code == 200
    assert approval.json()["manifest"] is None
    assert [path["id"] for path in approval.json()["workflow_paths"]] == ["PATH-01"]
    assert client.post(
        f"/api/cases/{DEMO_CASE_ID}/paths/PATH-01/commitments/TECH/decision",
        json={"actor": "林乔", "role": "研发", "decision": "APPROVE", "expected_revision": 1},
    ).status_code == 200
    final_commitment = client.post(
        f"/api/cases/{DEMO_CASE_ID}/paths/PATH-01/commitments/CUSTOMER/decision",
        json={"actor": "赵宁", "role": "供应经理", "decision": "APPROVE", "expected_revision": 1},
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
        DEMO_CASE_ID, "PATH-01", "SUPPLY", actor="王淼", role="主计划", expected_revision=1,
    )
    supply_node = next(node for node in case.commitment_nodes if node.id == "SUPPLY")
    customer = next(node for node in case.commitment_nodes if node.id == "CUSTOMER")
    assert supply_node.status is NodeStatus.READY
    assert customer.status is NodeStatus.BLOCKED
    assert not service.get_inbox("主计划")

    case = service.decide_commitment(
        DEMO_CASE_ID, "PATH-01", "TECH",
        decision=CommitmentDecision.REVISE, actor="林乔", role="研发",
        expected_revision=1, reason="请补充替代料认证范围。",
    )
    assert case.phase is OrchestrationPhase.PATH_EXPLORATION
    assert case.path_attempts[0].state is PathAttemptState.REVISING
    assert service.get_inbox("研发") == []

    asyncio.run(service.execute_path(DEMO_CASE_ID, "PATH-01", actor=OWNER_ACTOR, role=OWNER_ROLE))
    service.approve_commitment(
        DEMO_CASE_ID, "PATH-01", "SUPPLY", actor="王淼", role="主计划", expected_revision=2,
    )
    service.approve_commitment(
        DEMO_CASE_ID, "PATH-01", "TECH", actor="林乔", role="研发", expected_revision=2,
    )
    case = service.decide_commitment(
        DEMO_CASE_ID, "PATH-01", "CUSTOMER",
        decision=CommitmentDecision.REJECT, actor="赵宁", role="供应经理",
        expected_revision=2, reason="客户不同意本方案。",
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
            service.approve_commitment(
                DEMO_CASE_ID, "PATH-01", node_id, actor=actor, role=role, expected_revision=1,
            )
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
    approve_and_execute(service)
    regenerated = service.get_case(DEMO_CASE_ID)
    assert regenerated.path_attempts[0].solution_revision.revision == 2
    before = regenerated.to_dict()
    events = service.repository.list_events(DEMO_CASE_ID)
    with pytest.raises(InvalidTransitionError):
        service.approve_commitment(
            DEMO_CASE_ID, "PATH-01", "SUPPLY", actor="王淼", role="主计划", expected_revision=1,
        )
    assert service.get_case(DEMO_CASE_ID).to_dict() == before
    assert service.repository.list_events(DEMO_CASE_ID) == events
    approved = service.approve_commitment(
        DEMO_CASE_ID, "PATH-01", "SUPPLY", actor="王淼", role="主计划", expected_revision=2,
    )
    assert next(node for node in approved.commitment_nodes if node.id == "SUPPLY").reviewed_revision == 2


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


class _HumanInputPathAdapter:
    profile = "test/human-input"

    def __init__(self, *, needs_information: bool = False) -> None:
        self.needs_information = needs_information
        self.contexts = []

    async def generate(self, context, trace):
        self.contexts.append(context)
        if self.needs_information and not context.human_information:
            return PathAgentResult(information_requests=[
                InformationQuestion(role="主计划", question="实际可用数量是多少？", reason="核对本次缺料覆盖量。"),
                InformationQuestion(role="研发", question="替代料已完成哪些认证？", reason="判断适用范围。"),
            ])
        return PathAgentResult(
            recommendation="建议按已提供的数量和认证范围继续评审替代方案。",
            role_reports=[
                RoleReport(role=item["role"], dimension=item["dimension"], report="请确认补充资料适用于当前订单。")
                for item in context.required_role_reports
            ],
            change_summary="已按研发反馈补充认证范围，等待各责任角色重新确认。"
            if context.previous_solution_revision else "",
        )


def test_revision_feedback_invalidates_all_path_approvals_and_rejects_old_version(tmp_path) -> None:
    adapter = _HumanInputPathAdapter()
    service = make_service(tmp_path, path_agent=adapter)
    approve_and_execute(service)
    original = service.get_case(DEMO_CASE_ID).path_attempts[0].solution_revision
    service.approve_commitment(
        DEMO_CASE_ID, "PATH-01", "SUPPLY", actor="王淼", role="主计划", expected_revision=1,
    )
    reason = "认证报告仅覆盖旧型号，请重新核对当前型号。"
    revised = service.decide_commitment(
        DEMO_CASE_ID, "PATH-01", "TECH", actor="林乔", role="研发",
        decision=CommitmentDecision.REVISE, expected_revision=1, reason=reason,
    )
    assert all(node.status is NodeStatus.STALE for node in revised.commitment_nodes)
    adapter.needs_information = True
    waiting = asyncio.run(service.execute_path(DEMO_CASE_ID, "PATH-01", **OWNER))
    assert waiting.phase is OrchestrationPhase.PATH_EXPLORATION
    assert waiting.path_attempts[0].solution_revision.revision == 1
    assert waiting.path_attempts[0].state is PathAttemptState.AWAITING_INFORMATION
    for request in waiting.path_attempts[0].information_requests:
        service.answer_information_request(
            DEMO_CASE_ID, "PATH-01", request.id, actor="责任人", role=request.role, answer="已补充当前型号资料。",
        )
    assert service.get_case(DEMO_CASE_ID).path_attempts[0].state is PathAttemptState.REVISING
    asyncio.run(service.execute_path(DEMO_CASE_ID, "PATH-01", **OWNER))
    case = service.get_case(DEMO_CASE_ID)
    assert case.path_attempts[0].solution_revision.revision == 2
    assert {node.id: node.status for node in case.commitment_nodes} == {
        "SUPPLY": NodeStatus.PENDING, "TECH": NodeStatus.PENDING, "CUSTOMER": NodeStatus.BLOCKED,
    }
    assert all(node.reviewed_revision is None and node.decision_reason is None for node in case.commitment_nodes)
    feedback = adapter.contexts[-1].revision_feedback
    assert len(feedback) == 1
    assert feedback[0]["reason"] == reason
    assert feedback[0]["actor"] == "林乔"
    assert feedback[0]["revision"] == 1
    assert feedback[0]["recommendation_snapshot"] == original.recommendation
    assert feedback[0]["role_report_snapshot"]["role"] == "研发"
    before = case.to_dict()
    events = service.repository.list_events(DEMO_CASE_ID)
    with pytest.raises(InvalidTransitionError):
        service.approve_commitment(
            DEMO_CASE_ID, "PATH-01", "SUPPLY", actor="王淼", role="主计划", expected_revision=1,
        )
    assert service.get_case(DEMO_CASE_ID).to_dict() == before
    assert service.repository.list_events(DEMO_CASE_ID) == events
    approved = service.approve_commitment(
        DEMO_CASE_ID, "PATH-01", "SUPPLY", actor="王淼", role="主计划", expected_revision=2,
    )
    assert next(node for node in approved.commitment_nodes if node.id == "SUPPLY").reviewed_revision == 2


@pytest.mark.parametrize("decision", [CommitmentDecision.REVISE, CommitmentDecision.REJECT])
def test_revision_and_rejection_require_nonempty_reason_without_writing(tmp_path, decision) -> None:
    service = make_service(tmp_path)
    approve_and_execute(service)
    before = service.get_case(DEMO_CASE_ID).to_dict()
    events = service.repository.list_events(DEMO_CASE_ID)
    with pytest.raises(InvalidTransitionError):
        service.decide_commitment(
            DEMO_CASE_ID, "PATH-01", "TECH", actor="林乔", role="研发",
            decision=decision, expected_revision=1, reason="  ",
        )
    assert service.get_case(DEMO_CASE_ID).to_dict() == before
    assert service.repository.list_events(DEMO_CASE_ID) == events


def test_human_information_request_answer_resume_and_approval(client, monkeypatch, tmp_path) -> None:
    from agentic_cm import api

    adapter = _HumanInputPathAdapter(needs_information=True)
    service = make_service(tmp_path, path_agent=adapter)
    monkeypatch.setattr(api, "service", service)
    approve_and_execute(service)
    waiting = service.get_case(DEMO_CASE_ID)
    assert waiting.phase is OrchestrationPhase.PATH_EXPLORATION
    assert waiting.path_attempts[0].state is PathAttemptState.AWAITING_INFORMATION
    assert waiting.path_attempts[0].solution_revision is None
    original_business_payload = waiting.business_payload
    supply_item = service.get_inbox("主计划")[0]
    assert supply_item["kind"] == "information_request"
    assert "node" not in supply_item
    request_id = supply_item["information_request"]["id"]
    path = f"/api/cases/{DEMO_CASE_ID}/paths/PATH-01/information-requests/{request_id}/answer"
    before = waiting.to_dict()
    assert client.post(path, json={"actor": "林乔", "role": "研发", "answer": "18400 件"}).status_code == 403
    assert client.post(path, json={"actor": "王淼", "role": "主计划", "answer": "  "}).status_code == 409
    assert service.get_case(DEMO_CASE_ID).to_dict() == before
    with pytest.raises(InvalidTransitionError):
        asyncio.run(service.execute_path(DEMO_CASE_ID, "PATH-01", **OWNER))
    assert len(adapter.contexts) == 1
    assert client.post(path, json={"actor": "王淼", "role": "主计划", "answer": "18400 件"}).status_code == 200
    assert service.get_case(DEMO_CASE_ID).path_attempts[0].state is PathAttemptState.AWAITING_INFORMATION
    assert client.post(path, json={"actor": "王淼", "role": "主计划", "answer": "20000 件"}).status_code == 409
    engineering_id = service.get_inbox("研发")[0]["information_request"]["id"]
    assert client.post(
        f"/api/cases/{DEMO_CASE_ID}/paths/PATH-01/information-requests/{engineering_id}/answer",
        json={"actor": "林乔", "role": "研发", "answer": "已完成当前型号的可靠性认证。"},
    ).status_code == 200
    answered = service.get_case(DEMO_CASE_ID)
    assert answered.path_attempts[0].state is PathAttemptState.PLANNED
    assert answered.path_attempts[0].solution_revision is None
    assert service.get_inbox("主计划") == []
    assert service.get_inbox("研发") == []
    assert client.post(
        f"/api/cases/{DEMO_CASE_ID}/paths/PATH-01/execute", json={"actor": "王淼", "role": "主计划"},
    ).status_code == 403
    resumed = client.post(f"/api/cases/{DEMO_CASE_ID}/paths/PATH-01/execute", json=OWNER)
    assert resumed.status_code == 200
    assert resumed.json()["phase"] == "PROFESSIONAL_COMMITMENT"
    assert resumed.json()["path_attempts"][0]["solution_revision"]["revision"] == 1
    assert adapter.contexts[-1].human_information[0]["answer"] == "18400 件"
    assert adapter.contexts[-1].human_information[0]["answered_by"] == "王淼"
    assert adapter.contexts[-1].human_information[0]["answered_at"]
    assert service.get_case(DEMO_CASE_ID).business_payload == original_business_payload
    assert service.get_inbox("主计划")[0]["kind"] == "commitment"
    for node_id, actor, role in (("SUPPLY", "王淼", "主计划"), ("TECH", "林乔", "研发"), ("CUSTOMER", "赵宁", "供应经理")):
        service.approve_commitment(DEMO_CASE_ID, "PATH-01", node_id, actor=actor, role=role, expected_revision=1)

    assert service.get_case(DEMO_CASE_ID).phase is OrchestrationPhase.FINAL_REVIEW
    timeline = service.get_case_timeline(DEMO_CASE_ID)
    assert sum(event["event_type"] == "information.requested" for event in timeline) == 2
    assert sum(event["event_type"] == "information.answered" for event in timeline) == 2
    initial_run = service.get_agent_runs(DEMO_CASE_ID, **OWNER, agent_type="path")[-1]
    assert initial_run["status"] == "SUCCEEDED"


@pytest.mark.parametrize("quantity", [0, 12000, 18400])
def test_supply_information_is_scoped_to_substitute_and_deadline(client, quantity: int) -> None:
    from agentic_cm import api
    from agentic_cm.demo import SUPPLY_INFORMATION_DATASET_ID

    assert client.post("/api/demo/reset", json={"dataset_id": SUPPLY_INFORMATION_DATASET_ID}).status_code == 204
    original = api.service.get_case(DEMO_CASE_ID).business_payload.copy()
    assert original["gap_quantity"] == 18400
    assert original["target_date"]
    assert client.post(f"/api/cases/{DEMO_CASE_ID}/orchestrate", json=OWNER).status_code == 200
    assert client.post(
        f"/api/cases/{DEMO_CASE_ID}/manifest/approve", json={"selected_path_ids": ["PATH-01"], **OWNER},
    ).status_code == 200
    waiting = client.post(f"/api/cases/{DEMO_CASE_ID}/paths/PATH-01/execute", json=OWNER)
    assert waiting.status_code == 200
    attempt = waiting.json()["path_attempts"][0]
    assert attempt["state"] == "AWAITING_INFORMATION"
    assert attempt["solution_revision"] is None
    request = api.service.get_inbox("主计划")[0]["information_request"]
    assert request["material_id"] == "MCU-X7A"
    assert request["required_by"] == original["target_date"]
    endpoint = f"/api/cases/{DEMO_CASE_ID}/paths/PATH-01/information-requests/{request['id']}/answer"
    body = {"actor": "王淼", "role": "主计划", "answer": "供应方书面确认，按指定日期到货。"}
    before = api.service.get_case(DEMO_CASE_ID).to_dict()
    assert client.post(endpoint, json=body).status_code == 409
    for invalid in (-1, 1.5, True):
        assert client.post(endpoint, json={**body, "quantity": invalid}).status_code == 422
    assert api.service.get_case(DEMO_CASE_ID).to_dict() == before
    answered = client.post(endpoint, json={**body, "quantity": quantity})
    assert answered.status_code == 200
    confirmation = answered.json()["path_attempts"][0]["information_requests"][0]
    assert confirmation["answer_quantity"] == quantity
    assert confirmation["answered_by"] == "王淼"
    assert confirmation["material_id"] == "MCU-X7A"
    assert confirmation["required_by"] == original["target_date"]
    assert all(node["status"] != "READY" for node in answered.json()["commitment_nodes"])
    completed = client.post(f"/api/cases/{DEMO_CASE_ID}/paths/PATH-01/execute", json=OWNER)
    assert completed.status_code == 200
    solution = completed.json()["path_attempts"][0]["solution_revision"]
    assert solution["revision"] == 1
    assert "MCU-X7A" in solution["recommendation"]
    assert original["target_date"] in solution["recommendation"]
    assert f"{quantity:,}" in solution["recommendation"]
    assert f"{18400 - quantity:,}" in solution["recommendation"]
    reports = {item["role"]: item["report"] for item in solution["role_reports"]}
    supply_report = reports["主计划"]
    for fact in ("MCU-X7A", original["target_date"], f"{quantity:,}", f"{18400 - quantity:,}", body["answer"], "王淼"):
        assert fact in supply_report
    assert body["answer"] not in reports["研发"]
    assert api.service.get_case(DEMO_CASE_ID).business_payload == original


def test_case_payload_without_new_review_fields_remains_readable(tmp_path) -> None:
    service = make_service(tmp_path)
    approve_and_execute(service)
    legacy = service.get_case(DEMO_CASE_ID).to_dict()
    for node in legacy["commitment_nodes"]:
        node.pop("reviewed_revision")
        node.pop("decision_reason")
    for attempt in legacy["path_attempts"]:
        attempt.pop("information_requests")
        attempt["solution_revision"].pop("information_requests")
        attempt["solution_revision"].pop("change_summary")
    loaded = Case.model_validate(legacy)
    assert loaded.path_attempts[0].information_requests == []
    assert loaded.path_attempts[0].solution_revision.revision == 1
    assert all(node.reviewed_revision is None for node in loaded.commitment_nodes)
