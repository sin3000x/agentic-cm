from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import load_runtime_environment
from .orchestrator import OrchestrationError
from .repository import CaseRepository
from .service import CaseNotFoundError, CaseService, InvalidTransitionError


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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/cases")
def list_cases():
    return [case.to_dict() for case in service.list_cases()]


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    try:
        return service.get_case(case_id).to_dict()
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc


@app.get("/api/cases/{case_id}/capabilities")
def get_case_capabilities(case_id: str, path_id: str | None = None):
    try:
        return service.get_case_capabilities(case_id, path_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/cases/{case_id}/manifest")
def get_case_manifest(case_id: str):
    try:
        manifest = service.get_case_manifest(case_id)
        return manifest
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/cases/{case_id}/orchestrate")
async def orchestrate_case(case_id: str):
    try:
        return (await service.orchestrate_case(case_id)).to_dict()
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc
    except OrchestrationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/cases/{case_id}/manifest/approve")
def approve_manifest(case_id: str, request: ManifestApprovalRequest | None = None):
    try:
        return service.approve_manifest(
            case_id,
            request.selected_path_ids if request else None,
        ).to_dict()
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
