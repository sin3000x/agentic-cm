from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import load_runtime_environment
from .domain import CommitmentDecision
from .orchestrator import OrchestrationError
from .path_agent import PathAgentError, PathAgentExecutionError
from .repository import CaseRepository
from .service import AuthorizationError, CaseNotFoundError, CaseService, InvalidTransitionError


load_runtime_environment()
DATABASE_PATH = Path(os.getenv("AGENTIC_CM_DB", "data/agentic_cm.db"))
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
service = CaseService(CaseRepository(DATABASE_PATH))
service.ensure_demo_data()

app = FastAPI(title="Agentic Case Management API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class ResetRequest(BaseModel):
    dataset_id: str


class ManifestApprovalRequest(BaseModel):
    selected_path_ids: list[str]
    actor: str
    role: str


class OwnerActionRequest(BaseModel):
    actor: str
    role: str


class CommitmentApprovalRequest(BaseModel):
    actor: str
    role: str


class CommitmentDecisionRequest(CommitmentApprovalRequest):
    decision: CommitmentDecision


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/cases")
def list_cases(actor: str | None = None, role: str | None = None):
    return [service.get_case_view(case.id, actor=actor, role=role) for case in service.list_cases()]


@app.get("/api/capabilities")
def list_capabilities():
    return service.list_capabilities()


@app.get("/api/cases/{case_id}")
def get_case(case_id: str, actor: str | None = None, role: str | None = None):
    try:
        return service.get_case_view(case_id, actor=actor, role=role)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc


@app.get("/api/cases/{case_id}/capabilities")
def get_case_capabilities(case_id: str, actor: str, role: str, path_id: str | None = None):
    try:
        service.get_case_manifest(case_id, actor=actor, role=role)
        return service.get_case_capabilities(case_id, path_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/cases/{case_id}/manifest")
def get_case_manifest(case_id: str, actor: str, role: str):
    try:
        manifest = service.get_case_manifest(case_id, actor=actor, role=role)
        return manifest
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/cases/{case_id}/timeline")
def get_case_timeline(case_id: str):
    try:
        return service.get_case_timeline(case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc


@app.get("/api/cases/{case_id}/agent-runs")
def get_case_agent_runs(
    case_id: str,
    actor: str,
    role: str,
    agent_type: str | None = None,
):
    try:
        return service.get_agent_runs(
            case_id,
            actor=actor,
            role=role,
            agent_type=agent_type,
        )
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/cases/{case_id}/orchestrate")
async def orchestrate_case(case_id: str, request: OwnerActionRequest):
    try:
        return (await service.orchestrate_case(
            case_id,
            actor=request.actor,
            role=request.role,
        )).to_dict()
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc
    except OrchestrationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/api/cases/{case_id}/manifest/approve")
def approve_manifest(case_id: str, request: ManifestApprovalRequest):
    try:
        return service.approve_manifest(
            case_id,
            request.selected_path_ids,
            actor=request.actor,
            role=request.role,
        ).to_dict()
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/api/cases/{case_id}/paths/{path_id}/execute")
async def execute_path(case_id: str, path_id: str, request: OwnerActionRequest):
    try:
        return (await service.execute_path(
            case_id,
            path_id,
            actor=request.actor,
            role=request.role,
        )).to_dict()
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc
    except PathAgentExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except PathAgentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/inbox")
def get_inbox(role: str):
    return service.get_inbox(role)


@app.post("/api/cases/{case_id}/paths/{path_id}/commitments/{node_id}/approve")
def approve_commitment(
    case_id: str,
    path_id: str,
    node_id: str,
    request: CommitmentApprovalRequest,
):
    try:
        service.approve_commitment(
            case_id,
            path_id,
            node_id,
            actor=request.actor,
            role=request.role,
        )
        return service.get_case_view(case_id, actor=request.actor, role=request.role)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/cases/{case_id}/paths/{path_id}/commitments/{node_id}/decision")
def decide_commitment(
    case_id: str,
    path_id: str,
    node_id: str,
    request: CommitmentDecisionRequest,
):
    try:
        service.decide_commitment(
            case_id,
            path_id,
            node_id,
            decision=request.decision,
            actor=request.actor,
            role=request.role,
        )
        return service.get_case_view(case_id, actor=request.actor, role=request.role)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/demo/reset", status_code=204)
def reset_demo(request: ResetRequest):
    try:
        service.reset_demo(request.dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
