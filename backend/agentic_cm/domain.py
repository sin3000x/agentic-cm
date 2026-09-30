from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
PathOutcome = Literal["SUCCEEDED", "FAILED"]


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
    AWAITING_INFORMATION = "AWAITING_INFORMATION"
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
    MANIFEST_PROPOSED = "manifest.proposed"
    MANIFEST_APPROVED = "manifest.approved"
    SOLUTION_REVISION_PROPOSED = "solution_revision.proposed"
    INFORMATION_REQUESTED = "information.requested"
    INFORMATION_ANSWERED = "information.answered"
    COMMITMENT_APPROVED = "commitment.approved"
    COMMITMENT_REVISION_REQUESTED = "commitment.revision_requested"
    COMMITMENT_REJECTED = "commitment.rejected"
    SYNTHESIS_PROPOSED = "synthesis.proposed"
    OWNER_DECISION = "owner.decision"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MutableModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssetRef(FrozenModel):
    """Frozen Manifest pointer: id + version + content digest."""

    id: str
    version: str
    digest: str


class ManifestSkillSelection(FrozenModel):
    entrypoint: AssetRef
    reason: str | None = None
    members: tuple[AssetRef, ...] = ()

    @model_validator(mode="after")
    def validate_members(self) -> "ManifestSkillSelection":
        member_ids = [item.id for item in self.members]
        if self.entrypoint.id in member_ids:
            raise ValueError("Manifest Skill entrypoint cannot also be a member")
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("Manifest Skill member ids must be unique")
        return self


class ManifestPath(FrozenModel):
    id: str
    definition: str
    rationale: str
    selected: bool = True
    skill_selections: tuple[ManifestSkillSelection, ...] = ()
    policies: tuple[AssetRef, ...] = ()
    knowledge: tuple[AssetRef, ...] = ()

    @model_validator(mode="after")
    def validate_capabilities(self) -> "ManifestPath":
        entrypoint_ids = [selection.entrypoint.id for selection in self.skill_selections]
        if any(not asset_id.strip() for asset_id in entrypoint_ids):
            raise ValueError("Manifest Skill ids must be non-empty strings")
        if len(entrypoint_ids) != len(set(entrypoint_ids)):
            raise ValueError("Manifest Skill ids must be unique within a Path")
        for label, assets in (("Policy", self.policies), ("Knowledge", self.knowledge)):
            ids = [asset.id for asset in assets]
            if any(not asset_id.strip() for asset_id in ids):
                raise ValueError(f"Manifest {label} ids must be non-empty strings")
            if len(ids) != len(set(ids)):
                raise ValueError(f"Manifest {label} ids must be unique within a Path")
        self.skill_refs()
        return self

    def skill_refs(self) -> tuple[AssetRef, ...]:
        by_id: dict[str, AssetRef] = {}
        for selection in self.skill_selections:
            for ref in (selection.entrypoint, *selection.members):
                existing = by_id.get(ref.id)
                if existing is not None and existing != ref:
                    raise ValueError(f"Manifest Skill {ref.id!r} has conflicting references")
                by_id.setdefault(ref.id, ref)
        return tuple(by_id.values())


class Manifest(FrozenModel):
    id: str
    revision: int
    paths: tuple[ManifestPath, ...]
    knowledge: tuple[AssetRef, ...] = ()
    generated_from_case_version: int = 0

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "Manifest":
        path_ids = [path.id for path in self.paths]
        if len(path_ids) != len(set(path_ids)):
            raise ValueError("Manifest Path ids must be unique")
        knowledge_ids = [item.id for item in self.knowledge]
        if len(knowledge_ids) != len(set(knowledge_ids)):
            raise ValueError("Manifest global Knowledge ids must be unique")
        return self

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.model_dump(mode="json"), allow_unicode=True, sort_keys=False)

    @classmethod
    def from_yaml(cls, content: str) -> "Manifest":
        payload = yaml.safe_load(content)
        if not isinstance(payload, dict):
            raise ValueError("Manifest YAML must contain an object")
        return cls.model_validate(payload)


class CommitmentNode(FrozenModel):
    id: str
    role: str
    review_dimension: str
    status: NodeStatus
    depends_on: tuple[str, ...] = ()
    path_id: str = ""
    reviewed_revision: int | None = None
    decision_reason: str | None = None


