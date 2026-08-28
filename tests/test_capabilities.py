import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from agentic_cm.capabilities import (
    DEFAULT_BUILTIN_ROOT,
    CapabilityConfigurationError,
    CapabilityConflictError,
    CapabilityRegistry,
)
from agentic_cm.domain import AssetRef, Manifest, ManifestPath, ManifestSkillSelection, OrchestrationPhase
from agentic_cm.orchestrator import DeterministicPlannerAdapter
from agentic_cm.repository import CaseRepository
from agentic_cm.service import CaseService, InvalidTransitionError
from conftest import DEMO_CASE_ID, OWNER_ACTOR, OWNER_ROLE, make_service, orchestrate


def _write_skill(root: Path, skill_id: str, description: str = "分析业务证据。") -> Path:
    skill_dir = root / "skills" / skill_id
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill_id}\ndescription: {description}\n---\n\n# {skill_id}\n"
    )
    return skill_dir


def test_manifest_yaml_round_trips_skill_selections() -> None:
    manifest = Manifest(
        id="MAN-1",
        revision=1,
        paths=(
            ManifestPath(
                id="PATH-01",
                definition="MaterialSubstitution",
                rationale="评估替代物料。",
                skill_selections=(
                    ManifestSkillSelection(
                        entrypoint=AssetRef(id="review-bundle", version="1", digest="sha256:a"),
                        reason="需要组合技术与供应评审。",
                        members=(
                            AssetRef(id="engineering-review", version="1", digest="sha256:b"),
                            AssetRef(id="supply-review", version="1", digest="sha256:c"),
                        ),
                    ),
                ),
            ),
        ),
    )
    restored = Manifest.from_yaml(manifest.to_yaml())
    payload = yaml.safe_load(manifest.to_yaml())
    assert "skills" not in payload["paths"][0]
    assert [item.id for item in restored.paths[0].skill_refs()] == [
        "review-bundle", "engineering-review", "supply-review",
    ]


def test_capability_registry_rejects_stale_or_unknown_refs() -> None:
    registry = CapabilityRegistry.from_directories(DEFAULT_BUILTIN_ROOT, None)
    original = registry.resolve_skill_entrypoint("material-substitution-analysis").entrypoint
    for field, value, message in (
        ("id", "missing-skill", "unknown skill"),
        ("version", "changed-version", "version mismatch"),
        ("digest", "sha256:changed", "digest mismatch"),
    ):
        changed = SimpleNamespace(**{**original.__dict__, field: value})
        with pytest.raises(CapabilityConfigurationError, match=message):
            registry.resolve_refs("skill", (changed,))


