from __future__ import annotations

import json
import sqlite3
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
                """
            )

    def list_cases(self) -> list[Case]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM cases ORDER BY id").fetchall()
        return [self._decode(json.loads(row["payload"])) for row in rows]

    def get(self, case_id: str) -> Case | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM cases WHERE id = ?", (case_id,)).fetchone()
        return self._decode(json.loads(row["payload"])) if row else None

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
        legacy_attempt = data.get("path_attempt")
        path_attempts = data.get("path_attempts") or ([legacy_attempt] if legacy_attempt else [])
        return Case(
            id=data["id"], title=data["title"], description=data["description"], status=CaseStatus(data["status"]),
            phase=OrchestrationPhase(data["phase"]), owner=data["owner"], owner_role=data["owner_role"],
            business_payload=data["business_payload"], human_proposal=data.get("human_proposal"),
            classification=data.get("classification", {}), manifest=manifest,
            path_attempt=legacy_attempt, path_attempts=path_attempts,
            commitment_nodes=nodes, version=data["version"], updated_at=data["updated_at"],
        )
