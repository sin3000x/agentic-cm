from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Protocol

import httpx

from .agent_runtime import (
    AgentError,
    AgentExecutionError,
    AgentOutputError,
    AgentTraceSink,
    TraceNarration,
    configure_thinking,
    contains_chinese,
    openai_model_endpoint,
    request_structured_output,
)
from .capabilities import CapabilityResolution
from .config import (
    ReasoningEffort,
    agent_adapter_from_environment,
    agent_llm_config_from_environment,
    deterministic_delay_seconds_from_environment,
    llm_timeout_seconds_from_environment,
)
from .domain import (
    Case,
    OrchestrationPhase,
    PathAgentResult,
    PathAttemptState,
    ProposedOption,
    Recommendation,
    RoleReport,
    SolutionRevision,
)


_PATH_AGENT_NARRATION = TraceNarration(
    request="向 OpenAI-compatible Path Agent 发送 Manifest 组装请求",
    repair_request="上次响应无效，发送一次结构化修复请求",
    retry_request="模型连接或请求超时，自动重试一次",
    response="收到 Path Agent 模型响应",
    validation_failed="Path Agent 响应未通过结构化校验",
    request_failed="Path Agent 模型服务请求失败",
)


class PathAgentContext:
    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)

    def prompt_payload(self) -> dict[str, Any]:
        return {
            "case_snapshot": self.case_snapshot,
            "human_proposal": self.human_proposal,
            "manifest_ref": self.manifest_ref,
            "path": self.path,
            "path_attempt": self.path_attempt,
            "execution_skills": [
                {
                    "id": skill["id"],
                    "version": skill["version"],
                    "description": skill["description"],
                    "instructions_markdown": skill["instructions_markdown"],
                }
                for skill in self.execution_skills
            ],
            "knowledge": [
                {
                    key: item[key]
                    for key in (
                        "id", "version", "title", "knowledge_type",
                        "source", "confidence", "content",
                    )
                    if key in item
                }
                for item in self.knowledge
            ],
            "authorized_options": list(self.authorized_options),
            "tool_results": list(self.tool_results),
            "required_role_reports": list(self.required_role_reports),
            "previous_solution_revision": (
                self.previous_solution_revision.model_dump(mode="json")
                if self.previous_solution_revision
                else None
            ),
        }


class PathAgentAdapter(Protocol):
    async def generate(self, context: PathAgentContext, trace: AgentTraceSink) -> PathAgentResult: ...


class DeterministicPathAgentAdapter:
    profile = "deterministic-path/v1"

    def __init__(self, delay_seconds: float = 0.0) -> None:
        self._delay_seconds = delay_seconds

    async def generate(self, context: PathAgentContext, trace: AgentTraceSink) -> PathAgentResult:
        trace(
            "model.request",
            "COMPLETED",
            "Deterministic Path Adapter 接收 Manifest 组装上下文",
            {"context": context.prompt_payload(), "adapter": self.profile},
        )
        await asyncio.sleep(self._delay_seconds)
        options = tuple(
            ProposedOption(
                id=str(item["id"]),
                title=str(item.get("title") or item["id"]),
                description=str(item.get("description") or "作为冻结 Skill 候选进入并行核验。"),
                benefits=["保留原订单目标的探索空间"],
                risks=["当前供应与技术证据尚未由责任角色确认"],
                assumptions=["仅为分析提案，不代表物料、数量或交期承诺"],
            )
            for item in context.authorized_options
            if isinstance(item, dict) and item.get("id")
        )
        if not options:
            options = (
                ProposedOption(
                    id="OPTION-01",
                    title=context.path["title"],
                    description="按冻结 Skill 生成的待核验分析选项。",
                    benefits=["形成可审查的结构化提案"],
                    risks=["缺少可确认的候选事实"],
                    assumptions=["所有业务结论均等待责任角色确认"],
                ),
            )
        option_reference = "、".join(option.id for option in options)
        result = PathAgentResult(
            summary="已依据 Manifest 冻结的执行 Skill 形成替代方案草案；尚未作出业务承诺。",
            options=list(options),
            recommendation=Recommendation(
                option_ids=[],
                rationale="deterministic 模式不判断候选业务优先级。",
            ),
            evidence_gaps=["供应、技术与客户接受度需要由 Manifest 编译出的责任角色确认"],
            role_reports=[
                RoleReport(
                    role=contract["role"],
                    dimension=contract["dimension"],
                    report=(
                        f"{contract['role']}维度：冻结 Skill 中的{option_reference}已按{contract['dimension']}形成比较，"
                        f"但模拟查询结果仍须由{contract['role']}核验后才能形成业务判断。"
                    ),
                )
                for contract in context.required_role_reports
            ],
        )
        trace(
            "model.response",
            "COMPLETED",
            "Deterministic Path Adapter 返回结构化 SolutionRevision 草案",
            {"result": result.model_dump(mode="json")},
        )
        return result


