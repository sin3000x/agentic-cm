from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
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
from .config import (
    ReasoningEffort,
    agent_adapter_from_environment,
    agent_llm_config_from_environment,
)
from .capabilities import CapabilityResolution
from .domain import Case, OrchestrationPhase, PathAttemptState
from .llm import OpenAICompatibleClient, build_openai_compatible_client


class PathAgentError(ValueError):
    pass


class PathAgentOutputError(PathAgentError):
    pass


class PathAgentExecutionError(PathAgentError):
    pass


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


_PATH_AGENT_NARRATION = TraceNarration(
    request="\u5411 OpenAI-compatible Path Agent \u53d1\u9001 Manifest \u7ec4\u88c5\u8bf7\u6c42",
    repair_request="\u4e0a\u6b21\u54cd\u5e94\u65e0\u6548\uff0c\u53d1\u9001\u4e00\u6b21\u7ed3\u6784\u5316\u4fee\u590d\u8bf7\u6c42",
    retry_request="\u6a21\u578b\u8fde\u63a5\u6216\u8bf7\u6c42\u8d85\u65f6\uff0c\u81ea\u52a8\u91cd\u8bd5\u4e00\u6b21",
    response="\u6536\u5230 Path Agent \u6a21\u578b\u54cd\u5e94",
    validation_failed="Path Agent \u54cd\u5e94\u672a\u901a\u8fc7\u7ed3\u6784\u5316\u6821\u9a8c",
    request_failed="Path Agent \u6a21\u578b\u670d\u52a1\u8bf7\u6c42\u5931\u8d25",
)


class _ProposedOptionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonEmptyText
    title: NonEmptyText
    description: NonEmptyText
    benefits: list[NonEmptyText]
    risks: list[NonEmptyText]
    assumptions: list[NonEmptyText]


class _RecommendationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_ids: list[NonEmptyText]
    rationale: NonEmptyText


class _RoleReportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: NonEmptyText
    dimension: NonEmptyText
    report: NonEmptyText


class _PathAgentResultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: NonEmptyText
    options: list[_ProposedOptionPayload] = Field(min_length=1)
    recommendation: _RecommendationPayload
    evidence_gaps: list[NonEmptyText]
    role_reports: list[_RoleReportPayload]

    @model_validator(mode="after")
    def require_unique_contract_keys(self) -> "_PathAgentResultPayload":
        option_ids = [option.id for option in self.options]
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("Path Agent options must have unique ids")
        role_keys = [(report.role, report.dimension) for report in self.role_reports]
        if len(set(role_keys)) != len(role_keys):
            raise ValueError("Path Agent role reports must be unique by role and dimension")
        human_facing_text = [
            self.summary,
            self.recommendation.rationale,
            *self.evidence_gaps,
            *(value for option in self.options for value in (
                option.title,
                option.description,
                *option.benefits,
                *option.risks,
                *option.assumptions,
            )),
            *(value for report in self.role_reports for value in (
                report.role,
                report.dimension,
                report.report,
            )),
        ]
        if any(not _contains_chinese(value) for value in human_facing_text):
            raise ValueError("Path Agent 的全部面向人字段必须使用中文")
        return self


@dataclass(frozen=True)
class PathAgentContext:
    case_snapshot: dict[str, Any]
    human_proposal: dict[str, Any] | None
    manifest_ref: dict[str, Any]
    path: dict[str, Any]
    path_attempt: dict[str, Any]
    commitment_dag_snapshot: tuple[dict[str, Any], ...]
    execution_skills: tuple[dict[str, Any], ...]
    policies: tuple[dict[str, Any], ...]
    knowledge: tuple[dict[str, Any], ...]
    authorized_options: tuple[dict[str, str], ...]
    authorized_option_ids: tuple[str, ...]
    tool_results: tuple[dict[str, Any], ...]
    required_role_reports: tuple[dict[str, str], ...]
    previous_solution_revision: dict[str, Any] | None


