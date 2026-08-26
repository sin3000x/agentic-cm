"""AgentRun bookkeeping shared by every Agent invocation.

Each Agent call must open a run, emit an ordered trace, and close the run as
SUCCEEDED or FAILED — including when the Agent raises, so a failed run keeps
its audit trail while the Case stays untouched. This was duplicated verbatim
for the Orchestrator, Path, and Synthesis calls in CaseService.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4


class AgentRunStore(Protocol):
    """The persistence surface an AgentRun needs."""

    def create_agent_run(
        self,
        run_id: str,
        case_id: str,
        *,
        agent_type: str,
        adapter_profile: str,
        initiated_by: str,
    ) -> None: ...

    def append_agent_trace(
        self,
        run_id: str,
        *,
        step: str,
        status: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> None: ...

    def finish_agent_run(
        self,
        run_id: str,
        *,
        status: str,
        adapter_profile: str | None = None,
        error: BaseException | None = None,
    ) -> None: ...


def adapter_profile_of(adapter: object) -> str:
    """The adapter's self-reported profile, falling back to its class name."""
    return getattr(adapter, "profile", type(adapter).__name__)


@dataclass
class AgentRun:
    """A single in-flight Agent invocation.

    `trace` is passed to the Agent so its own steps land in the same run.
    """

    run_id: str
    _store: AgentRunStore

    def trace(
        self,
        step: str,
        status: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._store.append_agent_trace(
            self.run_id,
            step=step,
            status=status,
            summary=summary,
            details=details,
        )

    def complete(
        self,
        summary: str,
        details: dict[str, Any],
        *,
        adapter_profile: str,
    ) -> None:
        """Trace the closing step and mark the run SUCCEEDED.

        `adapter_profile` is the profile the Agent actually ran under, which for
        a model-backed Agent names the concrete model.
        """
        self.trace("run.completed", "COMPLETED", summary, details)
        self._store.finish_agent_run(
            self.run_id, status="SUCCEEDED", adapter_profile=adapter_profile
        )


@asynccontextmanager
async def agent_run(
    store: AgentRunStore,
    case_id: str,
    *,
    agent_type: str,
    adapter: object,
    actor: str,
    role: str,
    started_summary: str,
    failed_summary: str,
    started_details: dict[str, Any] | None = None,
):
    """Open an AgentRun, yield it, and close it exactly once.

    On success the caller must call `run.complete(...)`. If the body raises,
    the failure is traced, the run is marked FAILED, and the exception
    propagates so the caller's Case state is left untouched.
    """
    run_id = f"RUN-{uuid4()}"
    store.create_agent_run(
        run_id,
        case_id,
        agent_type=agent_type,
        adapter_profile=adapter_profile_of(adapter),
        initiated_by=actor,
    )
    run = AgentRun(run_id, store)
    run.trace(
        "run.started",
        "STARTED",
        started_summary,
        {"agent_type": agent_type, "initiated_by": actor, "role": role}
        | (started_details or {}),
    )
    try:
        yield run
    except Exception as exc:
        run.trace(
            "run.failed",
            "FAILED",
            failed_summary,
            {"error_type": type(exc).__name__, "error": str(exc)},
        )
        store.finish_agent_run(run_id, status="FAILED", error=exc)
        raise