class OpenAICompatiblePathAgentAdapter:
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
        client=None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if max_output_tokens < 1000:
            raise AgentError("Path Agent max output tokens must be at least 1000")
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._thinking_enabled = thinking_enabled
        self._reasoning_effort = reasoning_effort
        self._endpoint = openai_model_endpoint(
            api_key,
            model=model,
            base_url=base_url,
            api_key_header=api_key_header,
            api_key_prefix=api_key_prefix,
            timeout_seconds=timeout_seconds,
            http_client=http_client,
            client=client,
        )

    @property
    def profile(self) -> str:
        return f"openai-compatible-path/{self._model}"

    async def generate(self, context: PathAgentContext, trace: AgentTraceSink) -> PathAgentResult:
        prompt = context.prompt_payload()
        trace("model.context_projection", "COMPLETED", "构造 Path Agent 模型上下文", {"context": prompt})
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
                        f"Match this JSON Schema exactly: {json.dumps(PathAgentResult.model_json_schema())}. "
                        "Return role_reports for exactly the Policy-triggered contracts in "
                        "required_role_reports, with no missing or extra role/dimension pair; "
                        "if required_role_reports is empty, return an empty role_reports array. "
                        "Keep the JSON concise: at most two short items in each benefits, risks, assumptions, "
                        "and evidence_gaps array. Do not repeat the full evidence outside the required role reports."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": self._max_output_tokens,
            "stream": False,
        }
        configure_thinking(
            request, enabled=self._thinking_enabled, reasoning_effort=self._reasoning_effort
        )

        def build_result(payload: PathAgentResult) -> PathAgentResult:
            _require_chinese(payload)
            _validate_result_against_context(payload, context)
            return payload

        return await request_structured_output(
            self._endpoint,
            request,
            agent_label="Path Agent",
            trace=trace,
            step_prefix="model",
            narration=_PATH_AGENT_NARRATION,
            payload_model=PathAgentResult,
            build_result=build_result,
            repair_instruction=lambda exc: (
                f"The previous output was invalid: {exc}. Return one non-empty JSON object "
                "matching the exact schema, every authorized option, and exactly the "
                "Policy-triggered required_role_reports with no extra role/dimension pair."
            ),
            execution_error=AgentExecutionError,
            output_error=AgentOutputError,
            recoverable_output_errors=(AgentOutputError,),
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
    ) -> SolutionRevision:
        trace(
            "path.eligibility",
            "STARTED",
            "检查已批准 Path 是否允许生成 SolutionRevision",
            {
                "case_id": case.id,
                "case_version": case.version,
                "phase": case.phase.value,
                "path_id": path_id,
            },
        )
        if case.phase is not OrchestrationPhase.PATH_EXPLORATION or case.manifest is None:
            raise AgentError("Case is not in PATH_EXPLORATION with an approved Manifest")
        path = next((item for item in case.manifest.paths if item.id == path_id and item.selected), None)
        if path is None:
            raise AgentError(f"Unknown selected Manifest Path: {path_id}")
        attempt = next((item for item in case.path_attempts if item.path_id == path_id), None)
        if attempt is None:
            raise AgentError(f"PathAttempt does not exist for {path_id}")
        trace("path.eligibility", "COMPLETED", "Path 与冻结 Manifest 能力通过执行门禁")

        execution_skills = tuple(resolution.asset_payloads["skills"])
        if not execution_skills:
            raise AgentError(f"Frozen Manifest has no execution Skill for {path.definition}")
        policies = tuple(resolution.asset_payloads["policies"])
        knowledge = tuple(resolution.asset_payloads["knowledge"])
        commitments = list(resolution.compiled_policy.get("commitments", []))
        if not commitments:
            raise AgentError(f"Frozen Manifest has no mandatory Policy for {path.definition}")
        missing_report_contracts = [
            commitment.get("id", "<unknown>")
            for commitment in commitments
            if not isinstance(commitment.get("review_dimension"), str)
            or not commitment["review_dimension"].strip()
        ]
        if missing_report_contracts:
            raise AgentError(
                "Frozen Manifest Policy commitments have no role-report contract; "
                f"regenerate the Manifest with current Policies: {missing_report_contracts}"
            )
        previous = attempt.solution_revision
        if previous and attempt.state is not PathAttemptState.REVISING:
            raise AgentError("An existing SolutionRevision can only be regenerated after a human revision request")

        option_contracts = [
            tuple(skill.get("path_options", []))
            for skill in execution_skills
            if skill.get("path_options")
        ]
        if len(option_contracts) > 1 and any(contract != option_contracts[0] for contract in option_contracts[1:]):
            raise AgentError("Frozen execution Skills define conflicting Path options")
        authorized_options = option_contracts[0] if option_contracts else ()
        required_role_reports = tuple(
            {"role": commitment["role"], "dimension": commitment["review_dimension"]}
            for commitment in commitments
        )
        role_keys = [(item["role"], item["dimension"]) for item in required_role_reports]
        if len(set(role_keys)) != len(role_keys):
            raise AgentError("Frozen Policies define duplicate role report contracts")

        tools_by_id: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        for skill in execution_skills:
            for tool in skill.get("tools", []):
                current = tools_by_id.get(tool["id"])
                if current and current[0] != tool:
                    raise AgentError(f"Frozen execution Skills define conflicting tool {tool['id']}")
                tools_by_id[tool["id"]] = (tool, skill)
        trace(
            "agent.assemble",
            "COMPLETED",
            "从 Manifest 冻结引用组装 Path Agent",
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
            },
        )
        tool_results: list[dict[str, Any]] = []
        for tool_id, (tool, skill) in sorted(tools_by_id.items()):
            for option in authorized_options:
                option_id = option["id"]
                if option_id not in tool["records"]:
                    raise AgentError(f"Frozen tool {tool_id} has no record for option {option_id}")
                tool_results.append({
                    "tool_id": tool_id,
                    "description": tool["description"],
                    "read_only": True,
                    "input": {tool["input_key"]: option_id},
                    "output": tool["records"][option_id],
                    "source_skill": _safe_ref(skill),
                })
        if tool_results:
            trace("tools.query", "COMPLETED", "执行 Manifest 冻结的只读模拟查询", {"results": tool_results})
        context = PathAgentContext(
            case_snapshot={
                "id": case.id,
                "version": case.version,
                "title": case.title,
                "description": case.description,
                "classification": dict(case.classification),
                "business_payload": dict(case.business_payload),
            },
            human_proposal=case.human_proposal.model_dump(mode="json") if case.human_proposal else None,
            manifest_ref={
                "id": case.manifest.id,
                "revision": case.manifest.revision,
                "generated_from_case_version": case.manifest.generated_from_case_version,
            },
            path=path.model_dump(mode="json") | {"title": path_title},
            path_attempt={"path_id": attempt.path_id, "state": attempt.state.value},
            execution_skills=execution_skills,
            knowledge=knowledge,
            authorized_options=authorized_options,
            authorized_option_ids=tuple(item["id"] for item in authorized_options),
            tool_results=tuple(tool_results),
            required_role_reports=required_role_reports,
            previous_solution_revision=previous,
        )
        trace("agent.input", "COMPLETED", "构造冻结、最小授权的 Path Agent 上下文", {"context": context.prompt_payload()})
        result = await self.adapter.generate(context, trace)
        _require_chinese(result)
        _validate_result_against_context(result, context)
        revision = SolutionRevision(
            **result.model_dump(),
            revision=(previous.revision if previous else 0) + 1,
            generated_by=getattr(self.adapter, "profile", type(self.adapter).__name__),
        )
        trace(
            "solution_revision.compose",
            "COMPLETED",
            "组装受平台约束的 SolutionRevision",
            {"solution_revision": revision.model_dump(mode="json")},
        )
        return revision