@dataclass(frozen=True)
class PathPromptContext:
    case_snapshot: dict[str, Any]
    human_proposal: dict[str, Any] | None
    manifest_ref: dict[str, Any]
    path: dict[str, Any]
    path_attempt: dict[str, Any]
    execution_skills: tuple[dict[str, Any], ...]
    knowledge: tuple[dict[str, Any], ...]
    authorized_options: tuple[dict[str, str], ...]
    tool_results: tuple[dict[str, Any], ...]
    required_role_reports: tuple[dict[str, str], ...]
    previous_solution_revision: dict[str, Any] | None


@dataclass(frozen=True)
class ProposedOption:
    id: str
    title: str
    description: str
    benefits: tuple[str, ...]
    risks: tuple[str, ...]
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class RoleReport:
    role: str
    dimension: str
    report: str


@dataclass(frozen=True)
class PathAgentResult:
    summary: str
    options: tuple[ProposedOption, ...]
    recommended_option_ids: tuple[str, ...]
    recommendation_rationale: str
    evidence_gaps: tuple[str, ...]
    role_reports: tuple[RoleReport, ...]
    adapter_profile: str


class PathAgentAdapter(Protocol):
    async def generate(
        self,
        context: PathAgentContext,
        trace: AgentTraceSink,
    ) -> PathAgentResult: ...


class DeterministicPathAgentAdapter:
    """Keyless test adapter. It does not assert unverified operational facts."""

    profile = "deterministic-path/v1"

    async def generate(
        self,
        context: PathAgentContext,
        trace: AgentTraceSink,
    ) -> PathAgentResult:
        trace(
            "model.request",
            "COMPLETED",
            "Deterministic Path Adapter 接收 Manifest 组装上下文",
            {"context": asdict(context), "adapter": self.profile},
        )
        candidates = context.authorized_options
        options = tuple(
            ProposedOption(
                id=str(item["id"]),
                title=str(item.get("title") or item["id"]),
                description=str(item.get("description") or "作为冻结 Skill 候选进入并行核验。"),
                benefits=("保留原订单目标的探索空间",),
                risks=("当前供应与技术证据尚未由责任角色确认",),
                assumptions=("仅为分析提案，不代表物料、数量或交期承诺",),
            )
            for item in candidates
            if isinstance(item, dict) and item.get("id")
        )
        if not options:
            options = (
                ProposedOption(
                    id="OPTION-01",
                    title=context.path["title"],
                    description="按冻结 Skill 生成的待核验分析选项。",
                    benefits=("形成可审查的结构化提案",),
                    risks=("缺少可确认的候选事实",),
                    assumptions=("所有业务结论均等待责任角色确认",),
                ),
            )
        option_reference = "、".join(option.id for option in options)
        result = PathAgentResult(
            summary="已依据 Manifest 冻结的执行 Skill 形成替代方案草案；尚未作出业务承诺。",
            options=options,
            recommended_option_ids=(),
            recommendation_rationale="deterministic 模式不判断候选业务优先级。",
            evidence_gaps=("供应、技术与客户接受度需要由 Manifest 编译出的责任角色确认",),
            role_reports=tuple(
                RoleReport(
                    role=contract["role"],
                    dimension=contract["dimension"],
                    report=(
                        f"{contract['role']}维度：冻结 Skill 中的{option_reference}已按{contract['dimension']}形成比较，"
                        f"但模拟查询结果仍须由{contract['role']}核验后才能形成业务判断。"
                    ),
                )
                for contract in context.required_role_reports
            ),
            adapter_profile=self.profile,
        )
        trace(
            "model.response",
            "COMPLETED",
            "Deterministic Path Adapter 返回结构化 SolutionRevision 草案",
            {"result": _result_payload(result)},
        )
        return result


