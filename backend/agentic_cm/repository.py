from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .domain import (
    Case,
    CaseStatus,
    CommitmentNode,
    Manifest,
    ManifestPath,
    NodeStatus,
    OrchestrationPhase,
    PathAttempt,
    PathAttemptState,
)


class CaseRepository:
    """SQLite current state plus append-only domain events."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS domain_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    adapter_profile TEXT NOT NULL,
                    initiated_by TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    error_type TEXT,
                    error_message TEXT
                );
                CREATE TABLE IF NOT EXISTS agent_trace_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    step TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(run_id, sequence),
                    FOREIGN KEY(run_id) REFERENCES agent_runs(id)
                );
                """
            )

    def create_agent_run(
        self,
        run_id: str,
        case_id: str,
        *,
        agent_type: str,
        adapter_profile: str,
        initiated_by: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO agent_runs "
                "(id, case_id, agent_type, status, adapter_profile, initiated_by, started_at) "
                "VALUES (?, ?, ?, 'RUNNING', ?, ?, ?)",
                (run_id, case_id, agent_type, adapter_profile, initiated_by, self._now()),
            )

    def append_agent_trace(
        self,
        run_id: str,
        *,
        step: str,
        status: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
                "FROM agent_trace_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            connection.execute(
                "INSERT INTO agent_trace_events "
                "(run_id, sequence, step, status, summary, details, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    row["next_sequence"],
                    step,
                    status,
                    summary,
                    json.dumps(details or {}, ensure_ascii=False),
                    self._now(),
                ),
            )

    def finish_agent_run(
        self,
        run_id: str,
        *,
        status: str,
        adapter_profile: str | None = None,
        error: Exception | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE agent_runs SET status = ?, "
                "adapter_profile = COALESCE(?, adapter_profile), completed_at = ?, "
                "error_type = ?, error_message = ? WHERE id = ?",
                (
                    status,
                    adapter_profile,
                    self._now(),
                    type(error).__name__ if error else None,
                    str(error) if error else None,
                    run_id,
                ),
            )

    def list_agent_runs(self, case_id: str, *, agent_type: str | None = None) -> list[dict[str, Any]]:
        query = (
            "SELECT id, agent_type, status, adapter_profile, initiated_by, started_at, "
            "completed_at, error_type, error_message FROM agent_runs WHERE case_id = ?"
        )
        parameters: list[Any] = [case_id]
        if agent_type is not None:
            query += " AND agent_type = ?"
            parameters.append(agent_type)
        query += " ORDER BY started_at DESC, rowid DESC"
        with self._connect() as connection:
            runs = connection.execute(query, parameters).fetchall()
            result: list[dict[str, Any]] = []
            for run in runs:
                events = connection.execute(
                    "SELECT id, sequence, step, status, summary, details, created_at "
                    "FROM agent_trace_events WHERE run_id = ? ORDER BY sequence",
                    (run["id"],),
                ).fetchall()
                result.append({
                    "id": run["id"],
                    "agent_type": run["agent_type"],
                    "status": run["status"],
                    "adapter_profile": run["adapter_profile"],
                    "initiated_by": run["initiated_by"],
                    "started_at": self._utc_timestamp(run["started_at"]),
                    "completed_at": self._utc_timestamp(run["completed_at"]),
                    "error_type": run["error_type"],
                    "error_message": run["error_message"],
                    "events": [
                        {
                            "id": event["id"],
                            "sequence": event["sequence"],
                            "step": event["step"],
                            "status": event["status"],
                            "summary": event["summary"],
                            "details": json.loads(event["details"]),
                            "created_at": self._utc_timestamp(event["created_at"]),
                        }
                        for event in events
                    ],
                })
        return result

    @staticmethod
    def _utc_timestamp(value: str | None) -> str | None:
        if value is None:
            return None
        return datetime.fromisoformat(value.replace(" ", "T")).replace(tzinfo=timezone.utc).isoformat()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def list_cases(self) -> list[Case]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM cases ORDER BY id").fetchall()
        return [self._decode(json.loads(row["payload"])) for row in rows]

    def get(self, case_id: str) -> Case | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM cases WHERE id = ?", (case_id,)).fetchone()
        return self._decode(json.loads(row["payload"])) if row else None

    def has_event(self, case_id: str, event_type: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM domain_events WHERE case_id = ? AND event_type = ? LIMIT 1",
                (case_id, event_type),
            ).fetchone()
        return row is not None

    def list_events(self, case_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, event_type, payload, created_at "
                "FROM domain_events WHERE case_id = ? ORDER BY id",
                (case_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload"]),
                "created_at": datetime.fromisoformat(
                    row["created_at"].replace(" ", "T")
                ).replace(tzinfo=timezone.utc).isoformat(),
            }
            for row in rows
        ]

    def save(self, case: Case, event_type: str, event_payload: dict[str, Any]) -> None:
        serialized = json.dumps(case.to_dict(), ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO cases (id, payload, version) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, version=excluded.version",
                (case.id, serialized, case.version),
            )
            connection.execute(
                "INSERT INTO domain_events (case_id, event_type, payload) VALUES (?, ?, ?)",
                (case.id, event_type, json.dumps(event_payload, ensure_ascii=False)),
            )

    def reset(self, cases: list[Case]) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM cases")
            connection.execute("DELETE FROM domain_events")
            connection.execute("DELETE FROM agent_trace_events")
            connection.execute("DELETE FROM agent_runs")
            for case in cases:
                connection.execute(
                    "INSERT INTO cases (id, payload, version) VALUES (?, ?, ?)",
                    (case.id, json.dumps(case.to_dict(), ensure_ascii=False), case.version),
                )

    @staticmethod
    def _decode(data: dict[str, Any]) -> Case:
        manifest_data = data.get("manifest")
        manifest = None
        if manifest_data:
            snapshots = manifest_data.get("capability_snapshots", {})
            raw_paths = manifest_data["paths"]
            if not snapshots and manifest_data.get("capability_snapshot") and raw_paths:
                snapshots = {raw_paths[0]["id"]: manifest_data["capability_snapshot"]}
            paths = []
            for raw_path in raw_paths:
                path_payload = dict(raw_path)
                snapshot = snapshots.get(path_payload["id"])
                if snapshot and "skills" not in path_payload:
                    normalized = CaseRepository._normalize_capability_snapshot(snapshot)
                    payloads = normalized["asset_payloads"]
                    path_payload["skills"] = [
                        skill for skill in payloads.get("skills", [])
                        if path_payload["definition"]
                        in (skill.get("selector") or {}).get("path_definition", [])
                    ]
                    path_payload["knowledge"] = payloads.get("knowledge", [])
                    policies = [
                        CaseRepository._normalize_manifest_policy(policy)
                        for policy in payloads.get("policies", [])
                    ]
                    commitment_order = {
                        item["id"]: index
                        for index, item in enumerate(
                            normalized.get("compiled_policy", {}).get("commitments", [])
                        )
                    }
                    if commitment_order:
                        for policy in policies:
                            policy["commitments"].sort(
                                key=lambda item: commitment_order[item["id"]]
                            )
                        policies.sort(
                            key=lambda policy: min(
                                commitment_order[item["id"]]
                                for item in policy["commitments"]
                            )
                        )
                    path_payload["policies"] = policies
                path_payload.pop("title", None)
                for group in ("skills", "policies", "knowledge"):
                    path_payload[group] = [
                        CaseRepository._manifest_asset_ref(item)
                        for item in path_payload.get(group, [])
                    ]
                paths.append(ManifestPath.model_validate(path_payload))
            manifest = Manifest(
                id=manifest_data["id"], revision=manifest_data["revision"],
                paths=tuple(paths),
                knowledge=tuple(
                    CaseRepository._manifest_asset_ref(item)
                    for item in manifest_data.get("knowledge", [])
                ),
                generated_from_case_version=manifest_data.get("generated_from_case_version", 0),
            )
        nodes = [
            CommitmentNode(
                id=item["id"], role=item["role"],
                review_dimension=item.get("review_dimension")
                or item.get("role_report", {}).get("dimension")
                or item["role"],
                status=NodeStatus.READY if item["status"] == "COMMITTED" else NodeStatus(item["status"]),
                depends_on=tuple(item.get("depends_on", [])),
                path_id=item.get("path_id", ""),
            ) for item in data.get("commitment_nodes", [])
        ]
        raw_legacy_attempt = data.get("path_attempt")
        raw_attempts = data.get("path_attempts") or ([raw_legacy_attempt] if raw_legacy_attempt else [])
        path_attempts = [CaseRepository._normalize_path_attempt(item) for item in raw_attempts]
        raw_case_status = data["status"]
        return Case(
            id=data["id"], title=data["title"], description=data["description"],
            status=CaseStatus.OPEN if raw_case_status == "PENDING" else CaseStatus(raw_case_status),
            phase=OrchestrationPhase(data["phase"]), owner=data["owner"], owner_role=data["owner_role"],
            business_payload=data["business_payload"], human_proposal=data.get("human_proposal"),
            classification=data.get("classification", {}), manifest=manifest,
            path_attempts=path_attempts,
            commitment_nodes=nodes,
            synthesis_report=data.get("synthesis_report"),
            owner_decision=CaseRepository._normalize_owner_decision(data.get("owner_decision")),
            version=data["version"],
            created_at=data.get("created_at", data["updated_at"]), updated_at=data["updated_at"],
        )

    @staticmethod
    def _manifest_asset_ref(payload: dict[str, Any]) -> dict[str, str]:
        resolved = payload.get("resolved_ref")
        ref = resolved if isinstance(resolved, dict) else payload
        return {
            "id": str(ref.get("id") or payload.get("id") or "legacy-unverified"),
            "version": str(
                ref.get("version") or payload.get("version") or "legacy-unverified"
            ),
            "digest": str(
                ref.get("digest") or payload.get("digest") or "legacy-unverified"
            ),
        }

    @staticmethod
    def _normalize_path_attempt(value: Any) -> PathAttempt:
        """Read legacy PathAttempt shapes into the single authoritative state field."""
        attempt = dict(value) if isinstance(value, dict) else {}
        revision = attempt.get("solution_revision")
        if not isinstance(revision, dict) or not isinstance(revision.get("options"), list):
            revision = None
        else:
            revision = {
                key: item for key, item in revision.items()
                if key not in {"path_id", "path_definition", "required_commitment_ids", "manifest_ref"}
            }
        raw_state = attempt.get("state")
        if raw_state in {item.value for item in PathAttemptState}:
            state = PathAttemptState(raw_state)
        elif attempt.get("phase") == "DONE" and attempt.get("outcome") == "SUCCEEDED":
            state = PathAttemptState.SUCCEEDED
        elif attempt.get("phase") == "DONE" and attempt.get("outcome") in {"REJECTED", "FAILED"}:
            state = PathAttemptState.REJECTED
        elif attempt.get("phase") == "REVISING":
            state = PathAttemptState.REVISING
        elif revision:
            state = PathAttemptState.AWAITING_COMMITMENT
        else:
            state = PathAttemptState.PLANNED
        return PathAttempt(
            path_id=str(attempt.get("path_id", "")),
            state=state,
            solution_revision=revision,
        )

    @staticmethod
    def _normalize_capability_snapshot(value: Any) -> dict[str, Any]:
        snapshot = dict(value) if isinstance(value, dict) else {}
        payloads = json.loads(json.dumps(snapshot.get("asset_payloads", {}), ensure_ascii=False))
        for group_items in payloads.values():
            for asset in group_items:
                for removed in ("kind", "status", "purpose", "entrypoint"):
                    asset.pop(removed, None)
        for policy in payloads.get("policies", []):
            for commitment in policy.get("requirements", {}).get("commitments", []):
                report = commitment.pop("role_report", {})
                commitment.pop("reviews", None)
                commitment.setdefault("review_dimension", report.get("dimension") or commitment.get("role", ""))
        compiled = json.loads(json.dumps(snapshot.get("compiled_policy", {}), ensure_ascii=False))
        for commitment in compiled.get("commitments", []):
            report = commitment.pop("role_report", {})
            commitment.pop("reviews", None)
            commitment.setdefault("review_dimension", report.get("dimension") or commitment.get("role", ""))
        return {
            "schema_version": snapshot.get("schema_version", 1),
            "context": dict(snapshot.get("context", {})),
            "compiled_policy": compiled,
            "asset_payloads": payloads,
        }

    @staticmethod
    def _normalize_manifest_policy(policy: dict[str, Any]) -> dict[str, Any]:
        normalized = json.loads(json.dumps(policy, ensure_ascii=False))
        requirements = normalized.pop("requirements", {})
        normalized["commitments"] = list(requirements.get("commitments", []))
        return normalized

    @staticmethod
    def _normalize_owner_decision(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        return {
            key: value[key]
            for key in ("action", "actor", "role", "synthesis_revision", "decided_at")
            if key in value
        }
