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
    openai_model_endpoint,
    request_structured_output,
)
from .config import (
    ReasoningEffort,
    agent_adapter_from_environment,
    agent_llm_config_from_environment,
    deterministic_delay_seconds_from_environment,
)
from .domain import (
    Case,
    OrchestrationPhase,
    OwnerDecisionAction,
    PathAssessment,
    PathAttemptState,
    PathOutcome,
    SynthesisReport,
    SynthesisResult,
)


_SYNTHESIS_NARRATION = TraceNarration(
    request="向 OpenAI-compatible Synthesis Agent 发送全 Path 汇总请求",
    repair_request="上次响应无效，发送一次结构化修复请求",
    retry_request="模型连接或请求超时，自动重试一次",
    response="收到 Synthesis Agent 模型响应",
    validation_failed="Synthesis Agent 响应未通过结构或引用校验",
    request_failed="Synthesis Agent 模型服务请求失败",
)


class SynthesisContext:
    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)

    def prompt_payload(self) -> dict[str, Any]:
        path_results = []
        for item in self.path_results:
            revision = item["solution_revision"]
            path_results.append({
                "path_id": item["path_id"],
                "definition": item["definition"],
                "title": item["title"],
                "status": item["status"],
                "solution_revision": {
                    key: revision[key]
                    for key in (
                        "revision", "summary", "options",
                        "recommendation", "evidence_gaps", "role_reports",
                    )
                    if key in revision
                },
                "commitments": [
                    {key: node[key] for key in ("id", "role", "review_dimension", "status") if key in node}
                    for node in item["commitments"]
                ],
                "authorized_supporting_refs": item["authorized_supporting_refs"],
            })
        return {
            "case_snapshot": self.case_snapshot,
            "manifest_ref": self.manifest_ref,
            "path_results": path_results,
        }


class SynthesisAgentAdapter(Protocol):
    async def generate(self, context: SynthesisContext, trace: AgentTraceSink) -> SynthesisResult: ...


class DeterministicSynthesisAgentAdapter:
    profile = "deterministic-synthesis/v1"

    def __init__(self, delay_seconds: float = 0.0) -> None:
        self._delay_seconds = delay_seconds

    async def generate(self, context: SynthesisContext, trace: AgentTraceSink) -> SynthesisResult:
        trace(
            "model.request",
            "COMPLETED",
            "Deterministic Synthesis Adapter 接收全部终态 Path 结果",
            {"context": context.prompt_payload(), "adapter": self.profile},
        )
        await asyncio.sleep(self._delay_seconds)
        assessments: list[PathAssessment] = []
        for item in context.path_results:
            solution = item["solution_revision"]
            status: PathOutcome = item["status"]
            commitment_refs = [
                f"{item['path_id']}/commitment/{node['id']}"
                for node in item["commitments"]
                if node["status"] in {"READY", "REJECTED"}
            ]
            assessments.append(PathAssessment(
                path_id=item["path_id"],
                status=status,
                conclusion=(
                    f"{item['title']}的专业审批 DAG 已全部通过，可作为 Owner 决策输入。"
                    if status == "SUCCEEDED"
                    else f"{item['title']}在专业审批中被否决，失败结果与已形成方案均保留供比较。"
                ),
                supporting_refs=[
                    f"{item['path_id']}/solution-revision/{solution['revision']}",
                    *commitment_refs,
                ],
                risks=list(solution.get("evidence_gaps", [])),
            ))
        successful = [item for item in assessments if item.status == "SUCCEEDED"]
        failed = [item for item in assessments if item.status == "FAILED"]
        if successful and not failed:
            action = OwnerDecisionAction.CLOSE
        elif successful:
            action = OwnerDecisionAction.KEEP_OPEN
        else:
            action = OwnerDecisionAction.MODIFY
        result = SynthesisResult(
            summary=f"已汇总 {len(assessments)} 条已探索 Path：{len(successful)} 条审批通过，{len(failed)} 条审批失败。",
            path_assessments=assessments,
            cross_path_findings=["各 Path 结论均来自其 SolutionRevision 与人类审批节点，未补充新的业务证据。"],
            remaining_risks=list(dict.fromkeys(risk for item in assessments for risk in item.risks)),
            recommended_owner_action=action,
            decision_brief="请 Case Owner 基于成功与失败 Path 的完整记录选择关闭、保持 Open 或打回 Orchestrator；本报告不替代最终决定。",
        )
        trace(
            "model.response",
            "COMPLETED",
            "Deterministic Synthesis Adapter 返回结构化汇总报告",
            {"result": result.model_dump(mode="json")},
        )
        return result


