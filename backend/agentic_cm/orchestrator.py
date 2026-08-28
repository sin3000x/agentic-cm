from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from typing import Annotated, Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .agent_runtime import (
    AgentTraceSink,
    ModelEndpoint,
    TraceNarration,
    configure_thinking,
    contains_chinese as _contains_chinese,
    request_structured_output,
)
from .capabilities import CapabilityRegistry
from .config import (
    ReasoningEffort,
    agent_adapter_from_environment,
    agent_llm_config_from_environment,
)
from .domain import (
    Case,
    Manifest,
    ManifestAssetRef,
    ManifestPath,
    ManifestSkillSelection,
    OrchestrationPhase,
)
from .llm import OpenAICompatibleClient, build_openai_compatible_client


class OrchestrationError(ValueError):
    pass


class PlannerOutputError(OrchestrationError):
    pass


class PlannerExecutionError(OrchestrationError):
    pass


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


_PLANNER_NARRATION = TraceNarration(
    request="\u5411 OpenAI-compatible Planner \u53d1\u9001\u7ed3\u6784\u5316\u8bf7\u6c42",
    repair_request="\u4e0a\u6b21\u54cd\u5e94\u65e0\u6548\uff0c\u53d1\u9001\u4e00\u6b21\u7ed3\u6784\u5316\u4fee\u590d\u8bf7\u6c42",
    retry_request="\u6a21\u578b\u8fde\u63a5\u6216\u8bf7\u6c42\u8d85\u65f6\uff0c\u81ea\u52a8\u91cd\u8bd5\u4e00\u6b21",
    response="\u6536\u5230\u6a21\u578b\u54cd\u5e94",
    validation_failed="\u6a21\u578b\u54cd\u5e94\u672a\u901a\u8fc7\u7ed3\u6784\u5316\u6821\u9a8c",
    request_failed="\u6a21\u578b\u670d\u52a1\u8bf7\u6c42\u5931\u8d25",
)


class PlannerSkillChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: NonEmptyText
    reason: NonEmptyText


