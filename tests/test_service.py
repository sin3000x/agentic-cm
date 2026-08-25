import asyncio
import json
import os
import shutil
from pathlib import Path

import httpx

from agentic_cm.capabilities import (
    DEFAULT_BUILTIN_ROOT,
    CapabilityConfigurationError,
    CapabilityConflictError,
    CapabilityRegistry,
)
from agentic_cm.domain import (
    CaseStatus,
    CommitmentDecision,
    NodeStatus,
    OrchestrationPhase,
    OwnerDecisionAction,
)
from agentic_cm.demo import DEMO_DATASET_ID, demo_cases
from agentic_cm.orchestrator import (
    DeterministicPlannerAdapter,
    ManifestDraftResult,
    OpenAICompatiblePlannerAdapter,
    OrchestrationError,
    PlannedPath,
    PlannerOutputError,
)
from agentic_cm.repository import CaseRepository
from agentic_cm.path_agent import (
    DeterministicPathAgentAdapter,
    OpenAICompatiblePathAgentAdapter,
    PathAgentOutputError,
    PathAgentResult,
    PathAgentExecutionError,
    ProposedOption,
    RoleReport,
)
from agentic_cm.service import AuthorizationError, CaseService, InvalidTransitionError
from agentic_cm.synthesis_agent import (
    DeterministicSynthesisAgentAdapter,
    OpenAICompatibleSynthesisAgentAdapter,
)


def make_service(tmp_path: Path) -> CaseService:
    service = CaseService(
        CaseRepository(tmp_path / "test.db"),
        planner=DeterministicPlannerAdapter(),
        path_agent=DeterministicPathAgentAdapter(),
        synthesis_agent=DeterministicSynthesisAgentAdapter(),
    )
    service.ensure_demo_data()
    return service


def test_demo_dataset_is_the_authoritative_case_overview_source(tmp_path: Path) -> None:
    cases = {case.id: case for case in demo_cases()}

    assert cases["CM-2026-014"].title == "Northstar Mobility MCU-X7 订单预计延期 12 天"
    assert cases["CM-2026-015"].title == "MCU-X7B 替代料缺少客户认证与技术验证"
    assert all(case.description != "固定演示 Case" for case in cases.values())
    assert all(case.business_payload.get("risk_level") for case in cases.values())
    assert all(case.business_payload.get("commitment_due_date") for case in cases.values())

    service = make_service(tmp_path)
    legacy = service.get_case("CM-2026-012")
    legacy.title = "供应商交付异常"
    legacy.description = "固定演示 Case"
    legacy.business_payload = {}
    service.repository.save(legacy, "test.legacy_seed", {})
    service.ensure_demo_data()

    migrated = service.get_case("CM-2026-012")
    assert migrated.title == cases["CM-2026-012"].title
    assert migrated.business_payload["risk_level"] == "HIGH"
    assert service.repository.list_events("CM-2026-012")[-1]["event_type"] == "case.demo_metadata_migrated"
    service.reset_demo(DEMO_DATASET_ID)


def orchestrate(service: CaseService):
    return asyncio.run(service.orchestrate_case(
        "CM-2026-014", actor="陈澄", role="订单统筹经理"
    ))


def approve_and_execute_path(service: CaseService):
    orchestrate(service)
    service.approve_manifest(
        "CM-2026-014", ["PATH-01"], actor="陈澄", role="订单统筹经理"
    )
    return asyncio.run(service.execute_path(
        "CM-2026-014", "PATH-01", actor="陈澄", role="订单统筹经理"
    ))


def test_runtime_environment_loads_repository_dotenv(tmp_path: Path, monkeypatch) -> None:
    from agentic_cm import config

    monkeypatch.setattr(config, "REPOSITORY_ROOT", tmp_path)
    (tmp_path / ".env").write_text("AGENTIC_CM_TEST_DOTENV=loaded\n")
    try:
        config.load_runtime_environment()
        assert os.environ["AGENTIC_CM_TEST_DOTENV"] == "loaded"
    finally:
        os.environ.pop("AGENTIC_CM_TEST_DOTENV", None)


