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
    PENDING = "PENDING"
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
    COMMITTED = "COMMITTED"
    STALE = "STALE"
    REJECTED = "REJECTED"


class CommitmentDecision(StrEnum):
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    REJECT = "REJECT"


class OwnerDecisionAction(StrEnum):
    CLOSE = "CLOSE"
    KEEP_OPEN = "KEEP_OPEN"
    MODIFY = "MODIFY"


@dataclass(frozen=True)
class CommitmentNode:
    id: str
    role: str
    node_type: str
    status: NodeStatus
    reviews: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    path_id: str = ""


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
    status: str
    paths: tuple[ManifestPath, ...]
    policy_refs: tuple[str, ...]
    skill_refs: tuple[str, ...]
    knowledge_refs: tuple[str, ...]
    experience_refs: tuple[str, ...]
    capability_snapshot: dict[str, Any] | None
    planner_profile: str = "unknown"
    generated_from_case_version: int = 0
    capability_snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)


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
    path_attempt: dict[str, Any] | None = None
    path_attempts: list[dict[str, Any]] = field(default_factory=list)
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