def test_stale_manifest_policy_fails_closed_without_mutation(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    shutil.copytree(DEFAULT_BUILTIN_ROOT, builtin)
    repository = CaseRepository(tmp_path / "test.db")
    service = CaseService(
        repository,
        capabilities=CapabilityRegistry.from_directories(builtin, None),
        planner=DeterministicPlannerAdapter(),
    )
    service.ensure_demo_data()
    orchestrate(service)
    before_version = service.get_case(DEMO_CASE_ID).version
    policy_path = builtin / "policies" / "substitution-feasibility.json"
    policy = json.loads(policy_path.read_text())
    policy["title"] = f"{policy['title']}（已变更）"
    policy_path.write_text(json.dumps(policy, ensure_ascii=False))
    service.capabilities = CapabilityRegistry.from_directories(builtin, None)

    with pytest.raises(InvalidTransitionError, match="重新生成 Manifest"):
        service.approve_manifest(DEMO_CASE_ID, ["PATH-01"], actor=OWNER_ACTOR, role=OWNER_ROLE)
    unchanged = service.get_case(DEMO_CASE_ID)
    assert unchanged.version == before_version
    assert unchanged.phase is OrchestrationPhase.MANIFEST_REVIEW
    assert unchanged.path_attempts == []


def test_local_asset_replaces_builtin_and_examples_load() -> None:
    repository_root = DEFAULT_BUILTIN_ROOT.parents[1]
    registry = CapabilityRegistry.from_directories(
        DEFAULT_BUILTIN_ROOT, repository_root / "examples" / "local-capabilities"
    )
    resolution = registry.resolve({
        "case_type": "ORDER_DELIVERY_RISK",
        "path_definition": "MaterialSubstitution",
    })
    assert "POL-MY-COMPANY-REGION-001" in {item.id for item in resolution.policies}
    assert "KNOW-MY-COMPANY-REGION-001" in {item.id for item in resolution.knowledge}
    assert resolution.skills == ()


def test_skill_bundle_hides_members_and_rejects_unknown_member(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    bundle = _write_skill(builtin, "combined-review", "组合评审输入并生成建议。")
    _write_skill(builtin, "engineering-review", "分析技术可行性。")
    _write_skill(builtin, "standalone-review", "独立分析风险。")
    (bundle / "bundle.json").write_text(json.dumps({
        "schema_version": 1,
        "members": ["engineering-review"],
    }))
    registry = CapabilityRegistry.from_directories(builtin, None)
    catalog_ids = {item["id"] for item in registry.list_orchestrator_skills()}
    assert catalog_ids == {"combined-review", "standalone-review"}
    with pytest.raises(CapabilityConfigurationError, match="not an Orchestrator entrypoint"):
        registry.resolve_skill_entrypoint("engineering-review")

    broken = tmp_path / "broken"
    skill_dir = broken / "skills" / "review-bundle"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: review-bundle\ndescription: Review one path.\n---\n\n# Review\n"
    )
    (skill_dir / "bundle.json").write_text(json.dumps({
        "schema_version": 1, "members": ["missing-review"],
    }))
    with pytest.raises(CapabilityConfigurationError, match="unknown member"):
        CapabilityRegistry.from_directories(broken, None)


def test_incompatible_commitment_policy_conflict_fails_closed(tmp_path: Path) -> None:
    policy_dir = tmp_path / "builtin" / "policies"
    policy_dir.mkdir(parents=True)
    (tmp_path / "builtin" / "skill-ownership.json").write_text(
        json.dumps({"schema_version": 1, "ownership": {}})
    )
    (tmp_path / "builtin" / "case-types" / "order-delivery-risk").mkdir(parents=True)
    (tmp_path / "builtin" / "case-types" / "order-delivery-risk" / "paths.json").write_text(
        json.dumps({
            "schema_version": 1,
            "case_type": "ORDER_DELIVERY_RISK",
            "title": "订单交付风险",
            "paths": [{"id": "MaterialSubstitution", "title": "物料替代", "description": "desc"}],
        })
    )
    base = {
        "schema_version": 1,
        "version": "1",
        "selector": {
            "case_type": ["ORDER_DELIVERY_RISK"],
            "path_definition": ["MaterialSubstitution"],
        },
        "requirements": {
            "commitments": [{"id": "REVIEW", "role": "主计划", "review_dimension": "供应"}],
        },
    }
    (policy_dir / "one.json").write_text(json.dumps(base | {"id": "POL-A", "title": "A"}))
    conflict = json.loads(json.dumps(base))
    conflict["requirements"]["commitments"][0]["role"] = "研发"
    (policy_dir / "two.json").write_text(json.dumps(conflict | {"id": "POL-B", "title": "B"}))
    registry = CapabilityRegistry.from_directories(tmp_path / "builtin", None)
    with pytest.raises(CapabilityConflictError, match="incompatible commitment"):
        registry.resolve({
            "case_type": "ORDER_DELIVERY_RISK",
            "path_definition": "MaterialSubstitution",
        })


def test_demo_manifest_freezes_verified_capability_references(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    orchestrate(service)
    path = service.get_case(DEMO_CASE_ID).manifest.paths[0]
    assert path.skill_selections[0].entrypoint.id == "material-substitution-analysis"
    assert {item.id for item in path.skill_selections[0].members} == {
        "material-substitution-engineering-review",
        "material-substitution-master-planning-review",
        "material-substitution-supply-manager-review",
    }
    assert "material-substitution-analysis" in {item.id for item in path.skill_refs()}
    capabilities = service.get_case_capabilities(DEMO_CASE_ID, "PATH-01")
    assert capabilities["snapshot_status"] == "frozen"
    assert {item["id"] for item in capabilities["snapshot"]["compiled_policy"]["commitments"]} == {
        "SUPPLY", "TECH", "CUSTOMER",
    }