class InformationQuestion(FrozenModel):
    role: NonEmptyText
    question: NonEmptyText
    reason: NonEmptyText
    material_id: NonEmptyText | None = None
    required_by: str | None = None

    @model_validator(mode="after")
    def validate_supply_scope(self) -> "InformationQuestion":
        if (self.material_id is None) != (self.required_by is None):
            raise ValueError("Supply questions require both material_id and required_by")
        if self.required_by is not None:
            datetime.strptime(self.required_by, "%Y-%m-%d")
        return self


class InformationRequest(InformationQuestion):
    id: str
    answer: str | None = None
    answered_by: str | None = None
    answered_at: str | None = None
    answer_quantity: int | None = Field(default=None, ge=0, strict=True)


class RoleReport(MutableModel):
    role: NonEmptyText
    dimension: NonEmptyText
    report: NonEmptyText


class PathAgentResult(MutableModel):
    """Chinese Path recommendation plus one role_report per required contract."""

    recommendation: str = ""
    role_reports: list[RoleReport] = Field(default_factory=list)
    information_requests: list[InformationQuestion] = Field(
        default_factory=list,
        description="缺少必要事实时填写；此时 recommendation、change_summary 必须为空，role_reports 必须为空数组。",
    )
    change_summary: str = Field(default="", description="修订完整方案时必须说明如何回应反馈；请求信息时必须为空。")

    @model_validator(mode="after")
    def validate_unique_keys(self) -> "PathAgentResult":
        if self.information_requests:
            conflicts = [name for name in ("recommendation", "role_reports", "change_summary")
                         if (getattr(self, name).strip() if isinstance(getattr(self, name), str)
                             else getattr(self, name))]
            if conflicts:
                raise ValueError("信息请求分支不允许包含：" + ", ".join(conflicts))
        role_keys = [(item.role, item.dimension) for item in self.role_reports]
        if len(set(role_keys)) != len(role_keys):
            raise ValueError("Path Agent role reports must be unique by role and dimension")
        return self


class SolutionRevision(PathAgentResult):
    schema_version: int = 1
    revision: int
    generated_by: str


class PathAttempt(FrozenModel):
    path_id: str
    state: PathAttemptState
    solution_revision: SolutionRevision | None = None
    information_requests: list[InformationRequest] = Field(default_factory=list)


class PathAssessment(MutableModel):
    path_id: NonEmptyText
    status: PathOutcome
    conclusion: NonEmptyText
    supporting_refs: list[NonEmptyText] = Field(min_length=1)
    risks: list[NonEmptyText]


class SynthesisResult(MutableModel):
    """Structured Synthesis Agent output. SynthesisReport adds platform fields."""

    summary: NonEmptyText
    path_assessments: list[PathAssessment] = Field(min_length=1)
    cross_path_findings: list[NonEmptyText]
    remaining_risks: list[NonEmptyText]
    recommended_owner_action: OwnerDecisionAction
    decision_brief: NonEmptyText


class SynthesisReport(SynthesisResult):
    schema_version: int = 1
    revision: int
    generated_by: str
    manifest_ref: dict[str, Any] = Field(default_factory=dict)


class HumanProposal(MutableModel):
    revision: int
    author: str
    role: str
    content: str


class OwnerDecision(MutableModel):
    action: OwnerDecisionAction
    actor: str
    role: str
    synthesis_revision: int
    decided_at: str


class Case(MutableModel):
    id: str
    title: str
    description: str
    status: CaseStatus
    phase: OrchestrationPhase
    owner: str
    owner_role: str
    business_payload: dict[str, Any]
    human_proposal: HumanProposal | None = None
    classification: dict[str, str] = Field(default_factory=dict)
    manifest: Manifest | None = None
    path_attempts: list[PathAttempt] = Field(default_factory=list)
    commitment_nodes: list[CommitmentNode] = Field(default_factory=list)
    synthesis_report: SynthesisReport | None = None
    owner_decision: OwnerDecision | None = None
    version: int = 1
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def touch(self) -> None:
        self.version += 1
        self.updated_at = utc_now()
