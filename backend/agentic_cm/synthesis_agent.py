from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Annotated, Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .agent_runtime import (
    AgentTraceSink,
    ModelEndpoint,
    TraceNarration,
    request_structured_output,
)
from .config import agent_adapter_from_environment
from .domain import Case, OrchestrationPhase
from .llm import OpenAICompatibleClient, build_openai_compatible_client


class SynthesisAgentError(ValueError):
    pass


class SynthesisAgentOutputError(SynthesisAgentError):
    pass


class SynthesisAgentExecutionError(SynthesisAgentError):
    pass


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
PathStatus = Literal["SUCCEEDED", "FAILED"]
OwnerAction = Literal["CLOSE", "KEEP_OPEN", "MODIFY"]


_SYNTHESIS_NARRATION = TraceNarration(
    request="向 OpenAI-compatible Synthesis Agent 发送全 Path 汇总请求",
    repair_request="上次响应无效，发送一次结构化修复请求",
    retry_request="模型连接或请求超时，自动重试一次",
    response="收到 Synthesis Agent 模型响应",
    validation_failed="Synthesis Agent 响应未通过结构或引用校验",
    request_failed="Synthesis Agent 模型服务请求失败",
)


class _PathAssessmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path_id: NonEmptyText
    status: PathStatus
    conclusion: NonEmptyText
    supporting_refs: list[NonEmptyText] = Field(min_length=1)
    risks: list[NonEmptyText]


class _SynthesisResultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: NonEmptyText
    path_assessments: list[_PathAssessmentPayload] = Field(min_length=1)
    cross_path_findings: list[NonEmptyText]
    remaining_risks: list[NonEmptyText]
    recommended_owner_action: OwnerAction
    decision_brief: NonEmptyText


@dataclass(frozen=True)
class SynthesisContext:
    case_snapshot: dict[str, Any]
    manifest_ref: dict[str, Any]
    path_results: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class PathAssessment:
    path_id: str
    status: PathStatus
    conclusion: str
    supporting_refs: tuple[str, ...]
    risks: tuple[str, ...]


@dataclass(frozen=True)
class SynthesisResult:
    summary: str
    path_assessments: tuple[PathAssessment, ...]
    cross_path_findings: tuple[str, ...]
    remaining_risks: tuple[str, ...]
    recommended_owner_action: OwnerAction
    decision_brief: str
    adapter_profile: str


class SynthesisAgentAdapter(Protocol):
    async def generate(
        self,
        context: SynthesisContext,
        trace: AgentTraceSink,
    ) -> SynthesisResult: ...