def _safe_ref(payload: dict[str, Any]) -> dict[str, Any]:
    ref = payload.get("resolved_ref", {})
    return {key: ref.get(key) for key in ("id", "version", "digest", "source")}


def _require_chinese(result: PathAgentResult) -> None:
    values = [
        result.summary,
        result.recommendation.rationale,
        *result.evidence_gaps,
        *(
            value
            for option in result.options
            for value in (option.title, option.description, *option.benefits, *option.risks, *option.assumptions)
        ),
        *(value for report in result.role_reports for value in (report.role, report.dimension, report.report)),
    ]
    if any(not contains_chinese(value) for value in values):
        raise AgentOutputError("Path Agent 的全部面向人字段必须使用中文")


def _validate_result_against_context(result: PathAgentResult, context: PathAgentContext) -> None:
    option_ids = [option.id for option in result.options]
    unknown = set(result.recommendation.option_ids) - set(option_ids)
    if unknown:
        raise AgentOutputError(f"Recommendation references unknown options: {sorted(unknown)}")
    if context.authorized_option_ids and set(option_ids) != set(context.authorized_option_ids):
        raise AgentOutputError(
            "Path Agent must return every Manifest-authorized option exactly once; "
            f"missing={sorted(set(context.authorized_option_ids) - set(option_ids))}, "
            f"unknown={sorted(set(option_ids) - set(context.authorized_option_ids))}"
        )
    returned = {(item.role, item.dimension): item for item in result.role_reports}
    required = {(item["role"], item["dimension"]): item for item in context.required_role_reports}
    if set(returned) != set(required):
        raise AgentOutputError(
            "Path Agent must return every Skill-required role report exactly once; "
            f"missing={sorted(set(required) - set(returned))}, "
            f"unknown={sorted(set(returned) - set(required))}"
        )
    for key, contract in required.items():
        report = returned[key].report
        sentence_prefix = f"{contract['role']}维度："
        if not report.startswith(sentence_prefix):
            raise AgentOutputError(f"Role report {key} must start with {sentence_prefix}")
        if not all(option_id in report for option_id in context.authorized_option_ids):
            raise AgentOutputError(f"Role report {key} must mention every authorized option")
        if len(report) < 20 or report[-1] not in "。！？.!?":
            raise AgentOutputError(f"Role report {key} must be one complete sentence")


def path_agent_from_environment() -> PathAgentAdapter:
    adapter = agent_adapter_from_environment()
    if adapter == "deterministic":
        return DeterministicPathAgentAdapter(
            delay_seconds=deterministic_delay_seconds_from_environment()
        )
    if adapter == "openai-compatible":
        llm = agent_llm_config_from_environment("path")
        return OpenAICompatiblePathAgentAdapter(
            os.getenv("AGENTIC_CM_LLM_API_KEY"),
            model=llm.model,
            base_url=os.getenv("AGENTIC_CM_LLM_BASE_URL", ""),
            api_key_header=os.getenv("AGENTIC_CM_LLM_API_KEY_HEADER", "Authorization"),
            api_key_prefix=os.getenv("AGENTIC_CM_LLM_API_KEY_PREFIX", "Bearer"),
            timeout_seconds=llm_timeout_seconds_from_environment(),
            max_output_tokens=int(os.getenv("AGENTIC_CM_PATH_MAX_OUTPUT_TOKENS", "6000")),
            thinking_enabled=llm.thinking_enabled,
            reasoning_effort=llm.reasoning_effort,
        )
    raise AgentError(f"Unknown Path Agent adapter: {adapter}")
