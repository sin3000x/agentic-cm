from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


def utc_now() -> str:
    """The current UTC instant as an ISO 8601 string.

    Every persisted timestamp goes through here so stored values stay
    timezone-aware and comparable.
    """
    return datetime.now(timezone.utc).isoformat()


class CaseStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OrchestrationPhase(StrEnum):
    INTAKE = "INTAKE"
    MANIFEST_REVIEW = "MANIFEST_REVIEW"
    PATH_EXPLORATION = "PATH_EXPLORATION"
    PROFESSIONAL_COMMITMENT = "PROFESSIONAL_COMMITMENT"
    FINAL_REVIEW = "FINAL_REVIEW"


class NodeStatus(StrEnum):
    BLOCKED = "BLOCKED"
    PENDING = "PENDING"
    READY = "READY"
    STALE = "STALE"
    REJECTED = "REJECTED"


class PathAttemptState(StrEnum):
    PLANNED = "PLANNED"
    AWAITING_COMMITMENT = "AWAITING_COMMITMENT"
    REVISING = "REVISING"
    SUCCEEDED = "SUCCEEDED"
    REJECTED = "REJECTED"


class CommitmentDecision(StrEnum):
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    REJECT = "REJECT"


class OwnerDecisionAction(StrEnum):
    CLOSE = "CLOSE"
    KEEP_OPEN = "KEEP_OPEN"
    MODIFY = "MODIFY"


class CaseEvent(StrEnum):
    """Append-only domain event types.

    Both the write side and the public timeline projection reference these, so
    a mistyped name is a resolution error rather than a silently dropped
    timeline entry.
    """

    MANIFEST_PROPOSED = "manifest.proposed"
    MANIFEST_APPROVED = "manifest.approved"
    SOLUTION_REVISION_PROPOSED = "solution_revision.proposed"
    COMMITMENT_APPROVED = "commitment.approved"
    COMMITMENT_REVISION_REQUESTED = "commitment.revision_requested"
    COMMITMENT_REJECTED = "commitment.rejected"
    SYNTHESIS_PROPOSED = "synthesis.proposed"
    OWNER_DECISION = "owner.decision"

    # Startup backfills of Cases persisted by earlier versions. These are
    # deliberately absent from the public timeline.
    CASE_DEMO_METADATA_MIGRATED = "case.demo_metadata_migrated"
    CASE_PHASE_MIGRATED = "case.phase_migrated"
    COMMITMENT_PENDING_MIGRATION = "commitment.pending_migration"
    PATH_ATTEMPT_TERMINAL_MIGRATED = "path_attempt.terminal_migrated"


@dataclass(frozen=True)
class CommitmentNode:
    id: str
    role: str
    review_dimension: str
    status: NodeStatus
    depends_on: tuple[str, ...] = ()
    path_id: str = ""


@dataclass(frozen=True)
class PathAttempt:
    path_id: str
    state: PathAttemptState
    solution_revision: dict[str, Any] | None = None


@dataclass(frozen=True)
class ManifestPath:
    id: str
    definition: str
    title: str
    rationale: str
    selected: bool = True


@dataclass(frozen=True)
class Manifest:
    id: str
    revision: int
    paths: tuple[ManifestPath, ...]
    capability_snapshots: dict[str, dict[str, Any]]
    planner_profile: str = "unknown"
    generated_from_case_version: int = 0


@dataclass
class Case:
    id: str
    title: str
    description: str
    status: CaseStatus
    phase: OrchestrationPhase
    owner: str
    owner_role: str
    business_payload: dict[str, Any]
    human_proposal: dict[str, Any] | None
    classification: dict[str, str] = field(default_factory=dict)
    manifest: Manifest | None = None
    path_attempts: list[PathAttempt] = field(default_factory=list)
    commitment_nodes: list[CommitmentNode] = field(default_factory=list)
    synthesis_report: dict[str, Any] | None = None
    owner_decision: dict[str, Any] | None = None
    version: int = 1
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def touch(self) -> None:
        """Record a new authoritative revision of this Case.

        Every state change bumps the version and the timestamp together; they
        are what the optimistic-concurrency check and the UI both read.
        """
        self.version += 1
        self.updated_at = utc_now()