class OpenAICompatiblePathAgentAdapter:
    """Provider-neutral Path Agent adapter assembled from a frozen Manifest."""

    def __init__(
        self,
        api_key: str | None,
        *,
        model: str,
        base_url: str,
        api_key_header: str = "Authorization",
        api_key_prefix: str = "Bearer",
        timeout_seconds: float = 45.0,
        max_output_tokens: int = 6000,
        thinking_enabled: bool = False,
        reasoning_effort: ReasoningEffort = "high",
        client: OpenAICompatibleClient | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not model.strip():
            raise PathAgentError("A model id is required for the OpenAI-compatible Path Agent")
        if not base_url.strip():
            raise PathAgentError("A base URL is required for the OpenAI-compatible Path Agent")
        if max_output_tokens < 1000:
            raise PathAgentError("Path Agent max output tokens must be at least 1000")
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
            raise PathAgentError(str(exc)) from exc
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._api_key_header = api_key_header
        self._max_output_tokens = max_output_tokens
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
        return f"openai-compatible-path/{self._model}"

    async def generate(
        self,
        context: PathAgentContext,
        trace: AgentTraceSink,
    ) -> PathAgentResult:
        response_schema = _PathAgentResultPayload.model_json_schema()
        prompt_context = _path_prompt_context(context)
        trace(
            "model.context_projection",
            "COMPLETED",
            "将完整 PathRunContext 投影为去重的模型上下文",
            {"context": asdict(prompt_context)},
        )
        request = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a Path Agent assembled only from an approved Manifest snapshot. "
                        "Follow the frozen execution Skill instructions. Treat Knowledge as advisory, "
                        "never as current Case fact. Propose reviewable alternatives but do not make "
                        "business commitments, claim actions were executed, remove Policy duties, or "
                        "invent confirmed quantities, dates, certifications, or approvals. Put every "
                        "unsupported claim in assumptions or evidence_gaps. Write every human-facing "
                        "title, description, analysis, recommendation, evidence gap, and role report in Chinese. "
                        "Return JSON only. "
                        f"Match this JSON Schema exactly: {json.dumps(response_schema)}. "
                        "Return role_reports for exactly the Policy-triggered contracts in "
                        "required_role_reports, with no missing or extra role/dimension pair; "
                        "if required_role_reports is empty, return an empty role_reports array. "
                        "Keep the JSON concise: at most two short items in each benefits, risks, assumptions, "
                        "and evidence_gaps array. Do not repeat the full evidence outside the required role reports."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(asdict(prompt_context), ensure_ascii=False),
                },
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": self._max_output_tokens,
            "stream": False,
        }
        configure_thinking(
            request,
            enabled=self._thinking_enabled,
            reasoning_effort=self._reasoning_effort,
        )
        def build_result(payload: _PathAgentResultPayload) -> PathAgentResult:
            result = _parse_result(payload, self.profile)
            _validate_result_against_context(result, context)
            return result

        return await request_structured_output(
            self._endpoint,
            request,
            agent_label="Path Agent",
            trace=trace,
            step_prefix="model",
            narration=_PATH_AGENT_NARRATION,
            payload_model=_PathAgentResultPayload,
            build_result=build_result,
            repair_instruction=lambda exc: (
                f"The previous output was invalid: {exc}. Return one non-empty JSON object "
                "matching the exact schema, every authorized option, and exactly the "
                "Policy-triggered required_role_reports with no extra role/dimension pair."
            ),
            execution_error=PathAgentExecutionError,
            output_error=PathAgentOutputError,
            # The Path Agent also rejects output that is schema-valid but proposes
            # options or role reports the Manifest never authorized.
            recoverable_output_errors=(PathAgentOutputError,),
        )


def _path_prompt_context(context: PathAgentContext) -> PathPromptContext:
    execution_skills = tuple({
        "id": skill["id"],
        "version": skill["version"],
        "description": skill["description"],
        "instructions_markdown": skill["instructions_markdown"],
    } for skill in context.execution_skills)
    knowledge = tuple({
        key: item[key]
        for key in (
            "id", "version", "title", "knowledge_type", "source", "confidence", "content"
        )
        if key in item
    } for item in context.knowledge)
    path_attempt = dict(context.path_attempt)
    return PathPromptContext(
        case_snapshot=context.case_snapshot,
        human_proposal=context.human_proposal,
        manifest_ref=context.manifest_ref,
        path=context.path,
        path_attempt=path_attempt,
        execution_skills=execution_skills,
        knowledge=knowledge,
        authorized_options=context.authorized_options,
        tool_results=context.tool_results,
        required_role_reports=context.required_role_reports,
        previous_solution_revision=context.previous_solution_revision,
    )


