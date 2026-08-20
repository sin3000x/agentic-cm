from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from .capabilities import CapabilityRegistry, default_registry
from .demo import demo_cases
from .domain import CommitmentNode, NodeStatus, OrchestrationPhase
from .repository import CaseRepository


class CaseNotFoundError(LookupError):
    pass


class InvalidTransitionError(ValueError):
    pass


class CaseService:
    def __init__(self, repository: CaseRepository, capabilities: CapabilityRegistry | None = None) -> None:
        self.repository = repository
        self.capabilities = capabilities or default_registry()

    def ensure_demo_data(self) -> None:
        if not self.repository.list_cases():
            self.repository.reset(demo_cases(self.capabilities))

    def list_cases(self):
        return self.repository.list_cases()

    def get_case(self, case_id: str):
        case = self.repository.get(case_id)
        if case is None:
            raise CaseNotFoundError(case_id)
        return case

    def approve_manifest(self, case_id: str):
        case = self.get_case(case_id)
        if case.phase is not OrchestrationPhase.MANIFEST_REVIEW or not case.manifest:
            raise InvalidTransitionError("Case is not awaiting Manifest approval")
        if not any(path.selected for path in case.manifest.paths):
            raise InvalidTransitionError("At least one Path must remain selected")

        snapshot = case.manifest.capability_snapshot
        if not snapshot:
            snapshot = self._resolve_case_capabilities(case)
            case.manifest = replace(case.manifest, capability_snapshot=snapshot)
        compiled = snapshot["compiled_policy"]
        if not compiled.get("commitments"):
            raise InvalidTransitionError("No mandatory commitment requirements were compiled for this Path")

        case.phase = OrchestrationPhase.PATH_EXPLORATION
        selected_path = next(path for path in case.manifest.paths if path.selected)
        case.path_attempt = {
            "id": "ATTEMPT-01",
            "definition": selected_path.definition,
            "phase": "AWAITING_HUMAN",
            "outcome": None,
            "solution_revision": 1,
        }
        case.commitment_nodes = [
            CommitmentNode(
                id=item["id"],
                role=item["role"],
                node_type=item["node_type"],
                status=NodeStatus.BLOCKED if item.get("depends_on") else NodeStatus.READY,
                reviews=tuple(item["reviews"]),
                depends_on=tuple(item.get("depends_on", [])),
            )
            for item in compiled["commitments"]
        ]
        case.version += 1
        case.updated_at = datetime.now(timezone.utc).isoformat()
        self.repository.save(case, "manifest.approved", {"manifest_id": case.manifest.id, "revision": case.manifest.revision, "actor": case.owner})
        return case

    def reset_demo(self, dataset_id: str):
        if dataset_id != "supply-chain-golden-path-v1":
            raise ValueError("Unknown demo dataset")
        self.repository.reset(demo_cases(self.capabilities))

    def get_case_capabilities(self, case_id: str) -> dict:
        case = self.get_case(case_id)
        snapshot = case.manifest.capability_snapshot if case.manifest else None
        snapshot_status = "frozen"
        if not snapshot:
            snapshot = self._resolve_case_capabilities(case)
            snapshot_status = "preview"
        return {"snapshot_status": snapshot_status} | self.capabilities.describe_snapshot(snapshot)

    def _resolve_case_capabilities(self, case) -> dict:
        selected_path = next((path for path in (case.manifest.paths if case.manifest else ()) if path.selected), None)
        if selected_path is None:
            raise InvalidTransitionError("Case has no selected Path for capability resolution")
        context = case.classification | {"path_definition": selected_path.definition}
        return self.capabilities.resolve(context).to_snapshot()
