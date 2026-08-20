from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import httpx

from .capabilities import CapabilityRegistry
from .config import load_runtime_environment
from .domain import Case, Manifest, ManifestPath, OrchestrationPhase


class OrchestrationError(ValueError):
    pass


class PlannerOutputError(OrchestrationError):
    pass


class PlannerExecutionError(OrchestrationError):
    pass


@dataclass(frozen=True)
class PlanningCandidate:
    definition: str
    title: str
    description: str
    policy_ids: tuple[str, ...]
    skill_ids: tuple[str, ...]
    knowledge_ids: tuple[str, ...]
    mandatory_commitment_ids: tuple[str, ...]
    skill_guidance: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class PlanningContext:
    case_id: str
    case_version: int
    title: str
    description: str
    classification: dict[str, str]
    business_payload: dict[str, Any]
    human_proposal: dict[str, Any] | None


@dataclass(frozen=True)
class PlannedPath:
    definition: str
    rationale: str


@dataclass(frozen=True)
class ManifestDraftResult:
    paths: tuple[PlannedPath, ...]
    planner_profile: str


class PlannerAdapter(Protocol):
    async def propose(
        self, context: PlanningContext, candidates: tuple[PlanningCandidate, ...]
    ) -> ManifestDraftResult: ...


class DeterministicPlannerAdapter:
    """Reproducible adapter used for tests and keyless local development."""

    async def propose(
        self, context: PlanningContext, candidates: tuple[PlanningCandidate, ...]
    ) -> ManifestDraftResult:
        if not candidates:
            raise OrchestrationError("No compatible PathDefinition has applicable mandatory Policy")
        return ManifestDraftResult(
            paths=tuple(
                PlannedPath(
                    candidate.definition,
                    f"{candidate.title}由命中的编排 Skill 声明；"
                    "deterministic 模式不判断当前 Case 的业务优先级。",
                )
                for candidate in candidates
            ),
            planner_profile="deterministic/v1",
        )


class OpenAICompatiblePlannerAdapter:
    """Provider-neutral Chat Completions adapter; it owns no Case or workflow state."""

    def __init__(
        self,
        api_key: str | None,
        *,
        model: str,
        base_url: str,
        api_key_header: str = "Authorization",
        api_key_prefix: str = "Bearer",
        timeout_seconds: float = 45.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not model.strip():
            raise OrchestrationError("A model id is required for the OpenAI-compatible planner")
        if not base_url.strip():
            raise OrchestrationError("A base URL is required for the OpenAI-compatible planner")
        parsed_url = httpx.URL(base_url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.host:
            raise OrchestrationError("The OpenAI-compatible base URL must be an absolute HTTP(S) URL")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._api_key_header = api_key_header
        self._api_key_prefix = api_key_prefix
        self._timeout = timeout_seconds
        self._client = client

    async def propose(
        self, context: PlanningContext, candidates: tuple[PlanningCandidate, ...]
    ) -> ManifestDraftResult:
        request = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an enterprise exception Case planning component. Return JSON only. "
                        "Return every provided candidate definition exactly once, with a Case-specific rationale. "
                        "You may order them by relevance. Never invent or omit ids, remove policies, "
                        "make business commitments, or claim operational actions. "
                        'Schema: {"paths":[{"definition":"candidate id","rationale":"concise reason"}]}'
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"case": asdict(context), "candidates": [asdict(item) for item in candidates]},
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 800,
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            credential = f"{self._api_key_prefix} {self._api_key}".strip()
            headers[self._api_key_header] = credential
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                if self._client is not None:
                    response = await self._client.post(
                        f"{self._base_url}/chat/completions", json=request, headers=headers, timeout=self._timeout
                    )
                else:
                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            f"{self._base_url}/chat/completions", json=request, headers=headers, timeout=self._timeout
                        )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else "unavailable"
                raise PlannerExecutionError(f"Model planning request failed (status={status})") from exc
            try:
                envelope = response.json()
                content = envelope["choices"][0]["message"]["content"]
                payload = json.loads(content)
                paths = _parse_planned_paths(payload)
                return ManifestDraftResult(paths=paths, planner_profile=f"openai-compatible/{self._model}")
            except (KeyError, IndexError, TypeError, json.JSONDecodeError, PlannerOutputError) as exc:
                last_error = exc
                if attempt == 0:
                    request["messages"].append({
                        "role": "system",
                        "content": "The previous output was invalid. Return one non-empty JSON object matching the exact schema.",
                    })
        raise PlannerOutputError("Model returned an invalid JSON planning result after one repair") from last_error


def _parse_planned_paths(payload: Any) -> tuple[PlannedPath, ...]:
    if not isinstance(payload, dict) or set(payload) != {"paths"} or not isinstance(payload["paths"], list):
        raise PlannerOutputError("Planner result must contain only a paths array")
    paths: list[PlannedPath] = []
    for item in payload["paths"]:
        if not isinstance(item, dict) or set(item) != {"definition", "rationale"} or not all(
            isinstance(item[field], str) and item[field].strip() for field in ("definition", "rationale")
        ):
            raise PlannerOutputError("Each planned Path requires definition and rationale")
        paths.append(PlannedPath(item["definition"], item["rationale"].strip()))
    if not paths:
        raise PlannerOutputError("Planner must select at least one Path")
    definitions = [path.definition for path in paths]
    if len(set(definitions)) != len(definitions):
        raise PlannerOutputError("Planner selected the same Path more than once")
    return tuple(paths)


