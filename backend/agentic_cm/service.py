from __future__ import annotations

import asyncio

from .agent_run import agent_run
from .agent_runtime import AgentError
from .capabilities import CapabilityConfigurationError, CapabilityRegistry, default_registry
from .config import path_execution_mode_from_environment, path_max_concurrency_from_environment
from .demo import DEMO_DATASET_ID, demo_cases
from .domain import (
    CaseEvent,
    CaseStatus,
    CommitmentDecision,
    CommitmentNode,
    HumanProposal,
    NodeStatus,
    OrchestrationPhase,
    OwnerDecision,
    OwnerDecisionAction,
    PathAttempt,
    PathAttemptState,
    utc_now,
)
from .orchestrator import Orchestrator, PlannerAdapter, planner_from_environment
from .path_agent import PathAgent, PathAgentAdapter, path_agent_from_environment
from .repository import CaseRepository
from .synthesis_agent import SynthesisAgent, SynthesisAgentAdapter, synthesis_agent_from_environment


class CaseNotFoundError(LookupError):
    pass


class InvalidTransitionError(ValueError):
    pass


class AuthorizationError(PermissionError):
    pass


class CaseService:
    def __init__(
        self,
        repository: CaseRepository,
        capabilities: CapabilityRegistry | None = None,
        *,
        planner: PlannerAdapter | None = None,
        path_agent: PathAgentAdapter | None = None,
        synthesis_agent: SynthesisAgentAdapter | None = None,
        path_execution_mode: str | None = None,
        path_max_concurrency: int | None = None,
    ) -> None:
        self.repository = repository
        self.capabilities = capabilities or default_registry()
        self.orchestrator = Orchestrator(self.capabilities, planner or planner_from_environment())
        self.path_agent = PathAgent(path_agent or path_agent_from_environment())
        self.synthesis_agent = SynthesisAgent(synthesis_agent or synthesis_agent_from_environment())
        self.path_execution_mode = path_execution_mode or path_execution_mode_from_environment()
        if self.path_execution_mode not in {"parallel", "serial"}:
            raise ValueError("path_execution_mode must be 'parallel' or 'serial'")
        self.path_max_concurrency = (
            path_max_concurrency
            if path_max_concurrency is not None
            else path_max_concurrency_from_environment()
        )
        if self.path_max_concurrency < 1:
            raise ValueError("path_max_concurrency must be a positive integer")
        self._path_commit_locks: dict[str, asyncio.Lock] = {}

    def ensure_demo_data(self) -> None:
        if not self.repository.list_cases():
            self.repository.reset(demo_cases())

    def list_cases(self):
        return self.repository.list_cases()

    def list_capabilities(self) -> dict:
        assets = self.capabilities.list_assets()
        return {
            "assets": assets,
            "counts": {group: len(items) for group, items in assets.items()},
            "case_types": self.capabilities.list_case_types(),
        }

    def get_case(self, case_id: str):
        case = self.repository.get(case_id)
        if case is None:
            raise CaseNotFoundError(case_id)
        return case

    @staticmethod
    def _is_case_owner(case, *, actor: str | None, role: str | None) -> bool:
        return actor == case.owner and role == case.owner_role

    def _require_case_owner(self, case, *, actor: str, role: str) -> None:
        if not self._is_case_owner(case, actor=actor, role=role):
            raise AuthorizationError("Only the Case Owner can view or approve the Manifest")

    def _path_titles(self, case) -> dict[str, str]:
        case_type = case.classification.get("case_type")
        if not case_type:
            return {}
        return {
            definition.id: definition.title
            for definition in self.capabilities.resolve_path_candidates({"case_type": case_type})
        }

    def _asset_titles(self, group: str) -> dict[str, str]:
        return {
            item["id"]: item["title"]
            for item in self.capabilities.list_assets().get(group, [])
            if isinstance(item.get("id"), str) and isinstance(item.get("title"), str)
        }

    def _decorate_manifest_view(self, manifest: dict | None, case) -> dict | None:
        if not manifest:
            return manifest
        path_titles = self._path_titles(case)
        skill_titles = self._asset_titles("skills")
        for path in manifest.get("paths", []):
            definition = path.get("definition")
            if isinstance(definition, str):
                path["title"] = path_titles.get(definition, definition)
            for selection in path.get("skill_selections", []):
                entrypoint = selection.get("entrypoint") or {}
                entrypoint_id = entrypoint.get("id")
                if isinstance(entrypoint_id, str):
                    title = skill_titles.get(entrypoint_id, entrypoint_id)
                    entrypoint["title"] = title
                    selection["title"] = title
                for member in selection.get("members", []):
                    member_id = member.get("id")
                    if isinstance(member_id, str):
                        member["title"] = skill_titles.get(member_id, member_id)
        return manifest

    def get_case_view(
        self,
        case_id: str,
        *,
        actor: str | None = None,
        role: str | None = None,
    ) -> dict:
        case = self.get_case(case_id)
        can_view_manifest = self._is_case_owner(case, actor=actor, role=role)
        view = case.to_dict()
        view["manifest"] = self._decorate_manifest_view(view.get("manifest"), case)
        path_titles = self._path_titles(case)
        visible_paths = ()
        if case.manifest and (
            can_view_manifest
            or case.phase in {
                OrchestrationPhase.PATH_EXPLORATION,
                OrchestrationPhase.PROFESSIONAL_COMMITMENT,
                OrchestrationPhase.FINAL_REVIEW,
            }
        ):
            visible_paths = case.manifest.paths
        view["workflow_paths"] = [
            {
                "id": path.id,
                "definition": path.definition,
                "title": path_titles.get(path.definition, path.definition),
                "selected": True,
                "rationale": "",
            }
            for path in visible_paths
            if path.selected
        ]
        if not can_view_manifest:
            view["manifest"] = None
            view["synthesis_report"] = None
        view["permissions"] = {
            "can_view_manifest": can_view_manifest,
            "can_approve_manifest": can_view_manifest,
            "can_decide_case": can_view_manifest,
        }
        return view

    def get_case_manifest(self, case_id: str, *, actor: str, role: str) -> dict:
        case = self.get_case(case_id)
        self._require_case_owner(case, actor=actor, role=role)
        if case.manifest is None:
            raise InvalidTransitionError("Manifest has not been generated")
        return case.manifest.model_dump(mode="json")

    def get_case_timeline(self, case_id: str) -> list[dict]:
        self.get_case(case_id)
        public_fields = {
            CaseEvent.MANIFEST_PROPOSED: ("revision",),
            CaseEvent.MANIFEST_APPROVED: ("actor",),
            CaseEvent.SOLUTION_REVISION_PROPOSED: ("path_id", "revision"),
            CaseEvent.COMMITMENT_APPROVED: ("actor", "role", "node_id", "path_id"),
            CaseEvent.COMMITMENT_REVISION_REQUESTED: ("actor", "role", "node_id", "path_id"),
            CaseEvent.COMMITMENT_REJECTED: ("actor", "role", "node_id", "path_id"),
            CaseEvent.SYNTHESIS_PROPOSED: ("revision", "successful_path_count", "failed_path_count"),
            CaseEvent.OWNER_DECISION: ("actor", "role", "action", "synthesis_revision", "guidance"),
        }
        timeline: list[dict] = []
        for event in self.repository.list_events(case_id):
            fields = public_fields.get(event["event_type"])
            if fields is None:
                continue
            timeline.append({
                "id": event["id"],
                "event_type": event["event_type"],
                "created_at": event["created_at"],
                "details": {
                    field: event["payload"][field]
                    for field in fields
                    if field in event["payload"]
                },
            })
        return timeline

    def get_agent_runs(
        self,
        case_id: str,
        *,
        actor: str,
        role: str,
        agent_type: str | None = None,
    ) -> list[dict]:
        case = self.get_case(case_id)
        self._require_case_owner(case, actor=actor, role=role)
        if agent_type not in (None, "orchestrator", "path", "synthesis"):
            raise ValueError(f"Unsupported agent_type: {agent_type}")
        return self.repository.list_agent_runs(case_id, agent_type=agent_type)

    async def orchestrate_case(self, case_id: str, *, actor: str, role: str):
        case = self.get_case(case_id)
        self._require_case_owner(case, actor=actor, role=role)
        async with agent_run(
            self.repository,
            case.id,
            agent_type="orchestrator",
            adapter=self.orchestrator.planner,
            actor=actor,
            role=role,
            started_summary="Orchestrator AgentRun 已启动",
            failed_summary="Orchestrator AgentRun 失败；Case 权威状态未修改",
        ) as run:
            manifest, planner_profile = await self.orchestrator.compose_manifest(case, run.trace)
            case.manifest = manifest
            case.phase = OrchestrationPhase.MANIFEST_REVIEW
            case.touch()
            self.repository.save(
                case,
                CaseEvent.MANIFEST_PROPOSED,
                {
                    "manifest_id": manifest.id,
                    "revision": manifest.revision,
                    "planner_profile": planner_profile,
                    "path_definitions": [path.definition for path in manifest.paths],
                },
            )
            run.complete(
                "Manifest 已持久化，Case 进入 MANIFEST_REVIEW",
                {"manifest_id": manifest.id, "case_version": case.version, "phase": case.phase.value},
                adapter_profile=planner_profile,
            )
        return case

    def approve_manifest(
        self,
        case_id: str,
        selected_path_ids: list[str] | None = None,
        *,
        actor: str,
        role: str,
    ):
        case = self.get_case(case_id)
        self._require_case_owner(case, actor=actor, role=role)
        if case.phase is not OrchestrationPhase.MANIFEST_REVIEW or not case.manifest:
            raise InvalidTransitionError("Case is not awaiting Manifest approval")
        if selected_path_ids is not None:
            if not selected_path_ids or len(set(selected_path_ids)) != len(selected_path_ids):
                raise InvalidTransitionError("Manifest approval requires unique, non-empty selected Path ids")
            available = {path.id for path in case.manifest.paths}
            unknown = set(selected_path_ids) - available
            if unknown:
                raise InvalidTransitionError(f"Unknown Manifest Path ids: {sorted(unknown)}")
            selected = set(selected_path_ids)
        else:
            selected = {path.id for path in case.manifest.paths if path.selected}
        selected_paths = [path for path in case.manifest.paths if path.id in selected]
        if not selected_paths:
            raise InvalidTransitionError("At least one Path must remain selected")

        try:
            resolutions = {
                path.id: self.capabilities.resolve_manifest_path(path, case.classification["case_type"])
                for path in selected_paths
            }
        except CapabilityConfigurationError as exc:
            raise InvalidTransitionError(f"Manifest 能力引用已失效，请重新生成 Manifest：{exc}") from exc
        for path in selected_paths:
            if not resolutions[path.id].compiled_policy.get("commitments"):
                raise InvalidTransitionError(f"No mandatory commitments were compiled for Path {path.id}")

        case.manifest = case.manifest.model_copy(
            update={
                "paths": tuple(
                    path.model_copy(update={"selected": path.id in selected})
                    for path in case.manifest.paths
                )
            },
        )
        case.phase = OrchestrationPhase.PATH_EXPLORATION
        attempts: list[PathAttempt] = []
        nodes: list[CommitmentNode] = []
        for path in selected_paths:
            attempts.append(PathAttempt(path_id=path.id, state=PathAttemptState.PLANNED))
            nodes.extend(
                CommitmentNode(
                    id=item["id"],
                    role=item["role"],
                    review_dimension=item["review_dimension"],
                    status=NodeStatus.BLOCKED if item.get("depends_on") else NodeStatus.PENDING,
                    depends_on=tuple(item.get("depends_on", [])),
                    path_id=path.id,
                )
                for item in resolutions[path.id].compiled_policy["commitments"]
            )
        case.path_attempts = attempts
        case.commitment_nodes = nodes
        case.touch()
        self.repository.save(case, CaseEvent.MANIFEST_APPROVED, {
            "manifest_id": case.manifest.id,
            "revision": case.manifest.revision,
            "actor": actor,
            "selected_path_ids": [path.id for path in selected_paths],
        })
        return case

    async def execute_paths(self, case_id: str, path_ids: list[str], *, actor: str, role: str):
        case = self.get_case(case_id)
        self._require_case_owner(case, actor=actor, role=role)
        if not path_ids:
            raise InvalidTransitionError("At least one Path is required")
        if len(path_ids) != len(set(path_ids)):
            raise InvalidTransitionError("Path execution request contains duplicate ids")
        selected_path_ids = {
            path.id for path in (case.manifest.paths if case.manifest else ()) if path.selected
        }
        unknown_path_ids = set(path_ids) - selected_path_ids
        if unknown_path_ids:
            raise InvalidTransitionError(
                f"Path execution request contains unselected ids: {sorted(unknown_path_ids)}"
            )

        if self.path_execution_mode == "parallel":
            semaphore = asyncio.Semaphore(self.path_max_concurrency)

            async def execute_with_limit(path_id: str):
                async with semaphore:
                    return await self.execute_path(case_id, path_id, actor=actor, role=role)

            results = await asyncio.gather(
                *(execute_with_limit(path_id) for path_id in path_ids),
                return_exceptions=True,
            )
        else:
            results = []
            for path_id in path_ids:
                try:
                    results.append(await self.execute_path(case_id, path_id, actor=actor, role=role))
                except Exception as exc:
                    results.append(exc)
                    break

        failure = next((result for result in results if isinstance(result, Exception)), None)
        if failure is not None:
            raise failure
        return self.get_case(case_id)

    async def execute_path(self, case_id: str, path_id: str, *, actor: str, role: str):
        case_snapshot = self.get_case(case_id)
        self._require_case_owner(case_snapshot, actor=actor, role=role)
        async with agent_run(
            self.repository,
            case_snapshot.id,
            agent_type="path",
            adapter=self.path_agent.adapter,
            actor=actor,
            role=role,
            started_summary="Path AgentRun 已启动",
            failed_summary="Path AgentRun 失败；Case 与 SolutionRevision 未修改",
            started_details={"path_id": path_id},
        ) as run:
            path = next(
                (
                    item for item in case_snapshot.manifest.paths
                    if item.id == path_id and item.selected
                ),
                None,
            ) if case_snapshot.manifest else None
            if path is None:
                raise AgentError(f"Unknown selected Manifest Path: {path_id}")
            try:
                resolution = self.capabilities.resolve_manifest_path(
                    path, case_snapshot.classification["case_type"]
                )
            except CapabilityConfigurationError as exc:
                run.trace(
                    "capabilities.resolve",
                    "FAILED",
                    "Manifest 能力引用校验失败",
                    {
                        "path_id": path_id,
                        "skill_selections": [item.model_dump(mode="json") for item in path.skill_selections],
                        "error": str(exc),
                    },
                )
                raise AgentError(f"Manifest 能力引用已失效，请重新生成 Manifest：{exc}") from exc
            run.trace(
                "capabilities.resolve",
                "COMPLETED",
                "目标 Path 的 Manifest 能力引用通过校验",
                {
                    "path_id": path_id,
                    "skill_selections": [item.model_dump(mode="json") for item in path.skill_selections],
                    "policies": [item.model_dump(mode="json") for item in path.policies],
                    "knowledge": [item.model_dump(mode="json") for item in path.knowledge],
                },
            )
            initial_attempt = next(
                attempt for attempt in case_snapshot.path_attempts if attempt.path_id == path_id
            )
            initial_solution_revision = initial_attempt.solution_revision
            solution_revision = await self.path_agent.run(
                case_snapshot,
                path_id,
                self._path_titles(case_snapshot).get(path.definition, path.definition),
                resolution,
                run.trace,
            )
            lock = self._path_commit_locks.setdefault(case_id, asyncio.Lock())
            async with lock:
                case = self.get_case(case_id)
                self._require_case_owner(case, actor=actor, role=role)
                current_attempt = next(
                    attempt for attempt in case.path_attempts if attempt.path_id == path_id
                )
                if current_attempt.solution_revision != initial_solution_revision:
                    raise InvalidTransitionError(f"Path {path_id} changed while its Agent was running")
                case.path_attempts = [
                    attempt.model_copy(update={
                        "state": PathAttemptState.AWAITING_COMMITMENT,
                        "solution_revision": solution_revision,
                    }) if attempt.path_id == path_id else attempt
                    for attempt in case.path_attempts
                ]
                if all(attempt.solution_revision for attempt in case.path_attempts):
                    case.phase = OrchestrationPhase.PROFESSIONAL_COMMITMENT
                ready_ids = {
                    node.id for node in case.commitment_nodes
                    if node.path_id == path_id and node.status is NodeStatus.READY
                }
                case.commitment_nodes = [
                    node.model_copy(update={
                        "status": NodeStatus.PENDING if set(node.depends_on).issubset(ready_ids) else NodeStatus.BLOCKED
                    })
                    if node.path_id == path_id and node.status is NodeStatus.STALE
                    else node
                    for node in case.commitment_nodes
                ]
                case.touch()
                self.repository.save(case, CaseEvent.SOLUTION_REVISION_PROPOSED, {
                    "path_id": path_id,
                    "revision": solution_revision.revision,
                    "generated_by": solution_revision.generated_by,
                    "next_phase": case.phase.value,
                })
            run.complete(
                "SolutionRevision 已持久化，等待人类责任节点评审",
                {
                    "path_id": path_id,
                    "revision": solution_revision.revision,
                    "case_version": case.version,
                    "phase": case.phase.value,
                },
                adapter_profile=solution_revision.generated_by,
            )
        return case

    def get_inbox(self, role: str) -> list[dict]:
        items: list[dict] = []
        for case in self.repository.list_cases():
            if case.phase is not OrchestrationPhase.PROFESSIONAL_COMMITMENT:
                continue
            definition_titles = self._path_titles(case)
            path_titles = {
                path.id: definition_titles.get(path.definition, path.definition)
                for path in (case.manifest.paths if case.manifest else ())
            }
            for node in case.commitment_nodes:
                if node.role != role or node.status is not NodeStatus.PENDING:
                    continue
                attempt = next(
                    (item for item in case.path_attempts if item.path_id == node.path_id),
                    None,
                )
                revision = attempt.solution_revision if attempt else None
                role_report = next(
                    (
                        item for item in (revision.role_reports if revision else [])
                        if item.role == node.role and item.dimension == node.review_dimension
                    ),
                    None,
                )
                items.append({
                    "case_id": case.id,
                    "case_title": case.title,
                    "path_id": node.path_id,
                    "path_title": path_titles.get(node.path_id, node.path_id),
                    "node": node.model_dump(mode="json"),
                    "approval_context": {
                        "revision": revision.revision if revision else None,
                        "recommendation": revision.recommendation if revision else "",
                        "role_report": role_report.model_dump(mode="json") if role_report else None,
                    },
                })
        return items

    def approve_commitment(self, case_id: str, path_id: str, node_id: str, *, actor: str, role: str):
        return self.decide_commitment(
            case_id, path_id, node_id, decision=CommitmentDecision.APPROVE, actor=actor, role=role
        )

    def decide_commitment(
        self,
        case_id: str,
        path_id: str,
        node_id: str,
        *,
        decision: CommitmentDecision,
        actor: str,
        role: str,
    ):
        case = self.get_case(case_id)
        if case.phase is not OrchestrationPhase.PROFESSIONAL_COMMITMENT:
            raise InvalidTransitionError("Case is not in professional commitment review")
        target_index = next(
            (
                index for index, node in enumerate(case.commitment_nodes)
                if node.path_id == path_id and node.id == node_id
            ),
            None,
        )
        if target_index is None:
            raise InvalidTransitionError(f"Unknown Commitment node: {path_id}/{node_id}")
        target = case.commitment_nodes[target_index]
        if target.role != role:
            raise InvalidTransitionError(f"Commitment requires role {target.role}")
        if target.status is not NodeStatus.PENDING:
            raise InvalidTransitionError("Commitment is not awaiting Inbox approval")
        if not actor.strip():
            raise InvalidTransitionError("Commitment decision requires an actor")

        nodes = list(case.commitment_nodes)
        if decision is CommitmentDecision.APPROVE:
            nodes[target_index] = target.model_copy(update={"status": NodeStatus.READY})
            ready_ids = {
                node.id for node in nodes
                if node.path_id == path_id and node.status is NodeStatus.READY
            }
            nodes = [
                node.model_copy(update={"status": NodeStatus.PENDING})
                if node.path_id == path_id
                and node.status is NodeStatus.BLOCKED
                and set(node.depends_on).issubset(ready_ids)
                else node
                for node in nodes
            ]
            event_type = CaseEvent.COMMITMENT_APPROVED
        elif decision is CommitmentDecision.REVISE:
            nodes[target_index] = target.model_copy(update={"status": NodeStatus.STALE})
            event_type = CaseEvent.COMMITMENT_REVISION_REQUESTED
            self._update_path_attempt(case, path_id, state=PathAttemptState.REVISING)
            case.phase = OrchestrationPhase.PATH_EXPLORATION
        elif decision is CommitmentDecision.REJECT:
            nodes[target_index] = target.model_copy(update={"status": NodeStatus.REJECTED})
            nodes = [
                node.model_copy(update={"status": NodeStatus.STALE})
                if node.path_id == path_id
                and node.id != node_id
                and node.status in {NodeStatus.PENDING, NodeStatus.BLOCKED}
                else node
                for node in nodes
            ]
            event_type = CaseEvent.COMMITMENT_REJECTED
            self._update_path_attempt(case, path_id, state=PathAttemptState.REJECTED)
        else:
            raise InvalidTransitionError(f"Unsupported Commitment decision: {decision}")
        case.commitment_nodes = nodes
        for attempt in list(case.path_attempts):
            path_nodes = [node for node in nodes if node.path_id == attempt.path_id]
            if any(node.status is NodeStatus.REJECTED for node in path_nodes):
                self._update_path_attempt(case, attempt.path_id, state=PathAttemptState.REJECTED)
            elif path_nodes and all(node.status is NodeStatus.READY for node in path_nodes):
                self._update_path_attempt(case, attempt.path_id, state=PathAttemptState.SUCCEEDED)
        if self._all_selected_paths_terminal(case):
            case.phase = OrchestrationPhase.FINAL_REVIEW
        case.touch()
        self.repository.save(case, event_type, {
            "path_id": path_id,
            "node_id": node_id,
            "actor": actor,
            "role": role,
        })
        return case

    @staticmethod
    def _all_selected_paths_terminal(case) -> bool:
        selected_ids = {
            path.id for path in (case.manifest.paths if case.manifest else ()) if path.selected
        }
        attempts = {attempt.path_id: attempt for attempt in case.path_attempts}
        return bool(selected_ids) and all(
            attempts.get(path_id) is not None
            and attempts[path_id].state in {PathAttemptState.SUCCEEDED, PathAttemptState.REJECTED}
            for path_id in selected_ids
        )

    async def synthesize_case(self, case_id: str, *, actor: str, role: str):
        case = self.get_case(case_id)
        self._require_case_owner(case, actor=actor, role=role)
        async with agent_run(
            self.repository,
            case.id,
            agent_type="synthesis",
            adapter=self.synthesis_agent.adapter,
            actor=actor,
            role=role,
            started_summary="Synthesis AgentRun 已启动",
            failed_summary="Synthesis AgentRun 失败；CaseSynthesis 未修改",
        ) as run:
            report = await self.synthesis_agent.run(case, self._path_titles(case), run.trace)
            case.synthesis_report = report
            case.owner_decision = None
            case.touch()
            successful = sum(item.status == "SUCCEEDED" for item in report.path_assessments)
            failed = len(report.path_assessments) - successful
            self.repository.save(case, CaseEvent.SYNTHESIS_PROPOSED, {
                "revision": report.revision,
                "successful_path_count": successful,
                "failed_path_count": failed,
                "generated_by": report.generated_by,
            })
            run.complete(
                "CaseSynthesis 已持久化，等待 Case Owner 最终决策",
                {"revision": report.revision, "case_version": case.version},
                adapter_profile=report.generated_by,
            )
        return case

    def decide_case(
        self,
        case_id: str,
        *,
        action: OwnerDecisionAction,
        actor: str,
        role: str,
        guidance: str | None = None,
    ):
        case = self.get_case(case_id)
        self._require_case_owner(case, actor=actor, role=role)
        if case.phase is not OrchestrationPhase.FINAL_REVIEW or not case.synthesis_report:
            raise InvalidTransitionError("Case is not awaiting an Owner decision with a Synthesis report")
        if case.status is CaseStatus.CLOSED:
            raise InvalidTransitionError("A closed Case cannot receive another Owner decision")
        normalized_guidance = guidance.strip() if guidance else ""
        if action is OwnerDecisionAction.MODIFY and not normalized_guidance:
            raise InvalidTransitionError("Modification requires Case Owner guidance for the Orchestrator")
        previous_human_proposal = (
            case.human_proposal.model_dump(mode="json") if case.human_proposal else None
        )
        decision = OwnerDecision(
            action=action,
            actor=actor,
            role=role,
            synthesis_revision=case.synthesis_report.revision,
            decided_at=utc_now(),
        )
        decision_event = decision.model_dump(mode="json") | {
            "synthesis_snapshot": case.synthesis_report.model_dump(mode="json"),
            "path_attempts_snapshot": [attempt.model_dump(mode="json") for attempt in case.path_attempts],
            "commitments_snapshot": [node.model_dump(mode="json") for node in case.commitment_nodes],
        }
        if action is OwnerDecisionAction.MODIFY:
            decision_event["guidance"] = normalized_guidance
            decision_event["previous_human_proposal_snapshot"] = previous_human_proposal
        case.owner_decision = decision
        if action is OwnerDecisionAction.CLOSE:
            case.status = CaseStatus.CLOSED
        elif action is OwnerDecisionAction.KEEP_OPEN:
            case.status = CaseStatus.OPEN
        elif action is OwnerDecisionAction.MODIFY:
            case.human_proposal = HumanProposal(
                revision=int((case.human_proposal.revision if case.human_proposal else 0)) + 1,
                author=actor,
                role=role,
                content=normalized_guidance,
            )
            case.status = CaseStatus.OPEN
            case.phase = OrchestrationPhase.INTAKE
            case.manifest = None
            case.path_attempts = []
            case.commitment_nodes = []
            case.synthesis_report = None
        else:
            raise InvalidTransitionError(f"Unsupported Owner decision: {action}")
        case.version += 1
        case.updated_at = decision.decided_at
        self.repository.save(case, CaseEvent.OWNER_DECISION, decision_event)
        return case

    @staticmethod
    def _update_path_attempt(case, path_id: str, *, state: PathAttemptState) -> None:
        case.path_attempts = [
            attempt.model_copy(update={"state": state}) if attempt.path_id == path_id else attempt
            for attempt in case.path_attempts
        ]

    def reset_demo(self, dataset_id: str):
        if dataset_id != DEMO_DATASET_ID:
            raise ValueError("Unknown demo dataset")
        self.repository.reset(demo_cases())

    def get_case_capabilities(self, case_id: str, path_id: str | None = None) -> dict:
        case = self.get_case(case_id)
        selected_paths = [path for path in (case.manifest.paths if case.manifest else ()) if path.selected]
        target_path = next((path for path in selected_paths if path.id == path_id), None) if path_id else None
        if path_id and target_path is None:
            raise InvalidTransitionError(f"Unknown selected Path: {path_id}")
        target_path = target_path or (selected_paths[0] if selected_paths else None)
        snapshot = None
        if case.manifest and target_path:
            try:
                snapshot = self.capabilities.resolve_manifest_path(
                    target_path, case.classification["case_type"]
                ).to_snapshot()
            except CapabilityConfigurationError as exc:
                raise InvalidTransitionError(
                    f"Manifest 能力引用已失效，请重新生成 Manifest：{exc}"
                ) from exc
        snapshot_status = "frozen"
        if not snapshot:
            if target_path is None:
                raise InvalidTransitionError("Case has no selected Path for capability resolution")
            snapshot = self.capabilities.resolve(
                case.classification | {"path_definition": target_path.definition}
            ).to_snapshot()
            snapshot_status = "preview"
            snapshot["asset_payloads"]["skills"] = []
        return {
            "snapshot_status": snapshot_status,
            "path_id": target_path.id if target_path else None,
            "available_paths": [path.id for path in selected_paths],
        } | self.capabilities.describe_snapshot(snapshot)
