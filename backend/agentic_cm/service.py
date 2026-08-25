from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from datetime import datetime, timezone
from uuid import uuid4

from .capabilities import CapabilityRegistry, default_registry
from .config import (
    path_execution_mode_from_environment,
    path_max_concurrency_from_environment,
)
from .demo import DEMO_DATASET_ID, LEGACY_DEMO_TITLES, demo_cases
from .domain import (
    CaseStatus,
    CommitmentDecision,
    CommitmentNode,
    NodeStatus,
    OrchestrationPhase,
    OwnerDecisionAction,
)
from .orchestrator import Orchestrator, PlannerAdapter, planner_from_environment
from .path_agent import PathAgent, PathAgentAdapter, path_agent_from_environment
from .repository import CaseRepository
from .synthesis_agent import (
    SynthesisAgent,
    SynthesisAgentAdapter,
    synthesis_agent_from_environment,
)


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
        self.orchestrator = Orchestrator(
            self.capabilities,
            planner or planner_from_environment(),
        )
        self.path_agent = PathAgent(path_agent or path_agent_from_environment())
        self.synthesis_agent = SynthesisAgent(
            synthesis_agent or synthesis_agent_from_environment()
        )
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
        cases = self.repository.list_cases()
        if not cases:
            self.repository.reset(demo_cases())
            return
        demo_by_id = {case.id: case for case in demo_cases()}
        for case in cases:
            template = demo_by_id.get(case.id)
            if template and case.title == LEGACY_DEMO_TITLES.get(case.id):
                case.title = template.title
                case.description = template.description
                case.business_payload = {
                    **template.business_payload,
                    **case.business_payload,
                }
                case.version += 1
                case.updated_at = datetime.now(timezone.utc).isoformat()
                self.repository.save(case, "case.demo_metadata_migrated", {
                    "dataset_id": DEMO_DATASET_ID,
                    "fields": ["title", "description", "business_payload"],
                })
            if (
                case.phase is OrchestrationPhase.PATH_EXPLORATION
                and case.path_attempts
                and all(attempt.get("solution_revision") for attempt in case.path_attempts)
                and not any(attempt.get("phase") == "REVISING" for attempt in case.path_attempts)
            ):
                case.phase = OrchestrationPhase.PROFESSIONAL_COMMITMENT
                case.version += 1
                case.updated_at = datetime.now(timezone.utc).isoformat()
                self.repository.save(case, "case.phase_migrated", {
                    "from": OrchestrationPhase.PATH_EXPLORATION.value,
                    "to": OrchestrationPhase.PROFESSIONAL_COMMITMENT.value,
                    "reason": "all Path explorations already produced SolutionRevisions",
                })
            if (
                case.phase is OrchestrationPhase.PROFESSIONAL_COMMITMENT
                and case.commitment_nodes
                and not self.repository.has_event(case.id, "commitment.approved")
                and any(
                    node.status is NodeStatus.READY and not node.depends_on
                    for node in case.commitment_nodes
                )
            ):
                case.commitment_nodes = [
                    replace(node, status=NodeStatus.PENDING)
                    if node.status is NodeStatus.READY and not node.depends_on
                    else node
                    for node in case.commitment_nodes
                ]
                case.version += 1
                case.updated_at = datetime.now(timezone.utc).isoformat()
                self.repository.save(case, "commitment.pending_migration", {
                    "reason": "introduce explicit role Inbox approval before READY",
                })
            if case.phase is OrchestrationPhase.PROFESSIONAL_COMMITMENT:
                previous_attempt_states = [
                    (attempt.get("path_id"), attempt.get("phase"), attempt.get("outcome"))
                    for attempt in case.path_attempts
                ]
                for attempt in list(case.path_attempts):
                    path_id = attempt.get("path_id")
                    path_nodes = [node for node in case.commitment_nodes if node.path_id == path_id]
                    if any(node.status is NodeStatus.REJECTED for node in path_nodes):
                        self._update_path_attempt(case, path_id, phase="DONE", outcome="REJECTED")
                    elif path_nodes and all(node.status is NodeStatus.READY for node in path_nodes):
                        self._update_path_attempt(case, path_id, phase="DONE", outcome="SUCCEEDED")
                if self._all_selected_paths_terminal(case):
                    case.phase = OrchestrationPhase.FINAL_REVIEW
                    case.version += 1
                    case.updated_at = datetime.now(timezone.utc).isoformat()
                    self.repository.save(case, "case.phase_migrated", {
                        "from": OrchestrationPhase.PROFESSIONAL_COMMITMENT.value,
                        "to": OrchestrationPhase.FINAL_REVIEW.value,
                        "reason": "all selected Path approval DAGs are terminal",
                    })
                elif previous_attempt_states != [
                    (attempt.get("path_id"), attempt.get("phase"), attempt.get("outcome"))
                    for attempt in case.path_attempts
                ]:
                    case.version += 1
                    case.updated_at = datetime.now(timezone.utc).isoformat()
                    self.repository.save(case, "path_attempt.terminal_migrated", {
                        "reason": "derive terminal Path outcomes from existing approval DAG states",
                    })

    def list_cases(self):
        return self.repository.list_cases()

    def list_capabilities(self) -> dict:
        assets = self.capabilities.list_assets()
        return {
            "assets": assets,
            "counts": {group: len(items) for group, items in assets.items()},
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
        view["workflow_paths"] = [
            {
                "id": path.id,
                "definition": path.definition,
                "title": path.title,
                "selected": True,
                "rationale": "",
            }
            for path in (
                case.manifest.paths
                if case.manifest and case.phase in {
                    OrchestrationPhase.PATH_EXPLORATION,
                    OrchestrationPhase.PROFESSIONAL_COMMITMENT,
                    OrchestrationPhase.FINAL_REVIEW,
                }
                else ()
            )
            if path.selected
        ]
        if not can_view_manifest:
            view["manifest"] = None
            view["synthesis_report"] = None
            if view.get("owner_decision"):
                view["owner_decision"] = {
                    key: view["owner_decision"][key]
                    for key in ("action", "actor", "role", "synthesis_revision", "decided_at")
                    if key in view["owner_decision"]
                }
        view["permissions"] = {
            "can_view_manifest": can_view_manifest,
            "can_approve_manifest": can_view_manifest,
            "can_decide_case": can_view_manifest,
        }
        return view

    def get_case_manifest(self, case_id: str, *, actor: str, role: str) -> dict:
        case = self.get_case(case_id)
        self._require_case_owner(case, actor=actor, role=role)
        manifest = case.to_dict()["manifest"]
        if manifest is None:
            raise InvalidTransitionError("Manifest has not been generated")
        return manifest

    def get_case_timeline(self, case_id: str) -> list[dict]:
        self.get_case(case_id)
        public_fields = {
            "manifest.proposed": ("revision",),
            "manifest.approved": ("actor",),
            "solution_revision.proposed": ("path_id", "revision", "option_count"),
            "commitment.approved": ("actor", "role", "node_id", "path_id"),
            "commitment.revision_requested": ("actor", "role", "node_id", "path_id"),
            "commitment.rejected": ("actor", "role", "node_id", "path_id"),
            "synthesis.proposed": ("revision", "successful_path_count", "failed_path_count"),
            "owner.decision": ("actor", "role", "action", "synthesis_revision", "guidance"),
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
        run_id = f"RUN-{uuid4()}"
        adapter_profile = getattr(
            self.orchestrator.planner,
            "profile",
            type(self.orchestrator.planner).__name__,
        )
        self.repository.create_agent_run(
            run_id,
            case.id,
            agent_type="orchestrator",
            adapter_profile=adapter_profile,
            initiated_by=actor,
        )

        def trace(step: str, status: str, summary: str, details: dict | None = None) -> None:
            self.repository.append_agent_trace(
                run_id,
                step=step,
                status=status,
                summary=summary,
                details=details,
            )

        trace(
            "run.started",
            "STARTED",
            "Orchestrator AgentRun 已启动",
            {"agent_type": "orchestrator", "initiated_by": actor, "role": role},
        )
        try:
            manifest = await self.orchestrator.compose_manifest(case, trace)
        except Exception as exc:
            trace(
                "run.failed",
                "FAILED",
                "Orchestrator AgentRun 失败；Case 权威状态未修改",
                {"error_type": type(exc).__name__, "error": str(exc)},
            )
            self.repository.finish_agent_run(run_id, status="FAILED", error=exc)
            raise
        case.manifest = manifest
        case.phase = OrchestrationPhase.MANIFEST_REVIEW
        case.version += 1
        case.updated_at = datetime.now(timezone.utc).isoformat()
        self.repository.save(
            case,
            "manifest.proposed",
            {
                "manifest_id": manifest.id,
                "revision": manifest.revision,
                "planner_profile": manifest.planner_profile,
                "path_definitions": [path.definition for path in manifest.paths],
                "policy_refs": list(manifest.policy_refs),
            },
        )
        trace(
            "run.completed",
            "COMPLETED",
            "Manifest 已持久化，Case 进入 MANIFEST_REVIEW",
            {"manifest_id": manifest.id, "case_version": case.version, "phase": case.phase.value},
        )
        self.repository.finish_agent_run(
            run_id,
            status="SUCCEEDED",
            adapter_profile=manifest.planner_profile,
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
            case.manifest = replace(
                case.manifest,
                paths=tuple(replace(path, selected=path.id in selected) for path in case.manifest.paths),
            )
        selected_paths = [path for path in case.manifest.paths if path.selected]
        if not selected_paths:
            raise InvalidTransitionError("At least one Path must remain selected")

        snapshots = dict(case.manifest.capability_snapshots)
        for path in selected_paths:
            if path.id not in snapshots:
                if len(selected_paths) == 1 and case.manifest.capability_snapshot:
                    snapshots[path.id] = case.manifest.capability_snapshot
                else:
                    snapshots[path.id] = self._resolve_case_capabilities(case, path.id)
            if not snapshots[path.id]["compiled_policy"].get("commitments"):
                raise InvalidTransitionError(f"No mandatory commitments were compiled for Path {path.id}")
        case.manifest = replace(
            case.manifest,
            capability_snapshot=snapshots[selected_paths[0].id],
            capability_snapshots=snapshots,
        )

        case.phase = OrchestrationPhase.PATH_EXPLORATION
        attempts: list[dict] = []
        nodes: list[CommitmentNode] = []
        for index, path in enumerate(selected_paths, start=1):
            attempts.append({
                "id": f"ATTEMPT-{index:02d}",
                "path_id": path.id,
                "definition": path.definition,
                "title": path.title,
                "phase": "AWAITING_HUMAN",
                "outcome": None,
                "solution_revision": None,
            })
            nodes.extend(
                CommitmentNode(
                    id=item["id"],
                    role=item["role"],
                    node_type=item["node_type"],
                    status=NodeStatus.BLOCKED if item.get("depends_on") else NodeStatus.PENDING,
                    reviews=tuple(item["reviews"]),
                    depends_on=tuple(item.get("depends_on", [])),
                    path_id=path.id,
                )
                for item in snapshots[path.id]["compiled_policy"]["commitments"]
            )
        case.path_attempts = attempts
        case.path_attempt = attempts[0]
        case.commitment_nodes = nodes
        case.version += 1
        case.updated_at = datetime.now(timezone.utc).isoformat()
        self.repository.save(case, "manifest.approved", {
            "manifest_id": case.manifest.id,
            "revision": case.manifest.revision,
            "actor": actor,
            "path_attempt_ids": [attempt["id"] for attempt in attempts],
            "selected_path_ids": [path.id for path in selected_paths],
        })
        return case

    async def execute_paths(
        self,
        case_id: str,
        path_ids: list[str],
        *,
        actor: str,
        role: str,
    ):
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
                    return await self.execute_path(
                        case_id, path_id, actor=actor, role=role
                    )

            results = await asyncio.gather(*(
                execute_with_limit(path_id)
                for path_id in path_ids
            ), return_exceptions=True)
        else:
            results = []
            for path_id in path_ids:
                try:
                    results.append(await self.execute_path(
                        case_id, path_id, actor=actor, role=role
                    ))
                except Exception as exc:
                    results.append(exc)
                    break

        failure = next((result for result in results if isinstance(result, Exception)), None)
        if failure is not None:
            raise failure
        return self.get_case(case_id)

    async def execute_path(
        self,
        case_id: str,
        path_id: str,
        *,
        actor: str,
        role: str,
    ):
        case_snapshot = self.get_case(case_id)
        self._require_case_owner(case_snapshot, actor=actor, role=role)
        run_id = f"RUN-{uuid4()}"
        adapter_profile = getattr(
            self.path_agent.adapter,
            "profile",
            type(self.path_agent.adapter).__name__,
        )
        self.repository.create_agent_run(
            run_id,
            case_snapshot.id,
            agent_type="path",
            adapter_profile=adapter_profile,
            initiated_by=actor,
        )

        def trace(step: str, status: str, summary: str, details: dict | None = None) -> None:
            self.repository.append_agent_trace(
                run_id,
                step=step,
                status=status,
                summary=summary,
                details=details,
            )

        trace(
            "run.started",
            "STARTED",
            "Path AgentRun 已启动",
            {"agent_type": "path", "path_id": path_id, "initiated_by": actor, "role": role},
        )
        try:
            initial_attempt = next(
                attempt for attempt in case_snapshot.path_attempts
                if attempt.get("path_id") == path_id
            )
            initial_solution_revision = initial_attempt.get("solution_revision")
            solution_revision = await self.path_agent.run(case_snapshot, path_id, trace)

            lock = self._path_commit_locks.setdefault(case_id, asyncio.Lock())
            async with lock:
                case = self.get_case(case_id)
                self._require_case_owner(case, actor=actor, role=role)
                current_attempt = next(
                    attempt for attempt in case.path_attempts
                    if attempt.get("path_id") == path_id
                )
                if current_attempt.get("solution_revision") != initial_solution_revision:
                    raise InvalidTransitionError(
                        f"Path {path_id} changed while its Agent was running"
                    )
                case.path_attempts = [
                    {
                        **attempt,
                        "phase": "AWAITING_HUMAN",
                        "solution_revision": solution_revision,
                    }
                    if attempt.get("path_id") == path_id else attempt
                    for attempt in case.path_attempts
                ]
                case.path_attempt = next(
                    (dict(attempt) for attempt in case.path_attempts if attempt.get("path_id") == path_id),
                    case.path_attempt,
                )
                if all(attempt.get("solution_revision") for attempt in case.path_attempts):
                    case.phase = OrchestrationPhase.PROFESSIONAL_COMMITMENT
                ready_ids = {
                    node.id for node in case.commitment_nodes
                    if node.path_id == path_id and node.status is NodeStatus.READY
                }
                case.commitment_nodes = [
                    replace(
                        node,
                        status=NodeStatus.PENDING
                        if set(node.depends_on).issubset(ready_ids)
                        else NodeStatus.BLOCKED,
                    )
                    if node.path_id == path_id and node.status is NodeStatus.STALE
                    else node
                    for node in case.commitment_nodes
                ]
                case.version += 1
                case.updated_at = datetime.now(timezone.utc).isoformat()
                self.repository.save(case, "solution_revision.proposed", {
                    "path_id": path_id,
                    "revision": solution_revision["revision"],
                    "option_count": len(solution_revision["options"]),
                    "generated_by": solution_revision["generated_by"],
                    "next_phase": case.phase.value,
                })
        except Exception as exc:
            trace(
                "run.failed",
                "FAILED",
                "Path AgentRun 失败；Case 与 SolutionRevision 未修改",
                {"error_type": type(exc).__name__, "error": str(exc)},
            )
            self.repository.finish_agent_run(run_id, status="FAILED", error=exc)
            raise
        trace(
            "run.completed",
            "COMPLETED",
            "SolutionRevision 已持久化，等待人类责任节点评审",
            {
                "path_id": path_id,
                "revision": solution_revision["revision"],
                "case_version": case.version,
                "phase": case.phase.value,
            },
        )
        self.repository.finish_agent_run(
            run_id,
            status="SUCCEEDED",
            adapter_profile=solution_revision["generated_by"],
        )
        return case

    def get_inbox(self, role: str) -> list[dict]:
        items: list[dict] = []
        for case in self.repository.list_cases():
            if case.phase is not OrchestrationPhase.PROFESSIONAL_COMMITMENT:
                continue
            path_titles = {
                path.id: path.title for path in (case.manifest.paths if case.manifest else ())
            }
            for node in case.commitment_nodes:
                if node.role == role and node.status is NodeStatus.PENDING:
                    attempt = next(
                        (
                            item for item in case.path_attempts
                            if item.get("path_id") == node.path_id
                        ),
                        None,
                    )
                    revision = (
                        attempt.get("solution_revision")
                        if isinstance(attempt, dict)
                        and isinstance(attempt.get("solution_revision"), dict)
                        else None
                    )
                    snapshot = (
                        case.manifest.capability_snapshots.get(node.path_id, {})
                        if case.manifest else {}
                    )
                    commitment = next(
                        (
                            item
                            for item in snapshot.get("compiled_policy", {}).get("commitments", [])
                            if item.get("id") == node.id
                        ),
                        {},
                    )
                    report_contract = commitment.get("role_report", {})
                    role_report = next(
                        (
                            item for item in (revision or {}).get("role_reports", [])
                            if item.get("role") == node.role
                            and (
                                not report_contract.get("dimension")
                                or item.get("dimension") == report_contract.get("dimension")
                            )
                        ),
                        None,
                    )
                    items.append({
                        "case_id": case.id,
                        "case_title": case.title,
                        "path_id": node.path_id,
                        "path_title": path_titles.get(node.path_id, node.path_id),
                        "node": node,
                        "approval_context": {
                            "revision": revision.get("revision") if revision else None,
                            "summary": revision.get("summary", "") if revision else "",
                            "options": revision.get("options", []) if revision else [],
                            "recommendation": revision.get("recommendation", {}) if revision else {},
                            "role_report": role_report,
                        },
                    })
        return items

    def approve_commitment(
        self,
        case_id: str,
        path_id: str,
        node_id: str,
        *,
        actor: str,
        role: str,
    ):
        return self.decide_commitment(
            case_id,
            path_id,
            node_id,
            decision=CommitmentDecision.APPROVE,
            actor=actor,
            role=role,
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
        event_type: str
        if decision is CommitmentDecision.APPROVE:
            nodes[target_index] = replace(target, status=NodeStatus.READY)
            ready_ids = {
                node.id for node in nodes
                if node.path_id == path_id and node.status is NodeStatus.READY
            }
            nodes = [
                replace(node, status=NodeStatus.PENDING)
                if node.path_id == path_id
                and node.status is NodeStatus.BLOCKED
                and set(node.depends_on).issubset(ready_ids)
                else node
                for node in nodes
            ]
            event_type = "commitment.approved"
        elif decision is CommitmentDecision.REVISE:
            nodes[target_index] = replace(target, status=NodeStatus.STALE)
            event_type = "commitment.revision_requested"
            self._update_path_attempt(case, path_id, phase="REVISING", outcome=None)
            case.phase = OrchestrationPhase.PATH_EXPLORATION
        elif decision is CommitmentDecision.REJECT:
            nodes[target_index] = replace(target, status=NodeStatus.REJECTED)
            nodes = [
                replace(node, status=NodeStatus.STALE)
                if node.path_id == path_id
                and node.id != node_id
                and node.status in {NodeStatus.PENDING, NodeStatus.BLOCKED}
                else node
                for node in nodes
            ]
            event_type = "commitment.rejected"
            self._update_path_attempt(case, path_id, phase="DONE", outcome="REJECTED")
        else:
            raise InvalidTransitionError(f"Unsupported Commitment decision: {decision}")
        case.commitment_nodes = nodes
        for attempt in list(case.path_attempts):
            attempt_path_id = attempt.get("path_id")
            path_nodes = [node for node in nodes if node.path_id == attempt_path_id]
            if any(node.status is NodeStatus.REJECTED for node in path_nodes):
                self._update_path_attempt(case, attempt_path_id, phase="DONE", outcome="REJECTED")
            elif path_nodes and all(node.status is NodeStatus.READY for node in path_nodes):
                self._update_path_attempt(case, attempt_path_id, phase="DONE", outcome="SUCCEEDED")
        if self._all_selected_paths_terminal(case):
            case.phase = OrchestrationPhase.FINAL_REVIEW
        case.version += 1
        case.updated_at = datetime.now(timezone.utc).isoformat()
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
        attempts = {attempt.get("path_id"): attempt for attempt in case.path_attempts}
        return bool(selected_ids) and all(
            attempts.get(path_id, {}).get("phase") == "DONE"
            and attempts.get(path_id, {}).get("outcome") in {"SUCCEEDED", "REJECTED"}
            for path_id in selected_ids
        )

    async def synthesize_case(self, case_id: str, *, actor: str, role: str):
        case = self.get_case(case_id)
        self._require_case_owner(case, actor=actor, role=role)
        run_id = f"RUN-{uuid4()}"
        adapter_profile = getattr(
            self.synthesis_agent.adapter,
            "profile",
            type(self.synthesis_agent.adapter).__name__,
        )
        self.repository.create_agent_run(
            run_id,
            case.id,
            agent_type="synthesis",
            adapter_profile=adapter_profile,
            initiated_by=actor,
        )

        def trace(step: str, status: str, summary: str, details: dict | None = None) -> None:
            self.repository.append_agent_trace(
                run_id, step=step, status=status, summary=summary, details=details
            )

        trace("run.started", "STARTED", "Synthesis AgentRun 已启动", {
            "agent_type": "synthesis", "initiated_by": actor, "role": role
        })
        try:
            report = await self.synthesis_agent.run(case, trace)
        except Exception as exc:
            trace("run.failed", "FAILED", "Synthesis AgentRun 失败；CaseSynthesis 未修改", {
                "error_type": type(exc).__name__, "error": str(exc)
            })
            self.repository.finish_agent_run(run_id, status="FAILED", error=exc)
            raise
        case.synthesis_report = report
        case.owner_decision = None
        case.version += 1
        case.updated_at = datetime.now(timezone.utc).isoformat()
        successful = sum(
            item["status"] == "SUCCEEDED" for item in report["path_assessments"]
        )
        failed = len(report["path_assessments"]) - successful
        self.repository.save(case, "synthesis.proposed", {
            "revision": report["revision"],
            "successful_path_count": successful,
            "failed_path_count": failed,
            "generated_by": report["generated_by"],
        })
        trace("run.completed", "COMPLETED", "CaseSynthesis 已持久化，等待 Case Owner 最终决策", {
            "revision": report["revision"], "case_version": case.version
        })
        self.repository.finish_agent_run(
            run_id, status="SUCCEEDED", adapter_profile=report["generated_by"]
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
        previous_human_proposal = dict(case.human_proposal) if case.human_proposal else None
        decision = {
            "action": action.value,
            "actor": actor,
            "role": role,
            "synthesis_revision": case.synthesis_report["revision"],
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "synthesis_snapshot": dict(case.synthesis_report),
            "path_attempts_snapshot": [dict(attempt) for attempt in case.path_attempts],
            "commitments_snapshot": [asdict(node) for node in case.commitment_nodes],
        }
        if action is OwnerDecisionAction.MODIFY:
            decision["guidance"] = normalized_guidance
            decision["previous_human_proposal_snapshot"] = previous_human_proposal
        case.owner_decision = decision
        if action is OwnerDecisionAction.CLOSE:
            case.status = CaseStatus.CLOSED
        elif action is OwnerDecisionAction.KEEP_OPEN:
            case.status = CaseStatus.OPEN
        elif action is OwnerDecisionAction.MODIFY:
            case.human_proposal = {
                "revision": int((case.human_proposal or {}).get("revision", 0)) + 1,
                "author": actor,
                "role": role,
                "content": normalized_guidance,
            }
            case.status = CaseStatus.OPEN
            case.phase = OrchestrationPhase.INTAKE
            case.manifest = None
            case.path_attempt = None
            case.path_attempts = []
            case.commitment_nodes = []
            case.synthesis_report = None
        else:
            raise InvalidTransitionError(f"Unsupported Owner decision: {action}")
        case.version += 1
        case.updated_at = decision["decided_at"]
        self.repository.save(case, "owner.decision", decision)
        return case

    @staticmethod
    def _update_path_attempt(case, path_id: str, *, phase: str, outcome: str | None) -> None:
        case.path_attempts = [
            {**attempt, "phase": phase, "outcome": outcome}
            if attempt["path_id"] == path_id else attempt
            for attempt in case.path_attempts
        ]
        if case.path_attempt and case.path_attempt.get("path_id") == path_id:
            case.path_attempt = {**case.path_attempt, "phase": phase, "outcome": outcome}

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
            snapshot = case.manifest.capability_snapshots.get(target_path.id)
            if not snapshot and len(selected_paths) == 1:
                snapshot = case.manifest.capability_snapshot
        snapshot_status = "frozen"
        if not snapshot:
            snapshot = self._resolve_case_capabilities(case, target_path.id if target_path else None)
            snapshot_status = "preview"
        return {
            "snapshot_status": snapshot_status,
            "path_id": target_path.id if target_path else None,
            "available_paths": [path.id for path in selected_paths],
        } | self.capabilities.describe_snapshot(snapshot)

    def _resolve_case_capabilities(self, case, path_id: str | None = None) -> dict:
        selected_path = next(
            (
                path for path in (case.manifest.paths if case.manifest else ())
                if path.selected and (path_id is None or path.id == path_id)
            ),
            None,
        )
        if selected_path is None:
            raise InvalidTransitionError("Case has no selected Path for capability resolution")
        context = case.classification | {"path_definition": selected_path.definition}
        return self.capabilities.resolve(context).to_snapshot()