class Orchestrator:
    def __init__(
        self,
        capabilities: CapabilityRegistry,
        planner: PlannerAdapter,
    ) -> None:
        self.capabilities = capabilities
        self.planner = planner

    async def compose_manifest(self, case: Case) -> Manifest:
        if case.phase is not OrchestrationPhase.INTAKE or case.manifest is not None:
            raise OrchestrationError("Case is not eligible for initial orchestration")
        if case.status.value != "OPEN":
            raise OrchestrationError("Only OPEN Cases can be orchestrated")

        definitions = self.capabilities.resolve_path_candidates(case.classification)
        resolutions: dict[str, Any] = {}
        eligible: list[tuple[Any, Any]] = []
        incomplete: dict[str, list[str]] = {}
        for definition in definitions:
            resolution = self.capabilities.resolve(
                case.classification | {"path_definition": definition.id}
            )
            path_level_skills = [
                payload for payload in resolution.asset_payloads["skills"]
                if definition.id in (payload.get("selector") or {}).get("path_definition", [])
            ]
            missing: list[str] = []
            if not path_level_skills:
                missing.append("execution Skill")
            if not resolution.compiled_policy.get("commitments"):
                missing.append("mandatory Policy")
            if missing:
                incomplete[definition.id] = missing
            else:
                resolutions[definition.id] = resolution
                eligible.append((definition, resolution))
        if incomplete:
            raise OrchestrationError(
                f"Skill-declared Paths are not executable: {incomplete}"
            )
        candidates = tuple(
            PlanningCandidate(
                definition=definition.id,
                title=definition.title,
                description=definition.description,
                policy_ids=tuple(ref.id for ref in resolution.policies),
                skill_ids=tuple(ref.id for ref in resolution.skills),
                knowledge_ids=tuple(ref.id for ref in resolution.knowledge),
                mandatory_commitment_ids=tuple(
                    item["id"] for item in resolution.compiled_policy["commitments"]
                ),
                skill_guidance=tuple(
                    {
                        "id": payload["id"],
                        "description": payload["description"],
                        "instructions_markdown": payload["instructions_markdown"],
                    }
                    for payload in resolution.asset_payloads["skills"]
                    if any(path["id"] == definition.id for path in payload.get("paths", []))
                ),
            )
            for definition, resolution in eligible
        )
        if not candidates:
            raise OrchestrationError("No PathDefinition has both a matched Skill and applicable mandatory Policy")
        result = await self.planner.propose(
            PlanningContext(
                case_id=case.id,
                case_version=case.version,
                title=case.title,
                description=case.description,
                classification=dict(case.classification),
                business_payload=dict(case.business_payload),
                human_proposal=dict(case.human_proposal) if case.human_proposal else None,
            ),
            candidates,
        )
        allowed = {item.definition for item in candidates}
        if not result.paths:
            raise PlannerOutputError("Planner must select at least one Path")
        selected_definitions = [path.definition for path in result.paths]
        if len(set(selected_definitions)) != len(selected_definitions):
            raise PlannerOutputError("Planner selected the same Path more than once")
        returned = set(selected_definitions)
        if returned != allowed:
            raise PlannerOutputError(
                f"Planner must return every Skill-declared Path exactly once; "
                f"missing={sorted(allowed - returned)}, unknown={sorted(returned - allowed)}"
            )

        definitions_by_id = {definition.id: definition for definition in definitions}
        selected = [
            (planned, definitions_by_id[planned.definition], resolutions[planned.definition])
            for planned in result.paths
        ]
        manifest_paths = tuple(
            ManifestPath(
                id=f"PATH-{index:02d}",
                definition=definition.id,
                title=definition.title,
                rationale=planned.rationale,
            )
            for index, (planned, definition, _) in enumerate(selected, start=1)
        )
        capability_snapshots = {
            path.id: resolution.to_snapshot()
            for path, (_, _, resolution) in zip(manifest_paths, selected)
        }

        def aggregate_refs(kind: str) -> tuple[str, ...]:
            seen: set[str] = set()
            refs: list[str] = []
            for _, _, resolution in selected:
                for item in getattr(resolution, kind):
                    value = f"{item.id}@{item.version}"
                    if value not in seen:
                        seen.add(value)
                        refs.append(value)
            return tuple(refs)

        experience_refs: list[str] = []
        for _, _, resolution in selected:
            for item, payload in zip(resolution.knowledge, resolution.asset_payloads["knowledge"]):
                value = f"{item.id}@{item.version}"
                if payload.get("knowledge_type") == "experience" and value not in experience_refs:
                    experience_refs.append(value)
        return Manifest(
            id=f"MAN-{case.id}-{case.version}",
            revision=1,
            status="DRAFT",
            paths=manifest_paths,
            policy_refs=aggregate_refs("policies"),
            skill_refs=aggregate_refs("skills"),
            knowledge_refs=aggregate_refs("knowledge"),
            experience_refs=tuple(experience_refs),
            capability_snapshot=capability_snapshots[manifest_paths[0].id],
            planner_profile=result.planner_profile,
            generated_from_case_version=case.version,
            capability_snapshots=capability_snapshots,
        )


def planner_from_environment() -> PlannerAdapter:
    load_runtime_environment()
    adapter = os.getenv("AGENTIC_CM_ORCHESTRATOR_ADAPTER", "deterministic")
    if adapter == "deterministic":
        return DeterministicPlannerAdapter()
    if adapter == "openai-compatible":
        return OpenAICompatiblePlannerAdapter(
            os.getenv("AGENTIC_CM_LLM_API_KEY"),
            model=os.getenv("AGENTIC_CM_LLM_MODEL", ""),
            base_url=os.getenv("AGENTIC_CM_LLM_BASE_URL", ""),
            api_key_header=os.getenv("AGENTIC_CM_LLM_API_KEY_HEADER", "Authorization"),
            api_key_prefix=os.getenv("AGENTIC_CM_LLM_API_KEY_PREFIX", "Bearer"),
        )
    raise OrchestrationError(f"Unknown orchestrator adapter: {adapter}")