class PathAgent:
    def __init__(self, adapter: PathAgentAdapter) -> None:
        self.adapter = adapter

    async def run(
        self,
        case: Case,
        path_id: str,
        path_title: str,
        resolution: CapabilityResolution,
        trace: AgentTraceSink,
    ) -> dict[str, Any]:
        trace(
            "path.eligibility",
            "STARTED",
            "检查已批准 Path 是否允许生成 SolutionRevision",
            {"case_id": case.id, "case_version": case.version, "phase": case.phase.value, "path_id": path_id},
        )
        if case.phase is not OrchestrationPhase.PATH_EXPLORATION or case.manifest is None:
            raise PathAgentError("Case is not in PATH_EXPLORATION with an approved Manifest")
        path = next((item for item in case.manifest.paths if item.id == path_id and item.selected), None)
        if path is None:
            raise PathAgentError(f"Unknown selected Manifest Path: {path_id}")
        attempt = next((item for item in case.path_attempts if item.path_id == path_id), None)
        if attempt is None:
            raise PathAgentError(f"PathAttempt does not exist for {path_id}")
        trace("path.eligibility", "COMPLETED", "Path 与冻结 Manifest 能力通过执行门禁")

        execution_skills = tuple(resolution.asset_payloads["skills"])
        if not execution_skills:
            raise PathAgentError(f"Frozen Manifest has no execution Skill for {path.definition}")
        policies = tuple(resolution.asset_payloads["policies"])
        knowledge = tuple(resolution.asset_payloads["knowledge"])
        commitments = list(resolution.compiled_policy.get("commitments", []))
        if not commitments:
            raise PathAgentError(f"Frozen Manifest has no mandatory Policy for {path.definition}")
        missing_report_contracts = [
            commitment.get("id", "<unknown>")
            for commitment in commitments
            if not isinstance(commitment.get("review_dimension"), str)
            or not commitment["review_dimension"].strip()
        ]
        if missing_report_contracts:
            raise PathAgentError(
                "Frozen Manifest Policy commitments have no role-report contract; "
                f"regenerate the Manifest with current Policies: {missing_report_contracts}"
            )
        previous = attempt.solution_revision if isinstance(attempt.solution_revision, dict) else None
        if previous and attempt.state is not PathAttemptState.REVISING:
            raise PathAgentError("An existing SolutionRevision can only be regenerated after a human revision request")

        option_contracts = [
            tuple(skill.get("path_options", []))
            for skill in execution_skills
            if skill.get("path_options")
        ]
        if len(option_contracts) > 1 and any(contract != option_contracts[0] for contract in option_contracts[1:]):
            raise PathAgentError("Frozen execution Skills define conflicting Path options")
        authorized_options = option_contracts[0] if option_contracts else ()
        required_role_reports = tuple(
            {
                "role": commitment["role"],
                "dimension": commitment["review_dimension"],
            }
            for commitment in commitments
        )
        role_keys = [(item["role"], item["dimension"]) for item in required_role_reports]
        if len(set(role_keys)) != len(role_keys):
            raise PathAgentError("Frozen Policies define duplicate role report contracts")

        tools_by_id: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        for skill in execution_skills:
            for tool in skill.get("tools", []):
                current = tools_by_id.get(tool["id"])
                if current and current[0] != tool:
                    raise PathAgentError(f"Frozen execution Skills define conflicting tool {tool['id']}")
                tools_by_id[tool["id"]] = (tool, skill)
        trace(
            "agent.assemble",
            "COMPLETED",
            "从 Manifest 冻结快照组装 Path Agent",
            {
                "manifest_ref": {
                    "id": case.manifest.id,
                    "revision": case.manifest.revision,
                    "generated_from_case_version": case.manifest.generated_from_case_version,
                },
                "path": path.model_dump(mode="json"),
                "execution_skills": [_safe_ref(item) for item in execution_skills],
                "policies": [_safe_ref(item) for item in policies],
                "knowledge": [_safe_ref(item) for item in knowledge],
                "authorized_options": list(authorized_options),
                "tool_ids": sorted(tools_by_id),
                "required_role_reports": list(required_role_reports),
                "mandatory_commitment_ids": [item["id"] for item in commitments],
            },
        )
        tool_results: list[dict[str, Any]] = []
        for tool_id, (tool, skill) in sorted(tools_by_id.items()):
            for option in authorized_options:
                option_id = option["id"]
                if option_id not in tool["records"]:
                    raise PathAgentError(f"Frozen tool {tool_id} has no record for option {option_id}")
                tool_results.append({
                    "tool_id": tool_id,
                    "description": tool["description"],
                    "read_only": True,
                    "input": {tool["input_key"]: option_id},
                    "output": tool["records"][option_id],
                    "source_skill": _safe_ref(skill),
                })
        if tool_results:
            trace(
                "tools.query",
                "COMPLETED",
                "执行 Manifest 冻结的只读模拟查询",
                {"results": tool_results},
            )
        context = PathAgentContext(
            case_snapshot={
                "id": case.id,
                "version": case.version,
                "title": case.title,
                "description": case.description,
                "classification": dict(case.classification),
                "business_payload": dict(case.business_payload),
            },
            human_proposal=dict(case.human_proposal) if case.human_proposal else None,
            manifest_ref={
                "id": case.manifest.id,
                "revision": case.manifest.revision,
                "generated_from_case_version": case.manifest.generated_from_case_version,
            },
            path=path.model_dump(mode="json") | {"title": path_title},
            path_attempt={"path_id": attempt.path_id, "state": attempt.state.value},
            commitment_dag_snapshot=tuple(
                asdict(node) for node in case.commitment_nodes if node.path_id == path_id
            ),
            execution_skills=execution_skills,
            policies=policies,
            knowledge=knowledge,
            authorized_options=authorized_options,
            authorized_option_ids=tuple(item["id"] for item in authorized_options),
            tool_results=tuple(tool_results),
            required_role_reports=required_role_reports,
            previous_solution_revision=previous,
        )
        trace("agent.input", "COMPLETED", "构造冻结、最小授权的 PathRunContext", {"context": asdict(context)})
        result = await self.adapter.generate(context, trace)
        _validate_result_against_context(result, context)
        option_ids = [option.id for option in result.options]
        trace(
            "agent.output_validation",
            "COMPLETED",
            "Path Agent 输出通过结构、选项引用与治理边界校验",
            {
                "option_ids": option_ids,
                "authorized_option_ids": list(context.authorized_option_ids),
                "recommended_option_ids": list(result.recommended_option_ids),
                "role_reports": [asdict(item) for item in result.role_reports],
            },
        )
        revision = (previous.get("revision", 0) if previous else 0) + 1
        solution_revision = {
            "schema_version": 1,
            "revision": revision,
            "summary": result.summary,
            "options": [asdict(option) for option in result.options],
            "recommendation": {
                "option_ids": list(result.recommended_option_ids),
                "rationale": result.recommendation_rationale,
            },
            "evidence_gaps": list(result.evidence_gaps),
            "role_reports": [asdict(item) for item in result.role_reports],
            "generated_by": result.adapter_profile,
        }
        trace(
            "solution_revision.compose",
            "COMPLETED",
            "组装受平台约束的 SolutionRevision",
            {"solution_revision": solution_revision},
        )
        return solution_revision