class DeterministicSynthesisAgentAdapter:
    """Keyless aggregation that only restates approved or rejected Path artifacts."""

    profile = "deterministic-synthesis/v1"

    async def generate(
        self,
        context: SynthesisContext,
        trace: AgentTraceSink,
    ) -> SynthesisResult:
        trace(
            "model.request",
            "COMPLETED",
            "Deterministic Synthesis Adapter 接收全部终态 Path 结果",
            {"context": asdict(context), "adapter": self.profile},
        )
        assessments: list[PathAssessment] = []
        for item in context.path_results:
            solution = item["solution_revision"]
            status: PathStatus = item["status"]
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
                supporting_refs=(
                    f"{item['path_id']}/solution-revision/{solution['revision']}",
                    *commitment_refs,
                ),
                risks=tuple(solution.get("evidence_gaps", [])),
            ))
        successful = [item for item in assessments if item.status == "SUCCEEDED"]
        failed = [item for item in assessments if item.status == "FAILED"]
        action: OwnerAction = "CLOSE" if successful and not failed else "KEEP_OPEN" if successful else "MODIFY"
        result = SynthesisResult(
            summary=f"已汇总 {len(assessments)} 条已探索 Path：{len(successful)} 条审批通过，{len(failed)} 条审批失败。",
            path_assessments=tuple(assessments),
            cross_path_findings=("各 Path 结论均来自其 SolutionRevision 与人类审批节点，未补充新的业务证据。",),
            remaining_risks=tuple(dict.fromkeys(risk for item in assessments for risk in item.risks)),
            recommended_owner_action=action,
            decision_brief="请 Case Owner 基于成功与失败 Path 的完整记录选择关闭、保持 Open 或打回 Orchestrator；本报告不替代最终决定。",
            adapter_profile=self.profile,
        )
        trace(
            "model.response",
            "COMPLETED",
            "Deterministic Synthesis Adapter 返回结构化汇总报告",
            {"result": _result_payload(result)},
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
        client: OpenAICompatibleClient | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not model.strip() or not base_url.strip():
            raise SynthesisAgentError("Synthesis Agent requires a model id and base URL")
        if max_output_tokens < 1000:
            raise SynthesisAgentError("Synthesis Agent max output tokens must be at least 1000")
        try:
            self._client = client or build_openai_compatible_client(
                api_key,
                base_url=base_url,
                api_key_header=api_key_header,
                api_key_prefix=api_key_prefix,
                timeout_seconds=timeout_seconds,
                http_client=http_client,
            )
        except ValueError as exc:
            raise SynthesisAgentError(str(exc)) from exc
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._api_key_header = api_key_header
        self._max_output_tokens = max_output_tokens
        self._endpoint = ModelEndpoint(
            client=self._client,
            base_url=self._base_url,
            api_key_header=api_key_header,
            api_key_present=bool(api_key),
        )

    @property
    def profile(self) -> str:
        return f"openai-compatible-synthesis/{self._model}"

    async def generate(self, context: SynthesisContext, trace: AgentTraceSink) -> SynthesisResult:
        schema = _SynthesisResultPayload.model_json_schema()
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
                        f"{json.dumps(schema)}"
                    ),
                },
                {"role": "user", "content": json.dumps(asdict(context), ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": self._max_output_tokens,
            "stream": False,
        }
        def build_result(payload: _SynthesisResultPayload) -> SynthesisResult:
            result = _parse_result(payload, self.profile)
            _validate_result(result, context)
            return result

        return await request_structured_output(
            self._endpoint,
            request,
            agent_label="Synthesis Agent",
            trace=trace,
            step_prefix="model",
            narration=_SYNTHESIS_NARRATION,
            payload_model=_SynthesisResultPayload,
            build_result=build_result,
            repair_instruction=lambda exc: (
                f"The previous output was invalid: {exc}. Return valid JSON only. "
                "Copy supporting_refs exactly from each Path's authorized_supporting_refs. "
                "Remember that READY Commitments are already approved by humans."
            ),
            execution_error=SynthesisAgentExecutionError,
            output_error=SynthesisAgentOutputError,
            # Paraphrased supporting_refs are schema-valid but must still be repaired.
            recoverable_output_errors=(SynthesisAgentOutputError,),
        )


class SynthesisAgent:
    def __init__(self, adapter: SynthesisAgentAdapter) -> None:
        self.adapter = adapter

    async def run(self, case: Case, trace: AgentTraceSink) -> dict[str, Any]:
        trace("synthesis.eligibility", "STARTED", "检查全部已选 Path 的审批 DAG 是否终态", {
            "case_id": case.id, "case_version": case.version, "phase": case.phase.value
        })
        if (
            case.phase is not OrchestrationPhase.FINAL_REVIEW
            or case.manifest is None
            or case.status.value == "CLOSED"
        ):
            raise SynthesisAgentError("Case is not awaiting Synthesis in FINAL_REVIEW")
        selected_paths = [path for path in case.manifest.paths if path.selected]
        path_results: list[dict[str, Any]] = []
        for path in selected_paths:
            attempt = next((item for item in case.path_attempts if item.get("path_id") == path.id), None)
            nodes = [node for node in case.commitment_nodes if node.path_id == path.id]
            if not attempt or not isinstance(attempt.get("solution_revision"), dict):
                raise SynthesisAgentError(f"Path {path.id} has no SolutionRevision")
            if attempt.get("phase") != "DONE" or attempt.get("outcome") not in {"SUCCEEDED", "REJECTED"}:
                raise SynthesisAgentError(f"Path {path.id} approval DAG is not terminal")
            status: PathStatus = "SUCCEEDED" if attempt["outcome"] == "SUCCEEDED" else "FAILED"
            authorized_refs = [
                f"{path.id}/solution-revision/{attempt['solution_revision']['revision']}",
                *(
                    f"{path.id}/commitment/{node.id}"
                    for node in nodes
                ),
            ]
            path_results.append({
                "path_id": path.id,
                "definition": path.definition,
                "title": path.title,
                "status": status,
                "solution_revision": attempt["solution_revision"],
                "commitments": [asdict(node) for node in nodes],
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
                "human_proposal": dict(case.human_proposal) if case.human_proposal else None,
            },
            manifest_ref={"id": case.manifest.id, "revision": case.manifest.revision},
            path_results=tuple(path_results),
        )
        trace("agent.input", "COMPLETED", "构造包含成功与失败 Path 的只读 SynthesisContext", {
            "context": asdict(context)
        })
        result = await self.adapter.generate(context, trace)
        _validate_result(result, context)
        revision = int((case.synthesis_report or {}).get("revision", 0)) + 1
        report = {
            "schema_version": 1,
            "revision": revision,
            "summary": result.summary,
            "path_assessments": [{
                "path_id": item.path_id,
                "status": item.status,
                "conclusion": item.conclusion,
                "supporting_refs": list(item.supporting_refs),
                "risks": list(item.risks),
            } for item in result.path_assessments],
            "cross_path_findings": list(result.cross_path_findings),
            "remaining_risks": list(result.remaining_risks),
            "recommended_owner_action": result.recommended_owner_action,
            "decision_brief": result.decision_brief,
            "generated_by": result.adapter_profile,
            "manifest_ref": context.manifest_ref,
        }
        trace("synthesis.compose", "COMPLETED", "组装受平台约束的 CaseSynthesis 报告", {
            "report": report
        })
        return report


def _validate_result(result: SynthesisResult, context: SynthesisContext) -> None:
    expected = {item["path_id"]: item["status"] for item in context.path_results}
    returned = {item.path_id: item.status for item in result.path_assessments}
    if returned != expected or len(returned) != len(result.path_assessments):
        raise SynthesisAgentOutputError(
            f"Synthesis must assess every supplied Path once with its platform status: expected={expected}, returned={returned}"
        )
    allowed_refs_by_path = {
        item["path_id"]: set(item["authorized_supporting_refs"])
        for item in context.path_results
    }
    unknown = {
        ref for assessment in result.path_assessments
        for ref in assessment.supporting_refs
        if ref not in allowed_refs_by_path[assessment.path_id]
    }
    if unknown:
        raise SynthesisAgentOutputError(f"Synthesis references unknown artifacts: {sorted(unknown)}")


def _result_payload(result: SynthesisResult) -> dict[str, Any]:
    return {
        "summary": result.summary,
        "path_assessments": [asdict(item) for item in result.path_assessments],
        "cross_path_findings": list(result.cross_path_findings),
        "remaining_risks": list(result.remaining_risks),
        "recommended_owner_action": result.recommended_owner_action,
        "decision_brief": result.decision_brief,
    }


def _parse_result(payload: _SynthesisResultPayload, profile: str) -> SynthesisResult:
    return SynthesisResult(
        summary=payload.summary,
        path_assessments=tuple(PathAssessment(
            path_id=item.path_id,
            status=item.status,
            conclusion=item.conclusion,
            supporting_refs=tuple(item.supporting_refs),
            risks=tuple(item.risks),
        ) for item in payload.path_assessments),
        cross_path_findings=tuple(payload.cross_path_findings),
        remaining_risks=tuple(payload.remaining_risks),
        recommended_owner_action=payload.recommended_owner_action,
        decision_brief=payload.decision_brief,
        adapter_profile=profile,
    )


def synthesis_agent_from_environment() -> SynthesisAgentAdapter:
    adapter = agent_adapter_from_environment()
    if adapter == "deterministic":
        return DeterministicSynthesisAgentAdapter()
    if adapter == "openai-compatible":
        return OpenAICompatibleSynthesisAgentAdapter(
            os.getenv("AGENTIC_CM_LLM_API_KEY"),
            model=os.getenv("AGENTIC_CM_LLM_MODEL", ""),
            base_url=os.getenv("AGENTIC_CM_LLM_BASE_URL", ""),
            api_key_header=os.getenv("AGENTIC_CM_LLM_API_KEY_HEADER", "Authorization"),
            api_key_prefix=os.getenv("AGENTIC_CM_LLM_API_KEY_PREFIX", "Bearer"),
            max_output_tokens=int(os.getenv("AGENTIC_CM_SYNTHESIS_MAX_OUTPUT_TOKENS", "4000")),
        )
    raise SynthesisAgentError(f"Unknown Synthesis Agent adapter: {adapter}")