class OpenAICompatibleSynthesisAgentAdapter:
    def __init__(
        self,
        api_key: str | None,
        *,
        model: str,
        base_url: str,
        api_key_header: str = "Authorization",
        api_key_prefix: str = "Bearer",
        timeout_seconds: float = 45.0,
        max_output_tokens: int = 4000,
        thinking_enabled: bool = False,
        reasoning_effort: ReasoningEffort = "high",
        client=None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if max_output_tokens < 1000:
            raise AgentError("Synthesis Agent max output tokens must be at least 1000")
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
        return f"openai-compatible-synthesis/{self._model}"

    async def generate(self, context: SynthesisContext, trace: AgentTraceSink) -> SynthesisResult:
        prompt = context.prompt_payload()
        trace("model.context_projection", "COMPLETED", "构造 Synthesis 模型上下文", {"context": prompt})
        request: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a Synthesis Agent. Aggregate every supplied successful and failed Path. "
                        "Use only the supplied SolutionRevisions and human Commitment states; never invent "
                        "evidence, Paths, approvals, actions, quantities, or dates. Write all human-facing "
                        "fields in Chinese. A Commitment status of READY means that its responsible human "
                        "has already approved it; never describe READY as pending or unapproved. For each "
                        "Path assessment, supporting_refs must copy one or more exact strings from that "
                        "Path's authorized_supporting_refs array; do not paraphrase or create references. "
                        "Return JSON only and match this schema exactly: "
                        f"{json.dumps(SynthesisResult.model_json_schema())}"
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

        def build_result(payload: SynthesisResult) -> SynthesisResult:
            _validate_result(payload, context)
            return payload

        return await request_structured_output(
            self._endpoint,
            request,
            agent_label="Synthesis Agent",
            trace=trace,
            step_prefix="model",
            narration=_SYNTHESIS_NARRATION,
            payload_model=SynthesisResult,
            build_result=build_result,
            repair_instruction=lambda exc: (
                f"The previous output was invalid: {exc}. Return valid JSON only. "
                "Copy supporting_refs exactly from each Path's authorized_supporting_refs. "
                "Remember that READY Commitments are already approved by humans."
            ),
            execution_error=AgentExecutionError,
            output_error=AgentOutputError,
            recoverable_output_errors=(AgentOutputError,),
        )


class SynthesisAgent:
    def __init__(self, adapter: SynthesisAgentAdapter) -> None:
        self.adapter = adapter

    async def run(
        self,
        case: Case,
        path_titles: dict[str, str],
        trace: AgentTraceSink,
    ) -> SynthesisReport:
        trace("synthesis.eligibility", "STARTED", "检查全部已选 Path 的审批 DAG 是否终态", {
            "case_id": case.id, "case_version": case.version, "phase": case.phase.value
        })
        if (
            case.phase is not OrchestrationPhase.FINAL_REVIEW
            or case.manifest is None
            or case.status.value == "CLOSED"
        ):
            raise AgentError("Case is not awaiting Synthesis in FINAL_REVIEW")
        selected_paths = [path for path in case.manifest.paths if path.selected]
        path_results: list[dict[str, Any]] = []
        for path in selected_paths:
            attempt = next((item for item in case.path_attempts if item.path_id == path.id), None)
            nodes = [node for node in case.commitment_nodes if node.path_id == path.id]
            if not attempt or attempt.solution_revision is None:
                raise AgentError(f"Path {path.id} has no SolutionRevision")
            if attempt.state not in {PathAttemptState.SUCCEEDED, PathAttemptState.REJECTED}:
                raise AgentError(f"Path {path.id} approval DAG is not terminal")
            status: PathOutcome = "SUCCEEDED" if attempt.state is PathAttemptState.SUCCEEDED else "FAILED"
            revision = attempt.solution_revision
            authorized_refs = [
                f"{path.id}/solution-revision/{revision.revision}",
                *(f"{path.id}/commitment/{node.id}" for node in nodes),
            ]
            path_results.append({
                "path_id": path.id,
                "definition": path.definition,
                "title": path_titles.get(path.definition, path.definition),
                "status": status,
                "solution_revision": revision.model_dump(mode="json"),
                "commitments": [node.model_dump(mode="json") for node in nodes],
                "authorized_supporting_refs": authorized_refs,
            })
        trace("synthesis.eligibility", "COMPLETED", "全部已选 Path 已终态，允许生成汇总报告", {
            "path_statuses": {item["path_id"]: item["status"] for item in path_results}
        })
        context = SynthesisContext(
            case_snapshot={
                "id": case.id,
                "version": case.version,
                "title": case.title,
                "description": case.description,
                "status": case.status.value,
                "business_payload": dict(case.business_payload),
                "human_proposal": (
                    case.human_proposal.model_dump(mode="json") if case.human_proposal else None
                ),
            },
            manifest_ref={"id": case.manifest.id, "revision": case.manifest.revision},
            path_results=tuple(path_results),
        )
        trace("agent.input", "COMPLETED", "构造包含成功与失败 Path 的只读 Synthesis 上下文", {
            "context": context.prompt_payload()
        })
        result = await self.adapter.generate(context, trace)
        _validate_result(result, context)
        report = SynthesisReport(
            **result.model_dump(),
            revision=(case.synthesis_report.revision if case.synthesis_report else 0) + 1,
            generated_by=getattr(self.adapter, "profile", type(self.adapter).__name__),
            manifest_ref=context.manifest_ref,
        )
        trace("synthesis.compose", "COMPLETED", "组装受平台约束的 CaseSynthesis 报告", {
            "report": report.model_dump(mode="json")
        })
        return report


def _validate_result(result: SynthesisResult, context: SynthesisContext) -> None:
    expected = {item["path_id"]: item["status"] for item in context.path_results}
    returned = {item.path_id: item.status for item in result.path_assessments}
    if returned != expected or len(returned) != len(result.path_assessments):
        raise AgentOutputError(
            f"Synthesis must assess every supplied Path once with its platform status: expected={expected}, returned={returned}"
        )
    allowed_refs_by_path = {
        item["path_id"]: set(item["authorized_supporting_refs"])
        for item in context.path_results
    }
    unknown = {
        ref
        for assessment in result.path_assessments
        for ref in assessment.supporting_refs
        if ref not in allowed_refs_by_path[assessment.path_id]
    }
    if unknown:
        raise AgentOutputError(f"Synthesis references unknown artifacts: {sorted(unknown)}")


def synthesis_agent_from_environment() -> SynthesisAgentAdapter:
    adapter = agent_adapter_from_environment()
    if adapter == "deterministic":
        return DeterministicSynthesisAgentAdapter(
            delay_seconds=deterministic_delay_seconds_from_environment()
        )
    if adapter == "openai-compatible":
        llm = agent_llm_config_from_environment("synthesis")
        return OpenAICompatibleSynthesisAgentAdapter(
            os.getenv("AGENTIC_CM_LLM_API_KEY"),
            model=llm.model,
            base_url=os.getenv("AGENTIC_CM_LLM_BASE_URL", ""),
            api_key_header=os.getenv("AGENTIC_CM_LLM_API_KEY_HEADER", "Authorization"),
            api_key_prefix=os.getenv("AGENTIC_CM_LLM_API_KEY_PREFIX", "Bearer"),
            max_output_tokens=int(os.getenv("AGENTIC_CM_SYNTHESIS_MAX_OUTPUT_TOKENS", "4000")),
            thinking_enabled=llm.thinking_enabled,
            reasoning_effort=llm.reasoning_effort,
        )
    raise AgentError(f"Unknown Synthesis Agent adapter: {adapter}")
