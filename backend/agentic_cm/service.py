from __future__ import annotations

from datetime import datetime, timezone

from .demo import demo_cases
from .domain import CommitmentNode, NodeStatus, OrchestrationPhase
from .repository import CaseRepository


class CaseNotFoundError(LookupError):
    pass


class InvalidTransitionError(ValueError):
    pass


class CaseService:
    def __init__(self, repository: CaseRepository) -> None:
        self.repository = repository

    def ensure_demo_data(self) -> None:
        if not self.repository.list_cases():
            self.repository.reset(demo_cases())

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

        case.phase = OrchestrationPhase.PATH_EXPLORATION
        case.path_attempt = {"id": "ATTEMPT-01", "definition": "MaterialSubstitution", "phase": "AWAITING_HUMAN", "outcome": None, "solution_revision": 1}
        case.commitment_nodes = [
            CommitmentNode(id="SUPPLY", role="主计划", node_type="APPROVAL", status=NodeStatus.READY, reviews=("supply",)),
            CommitmentNode(id="TECH", role="研发", node_type="APPROVAL", status=NodeStatus.READY, reviews=("technical",)),
            CommitmentNode(id="CUSTOMER", role="一线经理", node_type="REVIEW", status=NodeStatus.BLOCKED, reviews=("customer", "overall_recommendation"), depends_on=("SUPPLY", "TECH")),
        ]
        case.version += 1
        case.updated_at = datetime.now(timezone.utc).isoformat()
        self.repository.save(case, "manifest.approved", {"manifest_id": case.manifest.id, "revision": case.manifest.revision, "actor": case.owner})
        return case

    def reset_demo(self, dataset_id: str):
        if dataset_id != "supply-chain-golden-path-v1":
            raise ValueError("Unknown demo dataset")
        self.repository.reset(demo_cases())
