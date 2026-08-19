from pathlib import Path

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