class PlannerPath(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: NonEmptyText
    rationale: NonEmptyText
    skills: list[PlannerSkillChoice] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_skill_choices(self) -> "PlannerPath":
        ids = [item.id for item in self.skills]
        if len(ids) != len(set(ids)):
            raise ValueError("Planner selected the same Skill more than once for one Path")
        if any(not _contains_chinese(item.reason) for item in self.skills):
            raise ValueError("Planner 的 Skill 选择理由必须使用中文")
        return self


class _ManifestDraftPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paths: list[PlannerPath] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_paths(self) -> "_ManifestDraftPayload":
        definitions = [path.definition for path in self.paths]
        if len(set(definitions)) != len(definitions):
            raise ValueError("Planner selected the same Path more than once")
        if any(not _contains_chinese(path.rationale) for path in self.paths):
            raise ValueError("Planner 的 Path 说明必须使用中文")
        return self


class PlannerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    paths: tuple[PlannerPath, ...]
    planner_profile: str


class PlannerAdapter(Protocol):
    async def propose(
        self,
        context: dict[str, Any],
        candidates: tuple[dict[str, Any], ...],
        skill_catalog: tuple[dict[str, str], ...],
        trace: AgentTraceSink,
    ) -> PlannerOutput: ...


class DeterministicPlannerAdapter:
    """Reproducible adapter used for tests and keyless local development."""

    profile = "deterministic/v1"

    async def propose(
        self,
        context: dict[str, Any],
        candidates: tuple[dict[str, Any], ...],
        skill_catalog: tuple[dict[str, str], ...],
        trace: AgentTraceSink,
    ) -> PlannerOutput:
        trace(
            "planner.request",
            "COMPLETED",
            "Deterministic Planner 接收候选 Path",
            {
                "case": context,
                "candidates": list(candidates),
                "skill_catalog": list(skill_catalog),
                "adapter": self.profile,
            },
        )
        if not candidates:
            raise OrchestrationError("No compatible PathDefinition has applicable mandatory Policy")
        result = PlannerOutput(
            paths=tuple(
                PlannerPath(
                    definition=candidate["definition"],
                    rationale=(
                        f"{candidate['title']}由 Case Type Catalog 声明；"
                        "deterministic 模式不判断当前 Case 的业务优先级。"
                    ),
                    skills=[
                        PlannerSkillChoice(
                            id=selected["id"],
                            reason=f"选择{selected['title']}分析{candidate['title']}相关证据。",
                        )
                    ],
                )
                for candidate in candidates
                for selected in (_deterministic_skill(candidate, skill_catalog),)
            ),
            planner_profile=self.profile,
        )
        trace(
            "planner.response",
            "COMPLETED",
            "Deterministic Planner 返回结构化建议",
            {"paths": [path.model_dump(mode="json") for path in result.paths]},
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
        thinking_enabled: bool = False,
        reasoning_effort: ReasoningEffort = "high",
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
        self._thinking_enabled = thinking_enabled
        self._reasoning_effort = reasoning_effort
        self._client = configured_client
        self._endpoint = ModelEndpoint(
            client=configured_client,
            base_url=self._base_url,
            api_key_header=api_key_header,
            api_key_present=bool(api_key),
        )

    @property
    def profile(self) -> str:
        return f"openai-compatible/{self._model}"

    async def propose(
        self,
        context: dict[str, Any],
        candidates: tuple[dict[str, Any], ...],
        skill_catalog: tuple[dict[str, str], ...],
        trace: AgentTraceSink,
    ) -> PlannerOutput:
        response_schema = _ManifestDraftPayload.model_json_schema()
        prompt_context = _planner_prompt_context(context, candidates, skill_catalog)
        trace(
            "planner.context_projection",
            "COMPLETED",
            "将完整候选能力投影为去重的 Planner 模型上下文",
            {"context": prompt_context},
        )
        request = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an enterprise exception Case planning component. Return JSON only. "
                        "Return every provided candidate definition exactly once, with a Case-specific rationale. "
                        "For every Path, select at least one Skill id from the provided skill_catalog "
                        "and give a Chinese reason. Never invent Skill ids. Bundle members are not selectable. "
                        "Use the provided orchestration knowledge only to understand and order candidate Paths. "
                        "Write every human-facing rationale in Chinese. "
                        "You may order them by relevance. Never invent or omit ids, remove policies, "
                        "make business commitments, or claim operational actions. "
                        f"Match this JSON Schema exactly: {json.dumps(response_schema)}"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt_context, ensure_ascii=False),
                },
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 800,
            "stream": False,
        }
        configure_thinking(
            request,
            enabled=self._thinking_enabled,
            reasoning_effort=self._reasoning_effort,
        )
        allowed_path_ids = {item["definition"] for item in candidates}
        allowed_skill_ids = {item["id"] for item in skill_catalog}

        def build_result(payload: _ManifestDraftPayload) -> PlannerOutput:
            _validate_planner_choices(payload.paths, allowed_path_ids, allowed_skill_ids)
            return PlannerOutput(paths=tuple(payload.paths), planner_profile=self.profile)

        return await request_structured_output(
            self._endpoint,
            request,
            agent_label="Planner",
            trace=trace,
            step_prefix="planner",
            narration=_PLANNER_NARRATION,
            payload_model=_ManifestDraftPayload,
            build_result=build_result,
            repair_instruction=lambda exc: (
                "The previous output was invalid. Return one non-empty JSON object "
                "matching the exact schema. Select only Skill ids from skill_catalog."
            ),
            execution_error=PlannerExecutionError,
            output_error=PlannerOutputError,
            recoverable_output_errors=(PlannerOutputError,),
        )


def _planner_prompt_context(
    context: dict[str, Any],
    candidates: tuple[dict[str, Any], ...],
    skill_catalog: tuple[dict[str, str], ...],
) -> dict[str, Any]:
    return {
        "case": {
            key: value for key, value in context.items()
            if key != "orchestration_knowledge"
        },
        "candidates": [
            {
                "definition": item["definition"],
                "title": item["title"],
                "description": item["description"],
                "required_review_dimensions": item["required_review_dimensions"],
            }
            for item in candidates
        ],
        "skill_catalog": [dict(item) for item in skill_catalog],
        "knowledge": list(context.get("orchestration_knowledge", [])),
    }


def _identifier_terms(value: str) -> set[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)
    return {term for term in re.split(r"[^a-z0-9]+", expanded.lower()) if term}