def _safe_ref(payload: dict[str, Any]) -> dict[str, Any]:
    ref = payload.get("resolved_ref", {})
    return {key: ref.get(key) for key in ("id", "version", "digest", "source")}


def _validate_result_against_context(
    result: PathAgentResult,
    context: PathAgentContext,
) -> None:
    option_ids = [option.id for option in result.options]
    if not option_ids or len(set(option_ids)) != len(option_ids):
        raise PathAgentOutputError("Path Agent options require unique, non-empty ids")
    unknown = set(result.recommended_option_ids) - set(option_ids)
    if unknown:
        raise PathAgentOutputError(f"Recommendation references unknown options: {sorted(unknown)}")
    if context.authorized_option_ids and set(option_ids) != set(context.authorized_option_ids):
        raise PathAgentOutputError(
            "Path Agent must return every Manifest-authorized option exactly once; "
            f"missing={sorted(set(context.authorized_option_ids) - set(option_ids))}, "
            f"unknown={sorted(set(option_ids) - set(context.authorized_option_ids))}"
        )
    returned_role_reports = {(item.role, item.dimension): item for item in result.role_reports}
    required_role_keys = {
        (item["role"], item["dimension"]): item for item in context.required_role_reports
    }
    if set(returned_role_reports) != set(required_role_keys):
        raise PathAgentOutputError(
            "Path Agent must return every Skill-required role report exactly once; "
            f"missing={sorted(set(required_role_keys) - set(returned_role_reports))}, "
            f"unknown={sorted(set(returned_role_reports) - set(required_role_keys))}"
        )
    for key, contract in required_role_keys.items():
        report = returned_role_reports[key].report
        sentence_prefix = f"{contract['role']}维度："
        if not report.startswith(sentence_prefix):
            raise PathAgentOutputError(
                f"Role report {key} must start with {sentence_prefix}"
            )
        if not all(option_id in report for option_id in context.authorized_option_ids):
            raise PathAgentOutputError(f"Role report {key} must mention every authorized option")
        if len(report) < 20 or report[-1] not in "。！？.!?":
            raise PathAgentOutputError(f"Role report {key} must be one complete sentence")


