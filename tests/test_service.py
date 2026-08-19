import json
from pathlib import Path

from agentic_cm.capabilities import (
    DEFAULT_BUILTIN_ROOT,
    CapabilityConfigurationError,
    CapabilityConflictError,
    CapabilityRegistry,
)
from agentic_cm.domain import NodeStatus, OrchestrationPhase
from agentic_cm.repository import CaseRepository
from agentic_cm.service import CaseService, InvalidTransitionError


def make_service(tmp_path: Path) -> CaseService:
    service = CaseService(CaseRepository(tmp_path / "test.db"))
    service.ensure_demo_data()
    return service


def test_manifest_approval_opens_parallel_nodes(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    initial_case = service.get_case("CM-2026-014")
    assert initial_case.human_proposal is not None
    assert initial_case.human_proposal["author"] == initial_case.owner
    assert initial_case.human_proposal["role"] == initial_case.owner_role
    case = service.approve_manifest("CM-2026-014")
    assert case.phase is OrchestrationPhase.PATH_EXPLORATION
    ready = {node.id for node in case.commitment_nodes if node.status is NodeStatus.READY}
    assert ready == {"SUPPLY", "TECH"}
    assert case.commitment_nodes[-1].status is NodeStatus.BLOCKED


def test_demo_manifest_freezes_resolved_capabilities(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    case = service.get_case("CM-2026-014")
    snapshot = case.manifest.capability_snapshot
    assert snapshot is not None
    assert {item["id"] for item in snapshot["policies"]} == {"POL-SUBSTITUTION-3", "POL-CUSTOMER-2"}
    assert [item["id"] for item in snapshot["skills"]] == ["material-substitution-analysis"]
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
        "organization": "demo-supply-chain",
        "case_type": "ORDER_DELIVERY_RISK",
        "path_definition": "MaterialSubstitution",
    })

    assert resolution.skills[0].source == "local"
    local_version = resolution.skills[0].version
    frozen_snapshot = resolution.to_snapshot()

    local_copy.write_text(content.replace("Analyze strictly only", "Analyze cautiously only"))
    reloaded = CapabilityRegistry.from_directories(DEFAULT_BUILTIN_ROOT, tmp_path / "local")
    assert reloaded.resolve({
        "organization": "demo-supply-chain",
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
        "organization": "demo-supply-chain",
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
        "match": {"path_definition": ["MaterialSubstitution"]},
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
        registry.resolve({"path_definition": "MaterialSubstitution"})
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
        "match": {"path_definition": ["MaterialSubstitution"]},
        "requirements": {"commitments": [], "constraints": {"unused": True}},
    }
    (policy_dir / "arbitrary-name.json").write_text(json.dumps(policy))

    try:
        CapabilityRegistry.from_directories(tmp_path / "builtin", None)
    except CapabilityConfigurationError:
        pass
    else:
        raise AssertionError("initial Policy must reject fields with no runtime consumer")


def test_manifest_cannot_be_approved_twice(tmp_path: Path) -> None:
    service = make_service(tmp_path)
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
