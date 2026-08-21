from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from .capabilities import CapabilityRegistry, default_registry
from .demo import demo_cases
from .domain import CommitmentNode, NodeStatus, OrchestrationPhase
from .orchestrator import Orchestrator, PlannerAdapter, planner_from_environment
from .repository import CaseRepository


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
    ) -> None:
        self.repository = repository
        self.capabilities = capabilities or default_registry()
        self.orchestrator = Orchestrator(
            self.capabilities,
            planner or planner_from_environment(),
        )

    def ensure_demo_data(self) -> None:
        if not self.repository.list_cases():
            self.repository.reset(demo_cases())
            return
        for case in self.repository.list_cases():
            if (
                case.phase is OrchestrationPhase.PATH_EXPLORATION
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

    def list_cases(self):
        return self.repository.list_cases()

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
        if not can_view_manifest:
            view["manifest"] = None
        view["permissions"] = {
            "can_view_manifest": can_view_manifest,
            "can_approve_manifest": can_view_manifest,
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
            "commitment.approved": ("actor", "role", "node_id", "path_id"),
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

    async def orchestrate_case(self, case_id: str, *, actor: str, role: str):
        case = self.get_case(case_id)
        self._require_case_owner(case, actor=actor, role=role)
        manifest = await self.orchestrator.compose_manifest(case)
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
                "phase": "AWAITING_HUMAN",
                "outcome": None,
                "solution_revision": 1,
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

    def get_inbox(self, role: str) -> list[dict]:
        items: list[dict] = []
        for case in self.repository.list_cases():
            path_titles = {
                path.id: path.title for path in (case.manifest.paths if case.manifest else ())
            }
            for node in case.commitment_nodes:
                if node.role == role and node.status is NodeStatus.PENDING:
                    items.append({
                        "case_id": case.id,
                        "case_title": case.title,
                        "path_id": node.path_id,
                        "path_title": path_titles.get(node.path_id, node.path_id),
                        "node": node,
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
        case = self.get_case(case_id)
        if case.phase is not OrchestrationPhase.PATH_EXPLORATION:
            raise InvalidTransitionError("Case is not exploring a Path")
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
            raise InvalidTransitionError("Commitment approval requires an actor")

        nodes = list(case.commitment_nodes)
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
        case.commitment_nodes = nodes
        case.version += 1
        case.updated_at = datetime.now(timezone.utc).isoformat()
        self.repository.save(case, "commitment.approved", {
            "path_id": path_id,
            "node_id": node_id,
            "actor": actor,
            "role": role,
        })
        return case

    def reset_demo(self, dataset_id: str):
        if dataset_id != "supply-chain-golden-path-v1":
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