def _deterministic_skill(
    candidate: dict[str, Any],
    skill_catalog: tuple[dict[str, str], ...],
) -> dict[str, str]:
    path_terms = _identifier_terms(candidate["definition"])
    ranked = sorted(
        skill_catalog,
        key=lambda skill: (-len(path_terms & _identifier_terms(skill["id"])), skill["id"]),
    )
    if not ranked:
        raise OrchestrationError("No Orchestrator-visible Skill entrypoints")
    return ranked[0]


def _validate_planner_choices(
    paths: tuple[PlannerPath, ...] | list[PlannerPath],
    allowed_path_ids: set[str],
    allowed_skill_ids: set[str],
) -> None:
    if not paths:
        raise PlannerOutputError("Planner must select at least one Path")
    selected_definitions = [path.definition for path in paths]
    if len(set(selected_definitions)) != len(selected_definitions):
        raise PlannerOutputError("Planner selected the same Path more than once")
    returned = set(selected_definitions)
    if returned != allowed_path_ids:
        raise PlannerOutputError(
            f"Planner must return every Catalog-declared Path exactly once; "
            f"missing={sorted(allowed_path_ids - returned)}, unknown={sorted(returned - allowed_path_ids)}"
        )
    for planned in paths:
        selected_ids = [choice.id for choice in planned.skills]
        if not selected_ids:
            raise PlannerOutputError(f"Planner selected no Skills for {planned.definition}")
        unknown = set(selected_ids) - allowed_skill_ids
        if unknown:
            raise PlannerOutputError(f"Planner selected unknown Skill ids: {sorted(unknown)}")
        if len(selected_ids) != len(set(selected_ids)):
            raise PlannerOutputError(
                f"Planner selected duplicate Skills for {planned.definition}"
            )