def _result_payload(result: PathAgentResult) -> dict[str, Any]:
    return {
        "summary": result.summary,
        "options": [asdict(option) for option in result.options],
        "recommendation": {
            "option_ids": list(result.recommended_option_ids),
            "rationale": result.recommendation_rationale,
        },
        "evidence_gaps": list(result.evidence_gaps),
        "role_reports": [asdict(item) for item in result.role_reports],
    }


def _parse_result(payload: _PathAgentResultPayload, adapter_profile: str) -> PathAgentResult:
    return PathAgentResult(
        summary=payload.summary,
        options=tuple(
            ProposedOption(
                id=item.id,
                title=item.title,
                description=item.description,
                benefits=tuple(item.benefits),
                risks=tuple(item.risks),
                assumptions=tuple(item.assumptions),
            )
            for item in payload.options
        ),
        recommended_option_ids=tuple(payload.recommendation.option_ids),
        recommendation_rationale=payload.recommendation.rationale,
        evidence_gaps=tuple(payload.evidence_gaps),
        role_reports=tuple(
            RoleReport(role=item.role, dimension=item.dimension, report=item.report)
            for item in payload.role_reports
        ),
        adapter_profile=adapter_profile,
    )


def path_agent_from_environment() -> PathAgentAdapter:
    adapter = agent_adapter_from_environment()
    if adapter == "deterministic":
        return DeterministicPathAgentAdapter()
    if adapter == "openai-compatible":
        llm = agent_llm_config_from_environment("path")
        return OpenAICompatiblePathAgentAdapter(
            os.getenv("AGENTIC_CM_LLM_API_KEY"),
            model=llm.model,
            base_url=os.getenv("AGENTIC_CM_LLM_BASE_URL", ""),
            api_key_header=os.getenv("AGENTIC_CM_LLM_API_KEY_HEADER", "Authorization"),
            api_key_prefix=os.getenv("AGENTIC_CM_LLM_API_KEY_PREFIX", "Bearer"),
            max_output_tokens=int(os.getenv("AGENTIC_CM_PATH_MAX_OUTPUT_TOKENS", "6000")),
            thinking_enabled=llm.thinking_enabled,
            reasoning_effort=llm.reasoning_effort,
        )
    raise PathAgentError(f"Unknown Path Agent adapter: {adapter}")
