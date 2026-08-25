from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .domain import Case, CaseStatus, CommitmentNode, Manifest, ManifestPath, NodeStatus, OrchestrationPhase


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
            paths = tuple(ManifestPath(**item) for item in manifest_data["paths"])
            snapshots = manifest_data.get("capability_snapshots", {})
            if not snapshots and manifest_data.get("capability_snapshot") and paths:
                snapshots = {paths[0].id: manifest_data["capability_snapshot"]}
            manifest = Manifest(
                id=manifest_data["id"], revision=manifest_data["revision"], status=manifest_data["status"],
                paths=paths,
                policy_refs=tuple(manifest_data["policy_refs"]),
                skill_refs=tuple(manifest_data.get("skill_refs", [])),
                knowledge_refs=tuple(manifest_data.get("knowledge_refs", manifest_data.get("experience_refs", []))),
                experience_refs=tuple(manifest_data.get("experience_refs", [])),
                capability_snapshot=manifest_data.get("capability_snapshot"),
                planner_profile=manifest_data.get("planner_profile", "unknown"),
                generated_from_case_version=manifest_data.get("generated_from_case_version", 0),
                capability_snapshots=snapshots,
            )
        nodes = [
            CommitmentNode(
                id=item["id"], role=item["role"], node_type=item["node_type"],
                status=NodeStatus(item["status"]), reviews=tuple(item["reviews"]),
                depends_on=tuple(item.get("depends_on", [])),
                path_id=item.get("path_id", ""),
            ) for item in data.get("commitment_nodes", [])
        ]
        raw_legacy_attempt = data.get("path_attempt")
        raw_attempts = data.get("path_attempts") or ([raw_legacy_attempt] if raw_legacy_attempt else [])
        path_attempts = [CaseRepository._normalize_path_attempt(item) for item in raw_attempts]
        legacy_attempt = None
        if raw_legacy_attempt:
            legacy_path_id = raw_legacy_attempt.get("path_id")
            legacy_attempt = next(
                (item for item in path_attempts if item.get("path_id") == legacy_path_id),
                CaseRepository._normalize_path_attempt(raw_legacy_attempt),
            )
        return Case(
            id=data["id"], title=data["title"], description=data["description"], status=CaseStatus(data["status"]),
            phase=OrchestrationPhase(data["phase"]), owner=data["owner"], owner_role=data["owner_role"],
            business_payload=data["business_payload"], human_proposal=data.get("human_proposal"),
            classification=data.get("classification", {}), manifest=manifest,
            path_attempt=legacy_attempt, path_attempts=path_attempts,
            commitment_nodes=nodes,
            synthesis_report=data.get("synthesis_report"),
            owner_decision=data.get("owner_decision"),
            version=data["version"],
            created_at=data.get("created_at", data["updated_at"]), updated_at=data["updated_at"],
        )

    @staticmethod
    def _normalize_path_attempt(value: Any) -> dict[str, Any]:
        """Read old demo rows where solution_revision was only a revision number."""
        attempt = dict(value) if isinstance(value, dict) else {}
        revision = attempt.get("solution_revision")
        if not isinstance(revision, dict) or not isinstance(revision.get("options"), list):
            attempt["solution_revision"] = None
        return attempt