class Orchestrator:
    def __init__(
        self,
        capabilities: CapabilityRegistry,
        planner: PlannerAdapter,
    ) -> None:
        self.capabilities = capabilities
        self.planner = planner

    async def compose_manifest(
        self, case: Case, trace: AgentTraceSink
    ) -> tuple[Manifest, str]:
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
        orchestration_resolution = self.capabilities.resolve(case.classification)
        trace(
            "paths.discovery",
            "COMPLETED",
            f"Case Type Catalog 声明了 {len(definitions)} 条候选 Path",
            {"classification": dict(case.classification), "paths": [asdict(item) for item in definitions]},
        )
        resolutions: dict[str, Any] = {}
        eligible: list[tuple[Any, Any]] = []
        incomplete: dict[str, list[str]] = {}
        for definition in definitions:
            resolution = self.capabilities.resolve(
                case.classification | {"path_definition": definition.id}
            )
            missing: list[str] = []
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
                f"解析 {definition.id} 的 Policy 与 Knowledge",
                {
                    "path_definition": definition.id,
                    "missing": missing,
                    "policies": [ref.id for ref in resolution.policies],
                    "knowledge": [ref.id for ref in resolution.knowledge],
                    "mandatory_commitments": [
                        item["id"] for item in resolution.compiled_policy.get("commitments", [])
                    ],
                },
            )
        if incomplete:
            raise OrchestrationError(
                f"Catalog-declared Paths are not executable: {incomplete}"
            )
        skill_catalog = self.capabilities.list_orchestrator_skills()
        if not skill_catalog:
            raise OrchestrationError("No Orchestrator-visible Skill entrypoints")
        candidates = tuple(
            {
                "definition": definition.id,
                "title": definition.title,
                "description": definition.description,
                "policy_ids": [ref.id for ref in resolution.policies],
                "knowledge_ids": [ref.id for ref in resolution.knowledge],
                "mandatory_commitment_ids": [
                    item["id"] for item in resolution.compiled_policy["commitments"]
                ],
                "required_review_dimensions": [
                    item["review_dimension"]
                    for item in resolution.compiled_policy["commitments"]
                ],
            }
            for definition, resolution in eligible
        )
        if not candidates:
            raise OrchestrationError("No PathDefinition has applicable mandatory Policy")
        planning_context = {
            "case_id": case.id,
            "case_version": case.version,
            "title": case.title,
            "description": case.description,
            "classification": dict(case.classification),
            "business_payload": dict(case.business_payload),
            "human_proposal": dict(case.human_proposal) if case.human_proposal else None,
            "orchestration_knowledge": list(
                orchestration_resolution.asset_payloads["knowledge"]
            ),
        }
        trace(
            "planner.input",
            "COMPLETED",
            "构造受限 Planner 输入",
            {
                "context": planning_context,
                "candidates": list(candidates),
                "skill_catalog": list(skill_catalog),
            },
        )
        result = await self.planner.propose(
            planning_context,
            candidates,
            skill_catalog,
            trace,
        )
        allowed_path_ids = {item["definition"] for item in candidates}
        allowed_skill_ids = {item["id"] for item in skill_catalog}
        _validate_planner_choices(result.paths, allowed_path_ids, allowed_skill_ids)
        selected_definitions = [path.definition for path in result.paths]
        trace(
            "planner.output_validation",
            "COMPLETED",
            "Planner 输出通过 Path 白名单、Skill 白名单与完整性校验",
            {
                "allowed_paths": sorted(allowed_path_ids),
                "allowed_skills": sorted(allowed_skill_ids),
                "returned_in_order": selected_definitions,
                "selected_skill_entrypoints": [
                    choice.id for planned in result.paths for choice in planned.skills
                ],
            },
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
                rationale=planned.rationale,
                skill_selections=tuple(
                    ManifestSkillSelection(
                        entrypoint=_manifest_ref(expanded.entrypoint),
                        reason=choice.reason,
                        members=tuple(_manifest_ref(ref) for ref in expanded.members),
                    )
                    for choice in planned.skills
                    for expanded in (self.capabilities.resolve_skill_entrypoint(choice.id),)
                ),
                policies=tuple(_manifest_ref(ref) for ref in resolution.policies),
                knowledge=tuple(
                    _manifest_ref(ref)
                    for ref in resolution.knowledge
                    if ref.id in {
                        payload["id"]
                        for payload in resolution.asset_payloads["knowledge"]
                        if definition.id in (payload.get("selector") or {}).get(
                            "path_definition", []
                        )
                    }
                ),
            )
            for index, (planned, definition, resolution) in enumerate(selected, start=1)
        )

        manifest = Manifest(
            id=f"MAN-{case.id}-{case.version}",
            revision=1,
            paths=manifest_paths,
            knowledge=tuple(
                _manifest_ref(ref) for ref in orchestration_resolution.knowledge
            ),
            generated_from_case_version=case.version,
        )
        trace(
            "manifest.compose",
            "COMPLETED",
            "组装 Manifest 并冻结逐 Path 能力快照",
            {
                "manifest_id": manifest.id,
                "revision": manifest.revision,
                "planner_profile": result.planner_profile,
                "paths": [path.model_dump(mode="json") for path in manifest.paths],
                "path_ids": [path.id for path in manifest.paths],
                "selected_skill_entrypoints": [
                    selection.entrypoint.id
                    for path in manifest.paths
                    for selection in path.skill_selections
                ],
                "expanded_skill_refs": [
                    {
                        "path": path.definition,
                        "entrypoint": selection.entrypoint.id,
                        "members": [item.id for item in selection.members],
                    }
                    for path in manifest.paths
                    for selection in path.skill_selections
                ],
                "manifest_yaml": manifest.to_yaml(),
            },
        )
        return manifest, result.planner_profile


def _manifest_ref(ref: Any) -> ManifestAssetRef:
    return ManifestAssetRef(id=ref.id, version=ref.version, digest=ref.digest)


def planner_from_environment() -> PlannerAdapter:
    adapter = agent_adapter_from_environment()
    if adapter == "deterministic":
        return DeterministicPlannerAdapter()
    if adapter == "openai-compatible":
        llm = agent_llm_config_from_environment("orchestrator")
        return OpenAICompatiblePlannerAdapter(
            os.getenv("AGENTIC_CM_LLM_API_KEY"),
            model=llm.model,
            base_url=os.getenv("AGENTIC_CM_LLM_BASE_URL", ""),
            api_key_header=os.getenv("AGENTIC_CM_LLM_API_KEY_HEADER", "Authorization"),
            api_key_prefix=os.getenv("AGENTIC_CM_LLM_API_KEY_PREFIX", "Bearer"),
            thinking_enabled=llm.thinking_enabled,
            reasoning_effort=llm.reasoning_effort,
        )
    raise OrchestrationError(f"Unknown orchestrator adapter: {adapter}")
