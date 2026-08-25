from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Annotated, Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

from .capabilities import CapabilityRegistry
from .config import agent_adapter_from_environment
from .domain import Case, Manifest, ManifestPath, OrchestrationPhase
from .llm import (
    CompatibleModelClientError,
    OpenAICompatibleClient,
    build_openai_compatible_client,
    create_chat_completion,
)


class OrchestrationError(ValueError):
    pass


class PlannerOutputError(OrchestrationError):
    pass


class PlannerExecutionError(OrchestrationError):
    pass


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _contains_chinese(value: str) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in value)


class _PlannedPathPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: NonEmptyText
    rationale: NonEmptyText


class _ManifestDraftPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paths: list[_PlannedPathPayload] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_paths(self) -> "_ManifestDraftPayload":
        definitions = [path.definition for path in self.paths]
        if len(set(definitions)) != len(definitions):
            raise ValueError("Planner selected the same Path more than once")
        if any(not _contains_chinese(path.rationale) for path in self.paths):
            raise ValueError("Planner 的 Path 说明必须使用中文")
        return self


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


class AgentTraceSink(Protocol):
    def __call__(
        self,
        step: str,
        status: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> None: ...


class PlannerAdapter(Protocol):
    async def propose(
        self,
        context: PlanningContext,
        candidates: tuple[PlanningCandidate, ...],
        trace: AgentTraceSink,
    ) -> ManifestDraftResult: ...


class DeterministicPlannerAdapter:
    """Reproducible adapter used for tests and keyless local development."""

    profile = "deterministic/v1"

    async def propose(
        self,
        context: PlanningContext,
        candidates: tuple[PlanningCandidate, ...],
        trace: AgentTraceSink,
    ) -> ManifestDraftResult:
        trace(
            "planner.request",
            "COMPLETED",
            "Deterministic Planner 接收候选 Path",
            {
                "case": asdict(context),
                "candidates": [asdict(candidate) for candidate in candidates],
                "adapter": self.profile,
            },
        )
        if not candidates:
            raise OrchestrationError("No compatible PathDefinition has applicable mandatory Policy")
        result = ManifestDraftResult(
            paths=tuple(
                PlannedPath(
                    candidate.definition,
                    f"{candidate.title}由命中的编排 Skill 声明；"
                    "deterministic 模式不判断当前 Case 的业务优先级。",
                )
                for candidate in candidates
            ),
            planner_profile=self.profile,
        )
        trace(
            "planner.response",
            "COMPLETED",
            "Deterministic Planner 返回结构化建议",
            {"paths": [asdict(path) for path in result.paths]},
        )
        return result


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
        client: OpenAICompatibleClient | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not model.strip():
            raise OrchestrationError("A model id is required for the OpenAI-compatible planner")
        if not base_url.strip():
            raise OrchestrationError("A base URL is required for the OpenAI-compatible planner")
        try:
            configured_client = client or build_openai_compatible_client(
                api_key,
                base_url=base_url,
                api_key_header=api_key_header,
                api_key_prefix=api_key_prefix,
                timeout_seconds=timeout_seconds,
                http_client=http_client,
            )
        except ValueError as exc:
            raise OrchestrationError(str(exc)) from exc
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._api_key_header = api_key_header
        self._client = configured_client

    @property
    def profile(self) -> str:
        return f"openai-compatible/{self._model}"

    async def propose(
        self,
        context: PlanningContext,
        candidates: tuple[PlanningCandidate, ...],
        trace: AgentTraceSink,
    ) -> ManifestDraftResult:
        response_schema = _ManifestDraftPayload.model_json_schema()
        request = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an enterprise exception Case planning component. Return JSON only. "
                        "Return every provided candidate definition exactly once, with a Case-specific rationale. "
                        "Write every human-facing rationale in Chinese. "
                        "You may order them by relevance. Never invent or omit ids, remove policies, "
                        "make business commitments, or claim operational actions. "
                        f"Match this JSON Schema exactly: {json.dumps(response_schema)}"
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
        last_error: Exception | None = None
        request_attempt = 0
        for schema_attempt in range(2):
            response = None
            for network_attempt in range(2):
                request_attempt += 1
                is_network_retry = network_attempt == 1
                step = (
                    "planner.retry_request" if is_network_retry
                    else "planner.request" if schema_attempt == 0
                    else "planner.repair_request"
                )
                trace(
                    step,
                    "STARTED",
                    "模型连接或请求超时，自动重试一次"
                    if is_network_retry
                    else "向 OpenAI-compatible Planner 发送结构化请求"
                    if schema_attempt == 0
                    else "上次响应无效，发送一次结构化修复请求",
                    {
                        "attempt": request_attempt,
                        "schema_attempt": schema_attempt + 1,
                        "network_attempt": network_attempt + 1,
                        "endpoint": f"{self._base_url}/chat/completions",
                        "request": request,
                        "authentication": {
                            "header": self._api_key_header,
                            "credential_present": bool(self._api_key),
                            "credential_value_logged": False,
                        },
                    },
                )
                try:
                    response = await create_chat_completion(self._client, request)
                    break
                except CompatibleModelClientError as exc:
                    trace(
                        "planner.request",
                        "FAILED",
                        "模型服务请求失败",
                        {
                            "attempt": request_attempt,
                            "http_status": exc.status,
                            "error_type": exc.cause_type,
                            "will_retry": exc.status == "unavailable" and network_attempt == 0,
                        },
                    )
                    if exc.status == "unavailable" and network_attempt == 0:
                        continue
                    raise PlannerExecutionError(
                        f"Model planning request failed (status={exc.status})"
                    ) from exc
            if response is None:
                raise PlannerExecutionError("Model planning request failed without a response")
            try:
                trace(
                    "planner.response",
                    "COMPLETED",
                    "收到模型响应",
                    {
                        "attempt": request_attempt,
                        "http_status": response.http_status,
                        "response_id": response.response_id,
                        "finish_reason": response.finish_reason,
                        "usage": response.usage,
                        "content": response.content,
                    },
                )
                payload = _ManifestDraftPayload.model_validate_json(response.content)
                paths = tuple(PlannedPath(path.definition, path.rationale) for path in payload.paths)
                return ManifestDraftResult(paths=paths, planner_profile=self.profile)
            except ValidationError as exc:
                last_error = exc
                trace(
                    "planner.response_validation",
                    "FAILED",
                    "模型响应未通过结构化校验",
                    {"attempt": request_attempt, "error_type": type(exc).__name__, "error": str(exc)},
                )
                if schema_attempt == 0:
                    request["messages"].append({
                        "role": "system",
                        "content": "The previous output was invalid. Return one non-empty JSON object matching the exact schema.",
                    })
        raise PlannerOutputError("Model returned an invalid JSON planning result after one repair") from last_error


class Orchestrator:
    def __init__(
        self,
        capabilities: CapabilityRegistry,
        planner: PlannerAdapter,
    ) -> None:
        self.capabilities = capabilities
        self.planner = planner

    async def compose_manifest(self, case: Case, trace: AgentTraceSink) -> Manifest:
        trace(
            "case.eligibility",
            "STARTED",
            "检查 Case 是否允许初次编排",
            {"case_id": case.id, "case_version": case.version, "phase": case.phase.value, "status": case.status.value},
        )
        if case.phase is not OrchestrationPhase.INTAKE or case.manifest is not None:
            raise OrchestrationError("Case is not eligible for initial orchestration")
        if case.status.value != "OPEN":
            raise OrchestrationError("Only OPEN Cases can be orchestrated")
        trace("case.eligibility", "COMPLETED", "Case 通过初次编排门禁")

        definitions = self.capabilities.resolve_path_candidates(case.classification)
        trace(
            "paths.discovery",
            "COMPLETED",
            f"编排 Skill 声明了 {len(definitions)} 条候选 Path",
            {"classification": dict(case.classification), "paths": [asdict(item) for item in definitions]},
        )
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
            trace(
                "capabilities.resolve",
                "FAILED" if missing else "COMPLETED",
                f"解析 {definition.id} 的执行能力",
                {
                    "path_definition": definition.id,
                    "missing": missing,
                    "policies": [ref.id for ref in resolution.policies],
                    "skills": [ref.id for ref in resolution.skills],
                    "knowledge": [ref.id for ref in resolution.knowledge],
                    "mandatory_commitments": [
                        item["id"] for item in resolution.compiled_policy.get("commitments", [])
                    ],
                },
            )
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
        planning_context = PlanningContext(
            case_id=case.id,
            case_version=case.version,
            title=case.title,
            description=case.description,
            classification=dict(case.classification),
            business_payload=dict(case.business_payload),
            human_proposal=dict(case.human_proposal) if case.human_proposal else None,
        )
        trace(
            "planner.input",
            "COMPLETED",
            "构造受限 Planner 输入",
            {"context": asdict(planning_context), "candidates": [asdict(item) for item in candidates]},
        )
        result = await self.planner.propose(
            planning_context,
            candidates,
            trace,
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
        trace(
            "planner.output_validation",
            "COMPLETED",
            "Planner 输出通过 Path 白名单与完整性校验",
            {"allowed": sorted(allowed), "returned_in_order": selected_definitions},
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
        manifest = Manifest(
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
        trace(
            "manifest.compose",
            "COMPLETED",
            "组装 Manifest 并冻结逐 Path 能力快照",
            {
                "manifest_id": manifest.id,
                "revision": manifest.revision,
                "planner_profile": manifest.planner_profile,
                "paths": [asdict(path) for path in manifest.paths],
                "policy_refs": list(manifest.policy_refs),
                "skill_refs": list(manifest.skill_refs),
                "knowledge_refs": list(manifest.knowledge_refs),
                "snapshot_path_ids": list(manifest.capability_snapshots),
            },
        )
        return manifest


def planner_from_environment() -> PlannerAdapter:
    adapter = agent_adapter_from_environment()
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
