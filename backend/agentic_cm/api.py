from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .agent_runtime import AgentError, AgentExecutionError
from .config import load_runtime_environment
from .domain import CommitmentDecision, Manifest, OwnerDecisionAction
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


class PathExecutionRequest(OwnerActionRequest):
    path_ids: list[str]


class CommitmentApprovalRequest(BaseModel):
    actor: str
    role: str


class CommitmentDecisionRequest(CommitmentApprovalRequest):
    decision: CommitmentDecision


class OwnerDecisionRequest(OwnerActionRequest):
    action: OwnerDecisionAction
    guidance: str | None = None


@app.exception_handler(CaseNotFoundError)
async def case_not_found_handler(_request: Request, exc: CaseNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Case not found"})


@app.exception_handler(AuthorizationError)
async def authorization_handler(_request: Request, exc: AuthorizationError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(InvalidTransitionError)
async def invalid_transition_handler(_request: Request, exc: InvalidTransitionError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(AgentExecutionError)
async def agent_execution_handler(_request: Request, exc: AgentExecutionError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(AgentError)
async def agent_error_handler(_request: Request, exc: AgentError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/runtime-config")
def runtime_config() -> dict[str, str | int]:
    return {
        "path_execution_mode": service.path_execution_mode,
        "path_max_concurrency": service.path_max_concurrency,
    }


@app.get("/api/cases")
def list_cases(actor: str | None = None, role: str | None = None):
    return [service.get_case_view(case.id, actor=actor, role=role) for case in service.list_cases()]


@app.get("/api/capabilities")
def list_capabilities():
    return service.list_capabilities()


@app.get("/api/cases/{case_id}")
def get_case(case_id: str, actor: str | None = None, role: str | None = None):
    return service.get_case_view(case_id, actor=actor, role=role)


@app.get("/api/cases/{case_id}/capabilities")
def get_case_capabilities(case_id: str, actor: str, role: str, path_id: str | None = None):
    service.get_case_manifest(case_id, actor=actor, role=role)
    return service.get_case_capabilities(case_id, path_id)


@app.get("/api/cases/{case_id}/manifest")
def get_case_manifest(case_id: str, actor: str, role: str):
    return service.get_case_manifest(case_id, actor=actor, role=role)


@app.get("/api/cases/{case_id}/manifest.yaml")
def download_case_manifest(case_id: str, actor: str, role: str):
    manifest = Manifest.model_validate(service.get_case_manifest(case_id, actor=actor, role=role))
    return Response(
        content=manifest.to_yaml(),
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="{manifest.id}.yaml"'},
    )


@app.get("/api/cases/{case_id}/timeline")
def get_case_timeline(case_id: str):
    return service.get_case_timeline(case_id)


@app.get("/api/cases/{case_id}/agent-runs")
def get_case_agent_runs(
    case_id: str,
    actor: str,
    role: str,
    agent_type: str | None = None,
):
    try:
        return service.get_agent_runs(case_id, actor=actor, role=role, agent_type=agent_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/cases/{case_id}/orchestrate")
async def orchestrate_case(case_id: str, request: OwnerActionRequest):
    await service.orchestrate_case(case_id, actor=request.actor, role=request.role)
    return service.get_case_view(case_id, actor=request.actor, role=request.role)


@app.post("/api/cases/{case_id}/manifest/approve")
def approve_manifest(case_id: str, request: ManifestApprovalRequest):
    service.approve_manifest(
        case_id,
        request.selected_path_ids,
        actor=request.actor,
        role=request.role,
    )
    return service.get_case_view(case_id, actor=request.actor, role=request.role)


@app.post("/api/cases/{case_id}/paths/{path_id}/execute")
async def execute_path(case_id: str, path_id: str, request: OwnerActionRequest):
    case = await service.execute_path(case_id, path_id, actor=request.actor, role=request.role)
    return case.to_dict()


@app.post("/api/cases/{case_id}/paths/execute")
async def execute_paths(case_id: str, request: PathExecutionRequest):
    case = await service.execute_paths(
        case_id, request.path_ids, actor=request.actor, role=request.role
    )
    return {
        "execution_mode": service.path_execution_mode,
        "max_concurrency": service.path_max_concurrency,
        "case": case.to_dict(),
    }


@app.get("/api/inbox")
def get_inbox(role: str):
    return service.get_inbox(role)


@app.post("/api/cases/{case_id}/synthesize")
async def synthesize_case(case_id: str, request: OwnerActionRequest):
    case = await service.synthesize_case(case_id, actor=request.actor, role=request.role)
    return case.to_dict()


@app.post("/api/cases/{case_id}/owner-decision")
def decide_case(case_id: str, request: OwnerDecisionRequest):
    service.decide_case(
        case_id,
        action=request.action,
        actor=request.actor,
        role=request.role,
        guidance=request.guidance,
    )
    return service.get_case_view(case_id, actor=request.actor, role=request.role)


@app.post("/api/cases/{case_id}/paths/{path_id}/commitments/{node_id}/approve")
def approve_commitment(
    case_id: str,
    path_id: str,
    node_id: str,
    request: CommitmentApprovalRequest,
):
    service.approve_commitment(case_id, path_id, node_id, actor=request.actor, role=request.role)
    return service.get_case_view(case_id, actor=request.actor, role=request.role)


@app.post("/api/cases/{case_id}/paths/{path_id}/commitments/{node_id}/decision")
def decide_commitment(
    case_id: str,
    path_id: str,
    node_id: str,
    request: CommitmentDecisionRequest,
):
    service.decide_commitment(
        case_id,
        path_id,
        node_id,
        decision=request.decision,
        actor=request.actor,
        role=request.role,
    )
    return service.get_case_view(case_id, actor=request.actor, role=request.role)


@app.post("/api/demo/reset", status_code=204)
def reset_demo(request: ResetRequest):
    try:
        service.reset_demo(request.dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