def test_orchestrator_builds_manifest_from_open_delay_case(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    initial = service.get_case("CM-2026-014")
    assert initial.phase is OrchestrationPhase.INTAKE
    assert initial.manifest is None

    case = orchestrate(service)

    assert case.phase is OrchestrationPhase.MANIFEST_REVIEW
    assert case.manifest.generated_from_case_version == 1
    assert case.manifest.planner_profile == "deterministic/v1"
    assert all(
        "deterministic 模式不判断当前 Case 的业务优先级" in path.rationale
        for path in case.manifest.paths
    )
    assert all("候选 A/B" not in path.rationale for path in case.manifest.paths)
    assert [path.definition for path in case.manifest.paths] == [
        "MaterialSubstitution", "SupplyExpediting", "OrderSplit"
    ]
    assert set(case.manifest.policy_refs) == {
        "POL-SUBSTITUTION-3@3.3.0", "POL-CUSTOMER-2@2.4.0",
        "POL-EXPEDITING-1@1.3.0", "POL-ORDER-SPLIT-1@1.3.0",
    }
    assert {item["id"] for item in case.manifest.capability_snapshot["compiled_policy"]["commitments"]} == {
        "SUPPLY", "TECH", "CUSTOMER"
    }
    manifest = service.get_case_manifest(
        "CM-2026-014", actor="陈澄", role="订单统筹经理"
    )
    assert manifest["id"] == "MAN-CM-2026-014-1"
    assert manifest["planner_profile"] == "deterministic/v1"


def test_orchestration_skill_paths_are_partitioned_by_case_type(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    skills = builtin / "skills"
    bindings = {}
    for skill_name, case_type, title in (
        ("quality-planning", "QUALITY_INCIDENT", "质量人工复核"),
        ("payment-planning", "PAYMENT_EXCEPTION", "付款人工复核"),
    ):
        skill_dir = skills / skill_name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {skill_name}\ndescription: Plan review paths for {case_type}.\n---\n\n# Plan\n"
        )
        (skill_dir / "paths.json").write_text(json.dumps({
            "schema_version": 1,
            "paths": [{"id": "ManualReview", "title": title, "description": "case-specific review"}],
        }))
        bindings[skill_name] = {"selector": {"case_type": [case_type]}}
    (builtin / "skill-bindings.json").write_text(json.dumps({
        "schema_version": 1,
        "bindings": bindings,
    }))

    registry = CapabilityRegistry.from_directories(builtin, None)

    assert [item.title for item in registry.resolve_path_candidates({"case_type": "QUALITY_INCIDENT"})] == [
        "质量人工复核"
    ]
    assert [item.title for item in registry.resolve_path_candidates({"case_type": "PAYMENT_EXCEPTION"})] == [
        "付款人工复核"
    ]
    assert registry.resolve_path_candidates({"case_type": "ORDER_DELIVERY_RISK"}) == ()


def test_paths_owning_skill_requires_one_case_type_binding(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    skill_dir = builtin / "skills" / "unscoped-planning"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: unscoped-planning\ndescription: Invalid fixture.\n---\n\n# Plan\n"
    )
    (skill_dir / "paths.json").write_text(json.dumps({
        "schema_version": 1,
        "paths": [{"id": "ManualReview", "title": "人工复核", "description": "fixture"}],
    }))
    (builtin / "skill-bindings.json").write_text(json.dumps({
        "schema_version": 1,
        "bindings": {"unscoped-planning": {"selector": {"case_type": ["ONE", "TWO"]}}},
    }))

    try:
        CapabilityRegistry.from_directories(builtin, None)
    except CapabilityConfigurationError as exc:
        assert "must bind exactly one case_type" in str(exc)
    else:
        raise AssertionError("A paths-owning Skill must belong to one Case type")


def test_professional_commitments_open_only_after_path_exploration(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    orchestrate(service)
    initial_case = service.get_case("CM-2026-014")
    assert initial_case.human_proposal is not None
    assert initial_case.human_proposal["author"] == initial_case.owner
    assert initial_case.human_proposal["role"] == initial_case.owner_role
    case = service.approve_manifest(
        "CM-2026-014", ["PATH-01"], actor="陈澄", role="订单统筹经理"
    )
    assert case.phase is OrchestrationPhase.PATH_EXPLORATION
    pending = {node.id for node in case.commitment_nodes if node.status is NodeStatus.PENDING}
    assert pending == {"SUPPLY", "TECH"}
    assert service.get_inbox("主计划") == []
    assert service.get_inbox("研发") == []
    assert [attempt["definition"] for attempt in case.path_attempts] == ["MaterialSubstitution"]
    assert case.commitment_nodes[-1].status is NodeStatus.BLOCKED

    case = asyncio.run(service.execute_path(
        "CM-2026-014", "PATH-01", actor="陈澄", role="订单统筹经理"
    ))

    assert case.phase is OrchestrationPhase.PROFESSIONAL_COMMITMENT
    assert {item["node"].id for item in service.get_inbox("主计划")} == {"SUPPLY"}
    assert {item["node"].id for item in service.get_inbox("研发")} == {"TECH"}


def test_manifest_is_visible_and_actionable_only_by_case_owner(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    orchestrate(service)

    owner_view = service.get_case_view(
        "CM-2026-014", actor="陈澄", role="订单统筹经理"
    )
    other_role_view = service.get_case_view(
        "CM-2026-014", actor="王淼", role="主计划"
    )
    anonymous_view = service.get_case_view("CM-2026-014")

    assert owner_view["manifest"] is not None
    assert owner_view["permissions"]["can_approve_manifest"] is True
    assert other_role_view["manifest"] is None
    assert other_role_view["workflow_paths"] == []
    assert other_role_view["synthesis_report"] is None
    assert other_role_view["permissions"]["can_view_manifest"] is False
    assert other_role_view["permissions"]["can_decide_case"] is False
    assert anonymous_view["manifest"] is None

    for operation in (
        lambda: service.get_case_manifest(
            "CM-2026-014", actor="王淼", role="主计划"
        ),
        lambda: service.approve_manifest(
            "CM-2026-014", ["PATH-01"], actor="王淼", role="主计划"
        ),
    ):
        try:
            operation()
        except AuthorizationError:
            pass
        else:
            raise AssertionError("a non-owner must not access or approve the Manifest")

    case = service.get_case("CM-2026-014")
    assert case.phase is OrchestrationPhase.MANIFEST_REVIEW


def test_manifest_http_endpoints_enforce_owner_boundary(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from agentic_cm import api

    monkeypatch.setattr(api, "service", make_service(tmp_path))
    client = TestClient(api.app)
    owner = {"actor": "陈澄", "role": "订单统筹经理"}

    assert client.post(
        "/api/cases/CM-2026-014/orchestrate", json=owner
    ).status_code == 200

    library = client.get("/api/capabilities")
    assert library.status_code == 200
    assert library.json()["counts"] == {"policies": 4, "skills": 7, "knowledge": 1}
    assert {asset["id"] for asset in library.json()["assets"]["skills"]} == {
        "shortage-response-planning", "material-substitution-analysis",
        "material-substitution-engineering-review",
        "material-substitution-master-planning-review",
        "material-substitution-supply-manager-review",
        "supply-expediting-analysis", "order-split-analysis",
    }

    other_view = client.get(
        "/api/cases/CM-2026-014", params={"actor": "王淼", "role": "主计划"}
    )
    assert other_view.status_code == 200
    assert other_view.json()["manifest"] is None
    assert other_view.json()["permissions"]["can_view_manifest"] is False

    assert client.get(
        "/api/cases/CM-2026-014/manifest",
        params={"actor": "王淼", "role": "主计划"},
    ).status_code == 403

    trace = client.get(
        "/api/cases/CM-2026-014/agent-runs",
        params={**owner, "agent_type": "orchestrator"},
    )
    assert trace.status_code == 200
    assert trace.json()[0]["status"] == "SUCCEEDED"
    assert client.get(
        "/api/cases/CM-2026-014/agent-runs",
        params={"actor": "王淼", "role": "主计划", "agent_type": "orchestrator"},
    ).status_code == 403
    assert client.post(
        "/api/cases/CM-2026-014/manifest/approve",
        json={"selected_path_ids": ["PATH-01"], "actor": "王淼", "role": "主计划"},
    ).status_code == 403
    assert client.post(
        "/api/cases/CM-2026-014/manifest/approve",
        json={"selected_path_ids": ["PATH-01"], **owner},
    ).status_code == 200
    timeline = client.get("/api/cases/CM-2026-014/timeline")
    assert timeline.status_code == 200
    assert [event["event_type"] for event in timeline.json()] == [
        "manifest.proposed", "manifest.approved"
    ]
    assert "selected_path_ids" not in timeline.json()[-1]["details"]

    assert client.post(
        "/api/cases/CM-2026-014/paths/PATH-01/execute",
        json={"actor": "王淼", "role": "主计划"},
    ).status_code == 403
    path_result = client.post(
        "/api/cases/CM-2026-014/paths/PATH-01/execute", json=owner
    )
    assert path_result.status_code == 200
    assert [option["id"] for option in path_result.json()["path_attempts"][0]["solution_revision"]["options"]] == [
        "A", "B"
    ]
    path_trace = client.get(
        "/api/cases/CM-2026-014/agent-runs", params={**owner, "agent_type": "path"}
    )
    assert path_trace.status_code == 200
    assert path_trace.json()[0]["status"] == "SUCCEEDED"

    approval = client.post(
        "/api/cases/CM-2026-014/paths/PATH-01/commitments/SUPPLY/approve",
        json={"actor": "王淼", "role": "主计划"},
    )
    assert approval.status_code == 200
    assert approval.json()["manifest"] is None
    assert approval.json()["workflow_paths"] == [{
        "id": "PATH-01",
        "definition": "MaterialSubstitution",
        "title": "物料替代",
        "selected": True,
        "rationale": "",
    }]
    assert client.get("/api/cases/CM-2026-014/timeline").json()[-1]["details"] == {
        "actor": "王淼",
        "role": "主计划",
        "node_id": "SUPPLY",
        "path_id": "PATH-01",
    }
    assert client.post(
        "/api/cases/CM-2026-014/paths/PATH-01/commitments/TECH/decision",
        json={"actor": "林乔", "role": "研发", "decision": "APPROVE"},
    ).status_code == 200
    final_commitment = client.post(
        "/api/cases/CM-2026-014/paths/PATH-01/commitments/CUSTOMER/decision",
        json={"actor": "赵宁", "role": "供应经理", "decision": "APPROVE"},
    )
    assert final_commitment.status_code == 200
    assert final_commitment.json()["phase"] == "FINAL_REVIEW"
    assert client.post(
        "/api/cases/CM-2026-014/synthesize",
        json={"actor": "王淼", "role": "主计划"},
    ).status_code == 403
    synthesized = client.post("/api/cases/CM-2026-014/synthesize", json=owner)
    assert synthesized.status_code == 200
    assert synthesized.json()["synthesis_report"]["path_assessments"][0]["status"] == "SUCCEEDED"
    decision = client.post(
        "/api/cases/CM-2026-014/owner-decision",
        json={**owner, "action": "KEEP_OPEN"},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "OPEN"


def test_role_inbox_approval_makes_node_ready_and_releases_dependents(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    approve_and_execute_path(service)

    try:
        service.approve_commitment(
            "CM-2026-014", "PATH-01", "SUPPLY", actor="林乔", role="研发"
        )
    except InvalidTransitionError as exc:
        assert "requires role 主计划" in str(exc)
    else:
        raise AssertionError("a different role must not approve the commitment")

    case = service.approve_commitment(
        "CM-2026-014", "PATH-01", "SUPPLY", actor="王淼", role="主计划"
    )
    statuses = {node.id: node.status for node in case.commitment_nodes}
    assert statuses == {
        "SUPPLY": NodeStatus.READY,
        "TECH": NodeStatus.PENDING,
        "CUSTOMER": NodeStatus.BLOCKED,
    }

    case = service.approve_commitment(
        "CM-2026-014", "PATH-01", "TECH", actor="林乔", role="研发"
    )
    statuses = {node.id: node.status for node in case.commitment_nodes}
    assert statuses == {
        "SUPPLY": NodeStatus.READY,
        "TECH": NodeStatus.READY,
        "CUSTOMER": NodeStatus.PENDING,
    }
    assert {item["node"].id for item in service.get_inbox("供应经理")} == {"CUSTOMER"}
    timeline = service.get_case_timeline("CM-2026-014")
    approvals = [event for event in timeline if event["event_type"] == "commitment.approved"]
    assert [event["details"]["actor"] for event in approvals] == ["王淼", "林乔"]
    assert [event["details"]["node_id"] for event in approvals] == ["SUPPLY", "TECH"]
    assert all(event["created_at"].endswith("+00:00") for event in approvals)
    assert all("reviews" not in event["details"] for event in approvals)


def test_commitment_revision_request_enters_revising_and_leaves_inbox(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    approve_and_execute_path(service)

    case = service.decide_commitment(
        "CM-2026-014", "PATH-01", "SUPPLY",
        decision=CommitmentDecision.REVISE, actor="王淼", role="主计划",
    )

    assert {node.id: node.status for node in case.commitment_nodes} == {
        "SUPPLY": NodeStatus.STALE,
        "TECH": NodeStatus.PENDING,
        "CUSTOMER": NodeStatus.BLOCKED,
    }
    assert case.path_attempts[0]["phase"] == "REVISING"
    assert case.phase is OrchestrationPhase.PATH_EXPLORATION
    assert service.get_inbox("主计划") == []
    assert service.get_case_timeline("CM-2026-014")[-1]["event_type"] == "commitment.revision_requested"


def test_commitment_rejection_ends_path_and_invalidates_open_nodes(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    approve_and_execute_path(service)

    case = service.decide_commitment(
        "CM-2026-014", "PATH-01", "TECH",
        decision=CommitmentDecision.REJECT, actor="林乔", role="研发",
    )

    assert {node.id: node.status for node in case.commitment_nodes} == {
        "SUPPLY": NodeStatus.STALE,
        "TECH": NodeStatus.REJECTED,
        "CUSTOMER": NodeStatus.STALE,
    }
    assert case.path_attempts[0]["phase"] == "DONE"
    assert case.path_attempts[0]["outcome"] == "REJECTED"
    assert service.get_inbox("主计划") == []
    assert service.get_inbox("研发") == []
    assert service.get_case_timeline("CM-2026-014")[-1]["event_type"] == "commitment.rejected"


def test_demo_manifest_freezes_resolved_capabilities(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    orchestrate(service)
    case = service.get_case("CM-2026-014")
    snapshot = case.manifest.capability_snapshot
    assert snapshot is not None
    assert {item["id"] for item in snapshot["policies"]} == {"POL-SUBSTITUTION-3", "POL-CUSTOMER-2"}
    assert {item["id"] for item in snapshot["skills"]} == {
        "material-substitution-analysis",
        "material-substitution-engineering-review",
        "material-substitution-master-planning-review",
        "material-substitution-supply-manager-review",
        "shortage-response-planning",
    }
    assert [item["id"] for item in snapshot["knowledge"]] == ["KNOW-2025-041"]
    assert all(item["digest"].startswith("sha256:") for item in snapshot["policies"])
    assert "path_inputs" not in case.business_payload
    base_skill = next(
        item for item in snapshot["asset_payloads"]["skills"]
        if item["id"] == "material-substitution-analysis"
    )
    assert [item["id"] for item in base_skill["path_options"]] == ["A", "B"]
    assert [item["id"] for item in base_skill["tools"]] == [
        "mock.material-master.lookup",
        "mock.supply-snapshot.lookup",
        "mock.customer-acceptance.lookup",
    ]
    role_contracts = {
        item["role"]: item["role_report"]["dimension"]
        for item in snapshot["compiled_policy"]["commitments"]
    }
    assert role_contracts == {
        "研发": "技术可行性",
        "主计划": "供应与交付可行性",
        "供应经理": "客户与商务接受度",
    }


def test_local_asset_replaces_builtin_without_editing_builtin(tmp_path: Path) -> None:
    local_skill_dir = tmp_path / "local" / "skills" / "material-substitution-analysis"
    local_skill_dir.mkdir(parents=True)
    source = DEFAULT_BUILTIN_ROOT / "skills" / "material-substitution-analysis" / "SKILL.md"
    local_copy = local_skill_dir / "SKILL.md"
    content = source.read_text().replace("候选集只能来自", "冻结候选集只能来自")
    local_copy.write_text(content)

    registry = CapabilityRegistry.from_directories(DEFAULT_BUILTIN_ROOT, tmp_path / "local")
    resolution = registry.resolve({
        "case_type": "ORDER_DELIVERY_RISK",
        "path_definition": "MaterialSubstitution",
    })

    assert resolution.skills[0].source == "local"
    local_version = resolution.skills[0].version
    frozen_snapshot = resolution.to_snapshot()

    local_copy.write_text(content.replace("冻结候选集只能来自", "已评审候选集只能来自"))
    reloaded = CapabilityRegistry.from_directories(DEFAULT_BUILTIN_ROOT, tmp_path / "local")
    assert reloaded.resolve({
        "case_type": "ORDER_DELIVERY_RISK",
        "path_definition": "MaterialSubstitution",
    }).skills[0].version != local_version
    frozen_details = reloaded.describe_snapshot(frozen_snapshot)
    frozen_skill = frozen_details["assets"]["skills"][0]
    assert frozen_skill["version"] == local_version
    assert frozen_skill["resolved_ref"]["source"] == "local"


def test_developer_can_add_new_local_assets_with_unrelated_filenames() -> None:
    repository_root = DEFAULT_BUILTIN_ROOT.parents[1]
    local_examples = repository_root / "examples" / "local-capabilities"
    registry = CapabilityRegistry.from_directories(DEFAULT_BUILTIN_ROOT, local_examples)
    resolution = registry.resolve({
        "case_type": "ORDER_DELIVERY_RISK",
        "path_definition": "MaterialSubstitution",
    })

    assert "POL-MY-COMPANY-REGION-001" in {item.id for item in resolution.policies}
    assert "regional-certification-check" in {item.id for item in resolution.skills}
    assert "KNOW-MY-COMPANY-REGION-001" in {item.id for item in resolution.knowledge}
    assert all(
        item.source == "local"
        for item in (*resolution.policies, *resolution.skills, *resolution.knowledge)
        if item.id in {
            "POL-MY-COMPANY-REGION-001",
            "regional-certification-check",
            "KNOW-MY-COMPANY-REGION-001",
        }
    )
    assert "REGION-COMPLIANCE" in {item["id"] for item in resolution.compiled_policy["commitments"]}


def test_knowledge_is_advisory_and_does_not_create_commitments(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    orchestrate(service)
    details = service.get_case_capabilities("CM-2026-014")
    compiled = details["snapshot"]["compiled_policy"]
    assert details["snapshot_status"] == "frozen"
    assert len(details["assets"]["knowledge"]) == 1
    assert {item["id"] for item in compiled["commitments"]} == {"SUPPLY", "TECH", "CUSTOMER"}


def test_incompatible_commitment_policy_conflict_fails_closed(tmp_path: Path) -> None:
    policy_dir = tmp_path / "builtin" / "policies"
    policy_dir.mkdir(parents=True)
    base = {
        "schema_version": 1,
        "kind": "policy",
        "version": "1",
        "title": "conflict fixture",
        "status": "published",
        "selector": {
            "case_type": ["ORDER_DELIVERY_RISK"],
            "path_definition": ["MaterialSubstitution"],
        },
        "requirements": {
            "commitments": [
                {
                    "id": "REVIEW", "role": "主计划", "node_type": "REVIEW",
                    "reviews": ["supply"], "depends_on": [],
                    "role_report": {"dimension": "供应可行性", "sentence_prefix": "主计划维度："},
                }
            ]
        },
    }
    (policy_dir / "one.json").write_text(json.dumps(base | {"id": "POL-ONE"}))
    conflicting = base | {
        "id": "POL-TWO",
        "requirements": {
            "commitments": [
                {
                    "id": "REVIEW", "role": "研发", "node_type": "REVIEW",
                    "reviews": ["technical"], "depends_on": [],
                    "role_report": {"dimension": "技术可行性", "sentence_prefix": "研发维度："},
                }
            ]
        },
    }
    (policy_dir / "two.json").write_text(json.dumps(conflicting))
    registry = CapabilityRegistry.from_directories(tmp_path / "builtin", None)

    try:
        registry.resolve({
            "case_type": "ORDER_DELIVERY_RISK",
            "path_definition": "MaterialSubstitution",
        })
    except CapabilityConflictError:
        pass
    else:
        raise AssertionError("ambiguous Policy conflict must fail closed")


def test_initial_policy_rejects_unconsumed_generic_fields(tmp_path: Path) -> None:
    policy_dir = tmp_path / "builtin" / "policies"
    policy_dir.mkdir(parents=True)
    policy = {
        "schema_version": 1,
        "kind": "policy",
        "id": "POL-TOO-MUCH",
        "version": "1",
        "title": "unused constraint fixture",
        "status": "published",
        "selector": {
            "case_type": ["ORDER_DELIVERY_RISK"],
            "path_definition": ["MaterialSubstitution"],
        },
        "requirements": {"commitments": [], "constraints": {"unused": True}},
    }
    (policy_dir / "arbitrary-name.json").write_text(json.dumps(policy))

    try:
        CapabilityRegistry.from_directories(tmp_path / "builtin", None)
    except CapabilityConfigurationError:
        pass
    else:
        raise AssertionError("initial Policy must reject fields with no runtime consumer")


def test_path_scoped_capability_requires_case_type(tmp_path: Path) -> None:
    policy_dir = tmp_path / "builtin" / "policies"
    policy_dir.mkdir(parents=True)
    policy = {
        "schema_version": 1,
        "kind": "policy",
        "id": "POL-UNSCOPED-PATH",
        "version": "1",
        "title": "unscoped path fixture",
        "status": "published",
        "selector": {"path_definition": ["ManualReview"]},
        "requirements": {"commitments": []},
    }
    (policy_dir / "unscoped.json").write_text(json.dumps(policy))

    try:
        CapabilityRegistry.from_directories(tmp_path / "builtin", None)
    except CapabilityConfigurationError as exc:
        assert "without case_type" in str(exc)
    else:
        raise AssertionError("Path-scoped capabilities must also scope case_type")


def test_selector_rejects_fields_outside_initial_contract(tmp_path: Path) -> None:
    policy_dir = tmp_path / "builtin" / "policies"
    policy_dir.mkdir(parents=True)
    policy = {
        "schema_version": 1,
        "kind": "policy",
        "id": "POL-UNSUPPORTED-SELECTOR",
        "version": "1",
        "title": "unsupported selector fixture",
        "status": "published",
        "selector": {"business_unit": ["demo"]},
        "requirements": {"commitments": []},
    }
    (policy_dir / "unsupported.json").write_text(json.dumps(policy))

    try:
        CapabilityRegistry.from_directories(tmp_path / "builtin", None)
    except CapabilityConfigurationError as exc:
        assert "Unsupported selector fields ['business_unit']" in str(exc)
    else:
        raise AssertionError("Initial selectors must use only case_type and path_definition")


def test_manifest_cannot_be_approved_twice(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    orchestrate(service)
    service.approve_manifest(
        "CM-2026-014", actor="陈澄", role="订单统筹经理"
    )
    try:
        service.approve_manifest(
            "CM-2026-014", actor="陈澄", role="订单统筹经理"
        )
    except InvalidTransitionError:
        pass
    else:
        raise AssertionError("second approval must fail")


def test_reset_is_scoped_to_known_dataset(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    try:
        service.reset_demo("wrong-dataset")
    except ValueError:
        pass
    else:
        raise AssertionError("unbounded reset must fail")


class _InventingPlanner:
    async def propose(self, context, candidates, trace):
        trace("planner.response", "COMPLETED", "test response", {"invented": True})
        return ManifestDraftResult(
            paths=(PlannedPath("InventedByModel", "unsupported"),),
            planner_profile="test/inventing",
        )


class _OmittingPlanner:
    async def propose(self, context, candidates, trace):
        candidate = candidates[0]
        return ManifestDraftResult(
            paths=(PlannedPath(candidate.definition, "only one"),),
            planner_profile="test/omitting",
        )


class _AllMatchedSkillPathsPlanner:
    def __init__(self) -> None:
        self.candidates = ()

    async def propose(self, context, candidates, trace):
        self.candidates = candidates
        return ManifestDraftResult(
            paths=tuple(
                PlannedPath(candidate.definition, f"reason for {candidate.definition}")
                for candidate in candidates
            ),
            planner_profile="test/all-matched-skill-paths",
        )


class _InventingPathAgent:
    profile = "test/inventing-path-option"

    async def generate(self, context, trace):
        return PathAgentResult(
            summary="invented option",
            options=(ProposedOption(
                id="ALT-C", title="invented", description="unsupported",
                benefits=(), risks=(), assumptions=(),
            ),),
            recommended_option_ids=("ALT-C",),
            recommendation_rationale="unsupported",
            evidence_gaps=(),
            role_reports=tuple(
                RoleReport(
                    role=item["role"], dimension=item["dimension"],
                    report=f"{item['sentence_prefix']}A 与 B 的比较属于不受支持的测试输出。",
                )
                for item in context.required_role_reports
            ),
            adapter_profile=self.profile,
        )


def test_skill_declares_three_candidates_and_manifest_supports_all_paths(tmp_path: Path) -> None:
    planner = _AllMatchedSkillPathsPlanner()
    service = CaseService(CaseRepository(tmp_path / "test.db"), planner=planner)
    service.ensure_demo_data()

    case = orchestrate(service)

    expected_definitions = ["MaterialSubstitution", "SupplyExpediting", "OrderSplit"]
    assert [candidate.definition for candidate in planner.candidates] == expected_definitions
    assert [path.definition for path in case.manifest.paths] == expected_definitions
    assert set(case.manifest.capability_snapshots) == {"PATH-01", "PATH-02", "PATH-03"}
    assert {ref.split("@", 1)[0] for ref in case.manifest.skill_refs} == {
        "shortage-response-planning",
        "material-substitution-analysis",
        "material-substitution-engineering-review",
        "material-substitution-master-planning-review",
        "material-substitution-supply-manager-review",
        "supply-expediting-analysis",
        "order-split-analysis",
    }

    approved = service.approve_manifest(
        "CM-2026-014", actor="陈澄", role="订单统筹经理"
    )
    assert [attempt["definition"] for attempt in approved.path_attempts] == expected_definitions
    assert [attempt["title"] for attempt in approved.path_attempts] == [
        "物料替代", "供应提拉", "订单拆分"
    ]
    assert {node.path_id for node in approved.commitment_nodes} == {"PATH-01", "PATH-02", "PATH-03"}
    assert {node.id for node in approved.commitment_nodes if node.path_id == "PATH-02"} == {
        "EXPEDITE-SUPPLY", "EXPEDITE-DELIVERY"
    }
    assert {node.id for node in approved.commitment_nodes if node.path_id == "PATH-03"} == {
        "SPLIT-PLAN", "SPLIT-CUSTOMER"
    }
    expediting_reports = {
        (item["role"], item["role_report"]["dimension"])
        for item in case.manifest.capability_snapshots["PATH-02"]["compiled_policy"]["commitments"]
    }
    assert expediting_reports == {
        ("采购与供应协同", "供应商产能与供应日期"),
        ("物流", "运输与到货日期"),
    }
    split_reports = {
        (item["role"], item["role_report"]["dimension"])
        for item in case.manifest.capability_snapshots["PATH-03"]["compiled_policy"]["commitments"]
    }
    assert split_reports == {
        ("主计划", "可用数量与交付批次"),
        ("供应经理", "客户接受度与剩余承诺"),
    }
    split_capabilities = service.get_case_capabilities("CM-2026-014", "PATH-03")
    assert {item["id"] for item in split_capabilities["snapshot"]["policies"]} == {"POL-ORDER-SPLIT-1"}


def test_multi_path_exploration_finishes_only_after_every_solution_revision(tmp_path: Path) -> None:
    service = CaseService(
        CaseRepository(tmp_path / "multi-path.db"),
        planner=_AllMatchedSkillPathsPlanner(),
        path_agent=DeterministicPathAgentAdapter(),
    )
    service.ensure_demo_data()
    orchestrate(service)
    service.approve_manifest("CM-2026-014", actor="陈澄", role="订单统筹经理")

    for path_id in ("PATH-01", "PATH-02"):
        case = asyncio.run(service.execute_path(
            "CM-2026-014", path_id, actor="陈澄", role="订单统筹经理"
        ))
        attempt = next(item for item in case.path_attempts if item["path_id"] == path_id)
        expected_roles = {
            item["role"]
            for item in case.manifest.capability_snapshots[path_id]["compiled_policy"]["commitments"]
        }
        assert {item["role"] for item in attempt["solution_revision"]["role_reports"]} == expected_roles
        assert case.phase is OrchestrationPhase.PATH_EXPLORATION
        assert service.get_inbox("主计划") == []

    case = asyncio.run(service.execute_path(
        "CM-2026-014", "PATH-03", actor="陈澄", role="订单统筹经理"
    ))
    split_attempt = next(item for item in case.path_attempts if item["path_id"] == "PATH-03")
    assert {item["role"] for item in split_attempt["solution_revision"]["role_reports"]} == {
        "主计划", "供应经理"
    }
    assert case.phase is OrchestrationPhase.PROFESSIONAL_COMMITMENT
    assert service.get_inbox("主计划")


def test_synthesis_waits_for_every_path_dag_and_includes_success_and_failure(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    case = orchestrate(service)
    selected_ids = [path.id for path in case.manifest.paths[:2]]
    service.approve_manifest(
        "CM-2026-014", selected_ids, actor="陈澄", role="订单统筹经理"
    )
    for path_id in selected_ids:
        asyncio.run(service.execute_path(
            "CM-2026-014", path_id, actor="陈澄", role="订单统筹经理"
        ))

    case = service.get_case("CM-2026-014")
    first_pending = next(
        node for node in case.commitment_nodes
        if node.path_id == selected_ids[1] and node.status is NodeStatus.PENDING
    )
    case = service.decide_commitment(
        case.id,
        selected_ids[1],
        first_pending.id,
        decision=CommitmentDecision.REJECT,
        actor="审批人",
        role=first_pending.role,
    )
    assert case.phase is OrchestrationPhase.PROFESSIONAL_COMMITMENT

    while case.phase is OrchestrationPhase.PROFESSIONAL_COMMITMENT:
        pending = next(
            node for node in case.commitment_nodes
            if node.path_id == selected_ids[0] and node.status is NodeStatus.PENDING
        )
        case = service.decide_commitment(
            case.id,
            selected_ids[0],
            pending.id,
            decision=CommitmentDecision.APPROVE,
            actor="审批人",
            role=pending.role,
        )

    assert case.phase is OrchestrationPhase.FINAL_REVIEW
    assert {attempt["outcome"] for attempt in case.path_attempts} == {"SUCCEEDED", "REJECTED"}
    report_case = asyncio.run(service.synthesize_case(
        case.id, actor="陈澄", role="订单统筹经理"
    ))
    report = report_case.synthesis_report
    assert {item["status"] for item in report["path_assessments"]} == {"SUCCEEDED", "FAILED"}
    assert "1 条审批通过，1 条审批失败" in report["summary"]
    runs = service.get_agent_runs(
        case.id, actor="陈澄", role="订单统筹经理", agent_type="synthesis"
    )
    assert runs[0]["status"] == "SUCCEEDED"
    assert any(event["step"] == "synthesis.compose" for event in runs[0]["events"])


def test_openai_synthesis_repairs_paraphrased_artifact_refs(tmp_path: Path) -> None:
    observed: dict[str, object] = {"attempts": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["attempts"] = int(observed["attempts"]) + 1
        payload = json.loads(request.content)
        observed["payload"] = payload
        supporting_refs = (
            ["PATH-01 方案修订 v1", "承诺均已通过"]
            if observed["attempts"] == 1
            else ["PATH-01/solution-revision/1", "PATH-01/commitment/SUPPLY"]
        )
        content = {
            "summary": "已汇总一条审批成功的物料替代路径。",
            "path_assessments": [{
                "path_id": "PATH-01",
                "status": "SUCCEEDED",
                "conclusion": "物料替代路径的全部责任节点已经由对应人员批准。",
                "supporting_refs": supporting_refs,
                "risks": ["仍需由 Case Owner 决定是否关闭 Case"],
            }],
            "cross_path_findings": ["本轮仅探索一条 Path，无跨 Path 冲突。"],
            "remaining_risks": ["Agent 汇总不构成最终业务决定。"],
            "recommended_owner_action": "KEEP_OPEN",
            "decision_brief": "请 Case Owner 审查已批准结果并作出最终决定。",
        }
        return httpx.Response(200, json={
            "id": f"synthesis-{observed['attempts']}",
            "object": "chat.completion",
            "created": 1,
            "model": "vendor-model-42",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(content, ensure_ascii=False)},
            }],
            "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200},
        })

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = CaseService(
                CaseRepository(tmp_path / "synthesis-repair.db"),
                planner=DeterministicPlannerAdapter(),
                path_agent=DeterministicPathAgentAdapter(),
                synthesis_agent=OpenAICompatibleSynthesisAgentAdapter(
                    "synthesis-secret",
                    model="vendor-model-42",
                    base_url="https://gateway.example/v1",
                    http_client=client,
                ),
            )
            service.ensure_demo_data()
            await service.orchestrate_case("CM-2026-014", actor="陈澄", role="订单统筹经理")
            service.approve_manifest(
                "CM-2026-014", ["PATH-01"], actor="陈澄", role="订单统筹经理"
            )
            await service.execute_path(
                "CM-2026-014", "PATH-01", actor="陈澄", role="订单统筹经理"
            )
            case = service.get_case("CM-2026-014")
            while case.phase is OrchestrationPhase.PROFESSIONAL_COMMITMENT:
                pending = next(node for node in case.commitment_nodes if node.status is NodeStatus.PENDING)
                case = service.decide_commitment(
                    case.id, pending.path_id, pending.id,
                    decision=CommitmentDecision.APPROVE, actor="审批人", role=pending.role,
                )
            return await service.synthesize_case(
                case.id, actor="陈澄", role="订单统筹经理"
            )

    case = asyncio.run(scenario())
    assert observed["attempts"] == 2
    assert case.synthesis_report["path_assessments"][0]["supporting_refs"] == [
        "PATH-01/solution-revision/1", "PATH-01/commitment/SUPPLY"
    ]
    request_payload = observed["payload"]
    request_context = json.loads(request_payload["messages"][1]["content"])
    assert request_context["path_results"][0]["authorized_supporting_refs"] == [
        "PATH-01/solution-revision/1",
        "PATH-01/commitment/SUPPLY",
        "PATH-01/commitment/TECH",
        "PATH-01/commitment/CUSTOMER",
    ]
    assert "READY means that its responsible human has already approved it" in request_payload["messages"][0]["content"]
    assert "synthesis-secret" not in json.dumps(request_payload)


def test_owner_can_close_keep_open_or_modify_after_synthesis(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    approve_and_execute_path(service)
    case = service.get_case("CM-2026-014")
    while case.phase is OrchestrationPhase.PROFESSIONAL_COMMITMENT:
        pending = next(node for node in case.commitment_nodes if node.status is NodeStatus.PENDING)
        case = service.decide_commitment(
            case.id,
            pending.path_id,
            pending.id,
            decision=CommitmentDecision.APPROVE,
            actor="审批人",
            role=pending.role,
        )
    asyncio.run(service.synthesize_case(case.id, actor="陈澄", role="订单统筹经理"))

    kept = service.decide_case(
        case.id,
        action=OwnerDecisionAction.KEEP_OPEN,
        actor="陈澄",
        role="订单统筹经理",
    )
    assert kept.status is CaseStatus.OPEN
    assert kept.phase is OrchestrationPhase.FINAL_REVIEW

    try:
        service.decide_case(
            case.id,
            action=OwnerDecisionAction.MODIFY,
            actor="陈澄",
            role="订单统筹经理",
        )
    except InvalidTransitionError as exc:
        assert "guidance" in str(exc)
    else:
        raise AssertionError("MODIFY must require explicit Case Owner guidance")
    assert service.get_case(case.id).phase is OrchestrationPhase.FINAL_REVIEW

    guidance = "保留物料替代 Path，并重点比较无需客户重新认证的交付拆分方案。"
    modified = service.decide_case(
        case.id,
        action=OwnerDecisionAction.MODIFY,
        actor="陈澄",
        role="订单统筹经理",
        guidance=guidance,
    )
    assert modified.status is CaseStatus.OPEN
    assert modified.phase is OrchestrationPhase.INTAKE
    assert modified.manifest is None
    assert modified.synthesis_report is None
    assert modified.commitment_nodes == []
    assert modified.owner_decision["action"] == "MODIFY"
    assert modified.owner_decision["guidance"] == guidance
    assert modified.owner_decision["previous_human_proposal_snapshot"]["revision"] == 1
    assert modified.human_proposal == {
        "revision": 2,
        "author": "陈澄",
        "role": "订单统筹经理",
        "content": guidance,
    }

    asyncio.run(service.orchestrate_case(
        case.id, actor="陈澄", role="订单统筹经理"
    ))
    rerun = service.get_agent_runs(
        case.id, actor="陈澄", role="订单统筹经理", agent_type="orchestrator"
    )[0]
    planner_input = next(event for event in rerun["events"] if event["step"] == "planner.input")
    assert planner_input["details"]["context"]["human_proposal"]["content"] == guidance

    close_root = tmp_path / "close"
    close_root.mkdir()
    close_service = make_service(close_root)
    approve_and_execute_path(close_service)
    close_case = close_service.get_case("CM-2026-014")
    while close_case.phase is OrchestrationPhase.PROFESSIONAL_COMMITMENT:
        pending = next(node for node in close_case.commitment_nodes if node.status is NodeStatus.PENDING)
        close_case = close_service.decide_commitment(
            close_case.id, pending.path_id, pending.id,
            decision=CommitmentDecision.APPROVE, actor="审批人", role=pending.role,
        )
    asyncio.run(close_service.synthesize_case(
        close_case.id, actor="陈澄", role="订单统筹经理"
    ))
    closed = close_service.decide_case(
        close_case.id,
        action=OwnerDecisionAction.CLOSE,
        actor="陈澄",
        role="订单统筹经理",
    )
    assert closed.status is CaseStatus.CLOSED


def test_reducing_skill_declared_paths_reduces_manifest_candidates(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    shutil.copytree(DEFAULT_BUILTIN_ROOT, builtin)
    paths_file = builtin / "skills" / "shortage-response-planning" / "paths.json"
    payload = json.loads(paths_file.read_text())
    payload["paths"] = [item for item in payload["paths"] if item["id"] == "MaterialSubstitution"]
    paths_file.write_text(json.dumps(payload))
    planner = _AllMatchedSkillPathsPlanner()
    registry = CapabilityRegistry.from_directories(builtin, None)
    service = CaseService(CaseRepository(tmp_path / "test.db"), capabilities=registry, planner=planner)
    service.ensure_demo_data()

    case = orchestrate(service)

    assert [candidate.definition for candidate in planner.candidates] == ["MaterialSubstitution"]
    assert [path.definition for path in case.manifest.paths] == ["MaterialSubstitution"]


def test_declared_path_without_execution_skill_fails_closed(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    shutil.copytree(DEFAULT_BUILTIN_ROOT, builtin)
    bindings_file = builtin / "skill-bindings.json"
    payload = json.loads(bindings_file.read_text())
    del payload["bindings"]["order-split-analysis"]
    bindings_file.write_text(json.dumps(payload))
    registry = CapabilityRegistry.from_directories(builtin, None)
    service = CaseService(CaseRepository(tmp_path / "test.db"), capabilities=registry)
    service.ensure_demo_data()

    try:
        orchestrate(service)
    except OrchestrationError as exc:
        assert "OrderSplit" in str(exc)
        assert "execution Skill" in str(exc)
    else:
        raise AssertionError("Every Skill-declared Path must have an execution Skill")

    case = service.get_case("CM-2026-014")
    assert case.phase is OrchestrationPhase.INTAKE
    assert case.manifest is None


def test_planner_cannot_invent_path_or_mutate_case(tmp_path: Path) -> None:
    repository = CaseRepository(tmp_path / "test.db")
    service = CaseService(repository, planner=_InventingPlanner())
    service.ensure_demo_data()

    try:
        orchestrate(service)
    except PlannerOutputError:
        pass
    else:
        raise AssertionError("untrusted planner Path must fail")

    unchanged = service.get_case("CM-2026-014")
    assert unchanged.phase is OrchestrationPhase.INTAKE
    assert unchanged.manifest is None
    with repository._connect() as connection:
        assert connection.execute("SELECT count(*) FROM domain_events").fetchone()[0] == 0


def test_planner_cannot_omit_skill_declared_paths(tmp_path: Path) -> None:
    service = CaseService(CaseRepository(tmp_path / "test.db"), planner=_OmittingPlanner())
    service.ensure_demo_data()

    try:
        orchestrate(service)
    except PlannerOutputError as exc:
        assert "missing=" in str(exc)
    else:
        raise AssertionError("Planner must return every Path declared by the matched Skill")

    unchanged = service.get_case("CM-2026-014")
    assert unchanged.phase is OrchestrationPhase.INTAKE
    assert unchanged.manifest is None


def test_openai_compatible_adapter_accepts_custom_provider_configuration() -> None:
    observed = {}
    trace_events = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed["api_key"] = request.headers["x-api-key"]
        observed["authorization"] = request.headers.get("authorization")
        observed["url"] = str(request.url)
        observed["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "response-planner-1",
                "object": "chat.completion",
                "created": 1,
                "model": "vendor-model-42",
                "choices": [
                    {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps({
                        "paths": [
                            {"definition": "MaterialSubstitution", "rationale": "物料缺口与候选能力匹配"},
                            {"definition": "OrderSplit", "rationale": "可用数量支持分批交付探索"}
                        ]
                    })}}
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = OpenAICompatiblePlannerAdapter(
                "secret-key",
                model="vendor-model-42",
                base_url="https://gateway.example/v1",
                api_key_header="x-api-key",
                api_key_prefix="",
                http_client=client,
            )
            from agentic_cm.orchestrator import PlanningCandidate, PlanningContext
            return await adapter.propose(
                PlanningContext("CM-1", 1, "延期", "关键物料延期", {}, {}, None),
                (PlanningCandidate(
                    "MaterialSubstitution", "物料替代", "desc",
                    ("POL-1",), ("skill-1",), (), ("SUPPLY",),
                    ({"id": "skill-1", "description": "desc", "instructions_markdown": "guide"},),
                ), PlanningCandidate(
                    "OrderSplit", "订单拆分", "desc",
                    ("POL-2",), ("skill-1",), (), ("SPLIT",),
                    ({"id": "skill-1", "description": "desc", "instructions_markdown": "guide"},),
                )),
                lambda *args, **kwargs: trace_events.append((args, kwargs)),
            )

    result = asyncio.run(run())
    assert [path.definition for path in result.paths] == ["MaterialSubstitution", "OrderSplit"]
    assert result.planner_profile == "openai-compatible/vendor-model-42"
    assert observed["api_key"] == "secret-key"
    assert observed["authorization"] is None
    assert observed["url"] == "https://gateway.example/v1/chat/completions"
    assert observed["payload"]["response_format"] == {"type": "json_object"}
    assert "secret-key" not in json.dumps(trace_events)
    request_trace = next(args for args, _ in trace_events if args[0] == "planner.request")
    assert request_trace[3]["authentication"] == {
        "header": "x-api-key",
        "credential_present": True,
        "credential_value_logged": False,
    }


def test_openai_compatible_adapter_repairs_pydantic_schema_failure_once() -> None:
    attempts = 0
    trace_events = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        content = {
            "paths": [{"definition": "MaterialSubstitution", "rationale": "候选能力匹配"}],
        }
        if attempts == 1:
            content["unexpected"] = True
        return httpx.Response(200, json={
            "id": f"response-{attempts}",
            "object": "chat.completion",
            "created": attempts,
            "model": "vendor-model-42",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(content)},
            }],
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            adapter = OpenAICompatiblePlannerAdapter(
                "secret-key",
                model="vendor-model-42",
                base_url="https://gateway.example/v1",
                http_client=http_client,
            )
            from agentic_cm.orchestrator import PlanningCandidate, PlanningContext
            return await adapter.propose(
                PlanningContext("CM-1", 1, "延期", "关键物料延期", {}, {}, None),
                (PlanningCandidate(
                    "MaterialSubstitution", "物料替代", "desc",
                    ("POL-1",), ("skill-1",), (), ("SUPPLY",),
                    ({"id": "skill-1", "description": "desc", "instructions_markdown": "guide"},),
                ),),
                lambda *args, **kwargs: trace_events.append((args, kwargs)),
            )

    result = asyncio.run(run())
    assert attempts == 2
    assert result.paths[0].definition == "MaterialSubstitution"
    assert [args[0] for args, _ in trace_events].count("planner.response_validation") == 1
    assert [args[0] for args, _ in trace_events].count("planner.repair_request") == 1


def test_openai_compatible_planner_retries_one_transient_connection_failure() -> None:
    attempts = 0
    trace_events = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("temporary timeout", request=request)
        return httpx.Response(200, json={
            "id": "response-after-retry",
            "object": "chat.completion",
            "created": 2,
            "model": "vendor-model-42",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps({
                    "paths": [{
                        "definition": "SupplyExpediting",
                        "rationale": "Owner 要求重点探索供应提拉，当前缺料风险与该路径相关。",
                    }],
                }, ensure_ascii=False)},
            }],
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            adapter = OpenAICompatiblePlannerAdapter(
                "secret-key",
                model="vendor-model-42",
                base_url="https://gateway.example/v1",
                http_client=http_client,
            )
            from agentic_cm.orchestrator import PlanningCandidate, PlanningContext
            return await adapter.propose(
                PlanningContext(
                    "CM-1", 2, "延期", "关键物料延期", {}, {},
                    {"revision": 2, "author": "陈澄", "role": "订单统筹经理", "content": "探索一下提拉看看"},
                ),
                (PlanningCandidate(
                    "SupplyExpediting", "供应提拉", "desc",
                    ("POL-1",), ("skill-1",), (), ("EXPEDITE-SUPPLY",),
                    ({"id": "skill-1", "description": "desc", "instructions_markdown": "guide"},),
                ),),
                lambda *args, **kwargs: trace_events.append((args, kwargs)),
            )

    result = asyncio.run(run())
    assert attempts == 2
    assert result.paths[0].definition == "SupplyExpediting"
    assert [args[0] for args, _ in trace_events].count("planner.retry_request") == 1
    assert [args[0] for args, _ in trace_events].count("planner.repair_request") == 0
    failed = next(args for args, _ in trace_events if args[0] == "planner.request" and args[1] == "FAILED")
    assert failed[3]["will_retry"] is True


def test_orchestrator_trace_persists_each_governed_step(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    orchestrate(service)

    runs = service.get_agent_runs(
        "CM-2026-014",
        actor="陈澄",
        role="订单统筹经理",
        agent_type="orchestrator",
    )

    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "SUCCEEDED"
    assert run["adapter_profile"] == "deterministic/v1"
    steps = [event["step"] for event in run["events"]]
    assert steps == [
        "run.started",
        "case.eligibility",
        "case.eligibility",
        "paths.discovery",
        "capabilities.resolve",
        "capabilities.resolve",
        "capabilities.resolve",
        "planner.input",
        "planner.request",
        "planner.response",
        "planner.output_validation",
        "manifest.compose",
        "run.completed",
    ]
    request_event = next(event for event in run["events"] if event["step"] == "planner.request")
    assert request_event["details"]["case"]["case_id"] == "CM-2026-014"
    assert [item["definition"] for item in request_event["details"]["candidates"]] == [
        "MaterialSubstitution", "SupplyExpediting", "OrderSplit"
    ]


def test_failed_orchestrator_trace_is_kept_without_business_mutation(tmp_path: Path) -> None:
    repository = CaseRepository(tmp_path / "test.db")
    service = CaseService(repository, planner=_InventingPlanner())
    service.ensure_demo_data()

    try:
        orchestrate(service)
    except PlannerOutputError:
        pass
    else:
        raise AssertionError("invented path must fail")

    runs = service.get_agent_runs(
        "CM-2026-014", actor="陈澄", role="订单统筹经理", agent_type="orchestrator"
    )
    assert runs[0]["status"] == "FAILED"
    assert runs[0]["error_type"] == "PlannerOutputError"
    assert runs[0]["events"][-1]["step"] == "run.failed"
    assert repository.list_events("CM-2026-014") == []


def test_agent_trace_is_owner_only(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    orchestrate(service)

    try:
        service.get_agent_runs(
            "CM-2026-014", actor="王淼", role="主计划", agent_type="orchestrator"
        )
    except AuthorizationError:
        pass
    else:
        raise AssertionError("Agent trace must remain owner-only")


def test_path_agent_builds_solution_revision_from_frozen_manifest(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    case = approve_and_execute_path(service)

    attempt = case.path_attempts[0]
    revision = attempt["solution_revision"]
    assert revision["path_definition"] == "MaterialSubstitution"
    assert revision["manifest_ref"]["id"] == "MAN-CM-2026-014-1"
    assert [option["id"] for option in revision["options"]] == ["A", "B"]
    assert {item["role"] for item in revision["role_reports"]} == {"研发", "主计划", "供应经理"}
    assert all("A" in item["report"] and "B" in item["report"] for item in revision["role_reports"])
    assert revision["required_commitment_ids"] == ["SUPPLY", "TECH", "CUSTOMER"]
    assert revision["generated_by"] == "deterministic-path/v1"
    assert case.phase is OrchestrationPhase.PROFESSIONAL_COMMITMENT
    assert case.commitment_nodes[0].status is NodeStatus.PENDING
    assert service.repository.list_events("CM-2026-014")[-1]["event_type"] == "solution_revision.proposed"


def test_repository_normalizes_legacy_numeric_solution_revision(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    orchestrate(service)
    service.approve_manifest(
        "CM-2026-014", ["PATH-01"], actor="陈澄", role="订单统筹经理"
    )
    with service.repository._connect() as connection:
        row = connection.execute(
            "SELECT payload FROM cases WHERE id = ?", ("CM-2026-014",)
        ).fetchone()
        payload = json.loads(row["payload"])
        payload["path_attempts"][0]["solution_revision"] = 1
        payload["path_attempt"]["solution_revision"] = 1
        connection.execute(
            "UPDATE cases SET payload = ? WHERE id = ?",
            (json.dumps(payload, ensure_ascii=False), "CM-2026-014"),
        )

    reloaded = service.get_case("CM-2026-014")

    assert reloaded.path_attempts[0]["solution_revision"] is None
    assert reloaded.path_attempt["solution_revision"] is None


def test_path_agent_trace_audits_manifest_assembly_and_persistence(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    approve_and_execute_path(service)

    runs = service.get_agent_runs(
        "CM-2026-014", actor="陈澄", role="订单统筹经理", agent_type="path"
    )

    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "SUCCEEDED"
    assert run["adapter_profile"] == "deterministic-path/v1"
    assert [event["step"] for event in run["events"]] == [
        "run.started",
        "path.eligibility",
        "path.eligibility",
        "agent.assemble",
        "tools.query",
        "agent.input",
        "model.request",
        "model.response",
        "agent.output_validation",
        "solution_revision.compose",
        "run.completed",
    ]
    assembly = next(event for event in run["events"] if event["step"] == "agent.assemble")
    assert assembly["details"]["manifest_ref"]["id"] == "MAN-CM-2026-014-1"
    assert {item["id"] for item in assembly["details"]["execution_skills"]} == {
        "material-substitution-analysis",
        "material-substitution-engineering-review",
        "material-substitution-master-planning-review",
        "material-substitution-supply-manager-review",
    }
    assert assembly["details"]["authorized_options"] == [
        {
            "id": "A", "material_id": "MCU-X7A", "title": "物料 A · MCU-X7A",
            "description": "与 MCU-X7 封装和引脚兼容、无需固件改动的优先替代候选。",
        },
        {
            "id": "B", "material_id": "MCU-X7B", "title": "物料 B · MCU-X7B",
            "description": "可覆盖完整缺口但需要固件配置与客户 AVL 评审的备选替代候选。",
        },
    ]
    assert assembly["details"]["tool_ids"] == [
        "mock.customer-acceptance.lookup",
        "mock.material-master.lookup",
        "mock.supply-snapshot.lookup",
    ]
    tool_trace = next(event for event in run["events"] if event["step"] == "tools.query")
    assert len(tool_trace["details"]["results"]) == 6
    assert {item["input"]["option_id"] for item in tool_trace["details"]["results"]} == {"A", "B"}
    assert assembly["details"]["mandatory_commitment_ids"] == ["SUPPLY", "TECH", "CUSTOMER"]


def test_path_agent_cannot_invent_manifest_unauthorized_option(tmp_path: Path) -> None:
    repository = CaseRepository(tmp_path / "inventing-path.db")
    service = CaseService(
        repository,
        planner=DeterministicPlannerAdapter(),
        path_agent=_InventingPathAgent(),
    )
    service.ensure_demo_data()
    orchestrate(service)
    service.approve_manifest(
        "CM-2026-014", ["PATH-01"], actor="陈澄", role="订单统筹经理"
    )

    try:
        asyncio.run(service.execute_path(
            "CM-2026-014", "PATH-01", actor="陈澄", role="订单统筹经理"
        ))
    except PathAgentOutputError as exc:
        assert "unknown=['ALT-C']" in str(exc)
    else:
        raise AssertionError("Path Agent must not invent an unauthorized option")

    unchanged = service.get_case("CM-2026-014")
    assert unchanged.path_attempts[0]["solution_revision"] is None
    assert [event["event_type"] for event in repository.list_events("CM-2026-014")] == [
        "manifest.proposed", "manifest.approved"
    ]
    runs = service.get_agent_runs(
        "CM-2026-014", actor="陈澄", role="订单统筹经理", agent_type="path"
    )
    assert runs[0]["status"] == "FAILED"


def test_openai_compatible_path_agent_uses_manifest_assembled_context(tmp_path: Path) -> None:
    observed = {"attempts": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["attempts"] += 1
        observed["api_key"] = request.headers["x-api-key"]
        observed["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "response-path-1",
            "object": "chat.completion",
            "created": 1,
            "model": "vendor-model-42",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps({
                "summary": "English summary" if observed["attempts"] == 1 else "比较两个替代候选，所有结论等待责任角色确认。",
                "options": [{
                    "id": "A",
                    "title": "物料 A · MCU-X7A",
                    "description": "保留为替代候选。",
                    "benefits": ["可并行开展核验"],
                    "risks": ["供应与技术状态未确认"],
                    "assumptions": ["不代表交付承诺"],
                }, {
                    "id": "B",
                    "title": "物料 B · MCU-X7B",
                    "description": "保留为第二替代候选。",
                    "benefits": ["降低单一候选失败风险"],
                    "risks": ["客户接受度未确认"],
                    "assumptions": ["不代表认证通过"],
                }],
                "recommendation": {"option_ids": [], "rationale": "证据不足，不排序。"},
                "evidence_gaps": ["供应、技术与客户接受度确认"],
                "role_reports": [
                    {
                        "role": "研发",
                        "dimension": "技术可行性",
                        "report": "研发维度：A 无需固件改动而 B 需要配置与回归测试，两者均须由研发完成剩余验证后确认。",
                    },
                    {
                        "role": "主计划",
                        "dimension": "供应与交付可行性",
                        "report": "主计划维度：A 需要分段补足缺口而 B 的模拟数量可覆盖缺口，两者库存和交期均须主计划确认。",
                    },
                    {
                        "role": "供应经理",
                        "dimension": "客户与商务接受度",
                        "report": "供应经理维度：A 需要客户偏差放行而 B 需要正式 AVL 认证，两者均须取得客户书面确认。",
                    },
                ],
            }, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 121, "total_tokens": 321},
        })

    # A file-backed DB is required because each repository call opens a connection.
    async def run_file_backed(tmp_path: Path):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = OpenAICompatiblePathAgentAdapter(
                "path-secret", model="vendor-model-42", base_url="https://gateway.example/v1",
                api_key_header="x-api-key", api_key_prefix="", http_client=client,
            )
            service = CaseService(
                CaseRepository(tmp_path / "openai-path.db"),
                planner=DeterministicPlannerAdapter(), path_agent=adapter,
            )
            service.ensure_demo_data()
            await service.orchestrate_case("CM-2026-014", actor="陈澄", role="订单统筹经理")
            service.approve_manifest("CM-2026-014", ["PATH-01"], actor="陈澄", role="订单统筹经理")
            return await service.execute_path(
                "CM-2026-014", "PATH-01", actor="陈澄", role="订单统筹经理"
            )

    case = asyncio.run(run_file_backed(tmp_path))
    revision = case.path_attempts[0]["solution_revision"]
    assert observed["attempts"] == 2
    assert revision["generated_by"] == "openai-compatible-path/vendor-model-42"
    assert observed["api_key"] == "path-secret"
    assert observed["payload"]["max_tokens"] == 6000
    request_context = json.loads(observed["payload"]["messages"][1]["content"])
    assert request_context["manifest_ref"]["id"] == "MAN-CM-2026-014-1"
    assert request_context["execution_skills"][0]["id"] == "material-substitution-analysis"
    assert request_context["compiled_policy"]["commitments"][0]["id"] == "SUPPLY"
    assert request_context["authorized_option_ids"] == ["A", "B"]
    assert len(request_context["tool_results"]) == 6
    assert {item["role"] for item in request_context["required_role_reports"]} == {
        "研发", "主计划", "供应经理"
    }
    assert "path-secret" not in json.dumps(observed["payload"])


def test_supply_expediting_role_reports_are_assembled_from_frozen_policy(tmp_path: Path) -> None:
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "response-expediting-policy-reports",
            "object": "chat.completion",
            "created": 1,
            "model": "vendor-model-42",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps({
                    "summary": "供应提拉方案等待采购与物流责任角色确认。",
                    "options": [{
                        "id": "EXPEDITE-OPTION-1",
                        "title": "供应与运输联合提拉",
                        "description": "先核验供应商产能，再评估运输提速。",
                        "benefits": ["形成分阶段核验方案"],
                        "risks": ["产能与到货日期尚未确认"],
                        "assumptions": ["责任角色可提供当前证据"],
                    }],
                    "recommendation": {
                        "option_ids": ["EXPEDITE-OPTION-1"],
                        "rationale": "该选项覆盖供应与运输两个依赖环节。",
                    },
                    "evidence_gaps": ["供应商产能和运输时效仍待确认"],
                    "role_reports": [{
                        "role": "采购与供应协同",
                        "dimension": "供应商产能与供应日期",
                        "report": "采购与供应协同维度：供应商产能与最早供应日期仍须责任角色核验后确认。",
                    }, {
                        "role": "物流",
                        "dimension": "运输与到货日期",
                        "report": "物流维度：运输方式与预计到货日期仍须物流责任角色核验后确认。",
                    }],
                }, ensure_ascii=False)},
            }],
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = CaseService(
                CaseRepository(tmp_path / "expediting-policy-reports.db"),
                planner=DeterministicPlannerAdapter(),
                path_agent=OpenAICompatiblePathAgentAdapter(
                    "secret", model="vendor-model-42", base_url="https://gateway.example/v1",
                    http_client=client,
                ),
            )
            service.ensure_demo_data()
            await service.orchestrate_case("CM-2026-014", actor="陈澄", role="订单统筹经理")
            case = service.get_case("CM-2026-014")
            expediting_path = next(
                path for path in case.manifest.paths if path.definition == "SupplyExpediting"
            )
            service.approve_manifest(
                case.id, [expediting_path.id], actor="陈澄", role="订单统筹经理"
            )
            return await service.execute_path(
                case.id, expediting_path.id, actor="陈澄", role="订单统筹经理"
            )

    case = asyncio.run(run())
    context = json.loads(observed["payload"]["messages"][1]["content"])
    assert context["required_role_reports"] == [{
        "role": "采购与供应协同",
        "dimension": "供应商产能与供应日期",
        "sentence_prefix": "采购与供应协同维度：",
    }, {
        "role": "物流",
        "dimension": "运输与到货日期",
        "sentence_prefix": "物流维度：",
    }]
    revision = case.path_attempts[0]["solution_revision"]
    assert {item["role"] for item in revision["role_reports"]} == {"采购与供应协同", "物流"}


def test_failed_path_agent_trace_is_kept_without_solution_mutation(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    async def run_failure(service: CaseService):
        await service.orchestrate_case("CM-2026-014", actor="陈澄", role="订单统筹经理")
        service.approve_manifest("CM-2026-014", ["PATH-01"], actor="陈澄", role="订单统筹经理")
        await service.execute_path("CM-2026-014", "PATH-01", actor="陈澄", role="订单统筹经理")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = CaseService(
                CaseRepository(tmp_path / "failed-path.db"),
                planner=DeterministicPlannerAdapter(),
                path_agent=OpenAICompatiblePathAgentAdapter(
                    None, model="unavailable-model", base_url="https://gateway.example/v1", http_client=client,
                ),
            )
            service.ensure_demo_data()
            try:
                await run_failure(service)
            except PathAgentExecutionError:
                pass
            else:
                raise AssertionError("upstream Path Agent failure must propagate")
            return service

    service = asyncio.run(scenario())
    unchanged = service.get_case("CM-2026-014")
    assert unchanged.path_attempts[0]["solution_revision"] is None
    assert [event["event_type"] for event in service.repository.list_events("CM-2026-014")] == [
        "manifest.proposed", "manifest.approved"
    ]
    runs = service.get_agent_runs(
        "CM-2026-014", actor="陈澄", role="订单统筹经理", agent_type="path"
    )
    assert runs[0]["status"] == "FAILED"
    assert runs[0]["events"][-1]["step"] == "run.failed"
