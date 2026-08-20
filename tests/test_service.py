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
from agentic_cm.domain import NodeStatus, OrchestrationPhase
from agentic_cm.orchestrator import (
    ManifestDraftResult,
    OpenAICompatiblePlannerAdapter,
    OrchestrationError,
    PlannedPath,
    PlannerOutputError,
)
from agentic_cm.repository import CaseRepository
from agentic_cm.service import CaseService, InvalidTransitionError


def make_service(tmp_path: Path) -> CaseService:
    service = CaseService(CaseRepository(tmp_path / "test.db"))
    service.ensure_demo_data()
    return service


def orchestrate(service: CaseService):
    return asyncio.run(service.orchestrate_case("CM-2026-014"))


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
        "POL-SUBSTITUTION-3@3.2.0", "POL-CUSTOMER-2@2.3.0",
        "POL-EXPEDITING-1@1.2.0", "POL-ORDER-SPLIT-1@1.2.0",
    }
    assert {item["id"] for item in case.manifest.capability_snapshot["compiled_policy"]["commitments"]} == {
        "SUPPLY", "TECH", "CUSTOMER"
    }
    manifest = service.get_case_manifest("CM-2026-014")
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


def test_manifest_approval_routes_parallel_nodes_to_role_inboxes(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    orchestrate(service)
    initial_case = service.get_case("CM-2026-014")
    assert initial_case.human_proposal is not None
    assert initial_case.human_proposal["author"] == initial_case.owner
    assert initial_case.human_proposal["role"] == initial_case.owner_role
    case = service.approve_manifest("CM-2026-014", ["PATH-01"])
    assert case.phase is OrchestrationPhase.PATH_EXPLORATION
    pending = {node.id for node in case.commitment_nodes if node.status is NodeStatus.PENDING}
    assert pending == {"SUPPLY", "TECH"}
    assert {item["node"].id for item in service.get_inbox("主计划")} == {"SUPPLY"}
    assert {item["node"].id for item in service.get_inbox("研发")} == {"TECH"}
    assert [attempt["definition"] for attempt in case.path_attempts] == ["MaterialSubstitution"]
    assert case.commitment_nodes[-1].status is NodeStatus.BLOCKED


def test_role_inbox_approval_makes_node_ready_and_releases_dependents(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    orchestrate(service)
    service.approve_manifest("CM-2026-014", ["PATH-01"])

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
    assert {item["node"].id for item in service.get_inbox("一线经理")} == {"CUSTOMER"}


def test_demo_manifest_freezes_resolved_capabilities(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    orchestrate(service)
    case = service.get_case("CM-2026-014")
    snapshot = case.manifest.capability_snapshot
    assert snapshot is not None
    assert {item["id"] for item in snapshot["policies"]} == {"POL-SUBSTITUTION-3", "POL-CUSTOMER-2"}
    assert {item["id"] for item in snapshot["skills"]} == {
        "material-substitution-analysis", "shortage-response-planning"
    }
    assert [item["id"] for item in snapshot["knowledge"]] == ["KNOW-2025-041"]
    assert all(item["digest"].startswith("sha256:") for item in snapshot["policies"])


def test_local_asset_replaces_builtin_without_editing_builtin(tmp_path: Path) -> None:
    local_skill_dir = tmp_path / "local" / "skills" / "material-substitution-analysis"
    local_skill_dir.mkdir(parents=True)
    source = DEFAULT_BUILTIN_ROOT / "skills" / "material-substitution-analysis" / "SKILL.md"
    local_copy = local_skill_dir / "SKILL.md"
    content = source.read_text().replace("Analyze only the candidate set", "Analyze strictly only the candidate set")
    local_copy.write_text(content)

    registry = CapabilityRegistry.from_directories(DEFAULT_BUILTIN_ROOT, tmp_path / "local")
    resolution = registry.resolve({
        "case_type": "ORDER_DELIVERY_RISK",
        "path_definition": "MaterialSubstitution",
    })

    assert resolution.skills[0].source == "local"
    local_version = resolution.skills[0].version
    frozen_snapshot = resolution.to_snapshot()

    local_copy.write_text(content.replace("Analyze strictly only", "Analyze cautiously only"))
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
                {"id": "REVIEW", "role": "主计划", "node_type": "REVIEW", "reviews": ["supply"], "depends_on": []}
            ]
        },
    }
    (policy_dir / "one.json").write_text(json.dumps(base | {"id": "POL-ONE"}))
    conflicting = base | {
        "id": "POL-TWO",
        "requirements": {
            "commitments": [
                {"id": "REVIEW", "role": "研发", "node_type": "REVIEW", "reviews": ["technical"], "depends_on": []}
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
    service.approve_manifest("CM-2026-014")
    try:
        service.approve_manifest("CM-2026-014")
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
    async def propose(self, context, candidates):
        return ManifestDraftResult(
            paths=(PlannedPath("InventedByModel", "unsupported"),),
            planner_profile="test/inventing",
        )


class _OmittingPlanner:
    async def propose(self, context, candidates):
        candidate = candidates[0]
        return ManifestDraftResult(
            paths=(PlannedPath(candidate.definition, "only one"),),
            planner_profile="test/omitting",
        )


class _AllMatchedSkillPathsPlanner:
    def __init__(self) -> None:
        self.candidates = ()

    async def propose(self, context, candidates):
        self.candidates = candidates
        return ManifestDraftResult(
            paths=tuple(
                PlannedPath(candidate.definition, f"reason for {candidate.definition}")
                for candidate in candidates
            ),
            planner_profile="test/all-matched-skill-paths",
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
        "supply-expediting-analysis",
        "order-split-analysis",
    }

    approved = service.approve_manifest("CM-2026-014")
    assert [attempt["definition"] for attempt in approved.path_attempts] == expected_definitions
    assert {node.path_id for node in approved.commitment_nodes} == {"PATH-01", "PATH-02", "PATH-03"}
    assert {node.id for node in approved.commitment_nodes if node.path_id == "PATH-02"} == {
        "EXPEDITE-SUPPLY", "EXPEDITE-DELIVERY"
    }
    assert {node.id for node in approved.commitment_nodes if node.path_id == "PATH-03"} == {
        "SPLIT-PLAN", "SPLIT-CUSTOMER"
    }
    split_capabilities = service.get_case_capabilities("CM-2026-014", "PATH-03")
    assert {item["id"] for item in split_capabilities["snapshot"]["policies"]} == {"POL-ORDER-SPLIT-1"}


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

    def handler(request: httpx.Request) -> httpx.Response:
        observed["api_key"] = request.headers["x-api-key"]
        observed["url"] = str(request.url)
        observed["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps({
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
                client=client,
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
            )

    result = asyncio.run(run())
    assert [path.definition for path in result.paths] == ["MaterialSubstitution", "OrderSplit"]
    assert result.planner_profile == "openai-compatible/vendor-model-42"
    assert observed["api_key"] == "secret-key"
    assert observed["url"] == "https://gateway.example/v1/chat/completions"
    assert observed["payload"]["response_format"] == {"type": "json_object"}
