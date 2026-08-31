from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.backends.utils import create_file_data
from deepagents.profiles import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    register_harness_profile,
)
from langchain.agents.structured_output import ToolStrategy
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError
from pydantic import ValidationError

from .agent_runtime import (
    AgentError,
    AgentExecutionError,
    AgentOutputError,
    AgentTraceSink,
    contains_chinese,
)
from .capabilities import CapabilityResolution
from .config import (
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
    RoleReport,
    SolutionRevision,
)


_PATH_AGENT_SYSTEM_PROMPT = (
    "You are a Path Agent assembled only from an approved Manifest snapshot. "
    "Read and follow the authorized Skills available under /skills before producing a result. "
    "Treat Knowledge as advisory, never as current Case fact. Write one Chinese recommendation "
    "for this Path. Do not make business commitments, claim actions were executed, remove Policy "
    "duties, or invent confirmed quantities, dates, certifications, or approvals. "
    "Return role_reports for exactly the contracts in required_role_reports, with no missing or "
    "extra role/dimension pair; each report explains why this recommendation should be approved "
    "from that role's dimension and what that role still needs to confirm."
)

_PATH_HARNESS_PROFILE = HarnessProfile(
    excluded_tools=frozenset({"write_file", "edit_file", "delete", "execute"}),
    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
)
for _provider in ("agentic-cm", "openai"):
    register_harness_profile(_provider, _PATH_HARNESS_PROFILE)


@dataclass(frozen=True, slots=True)
class PathAgentContext:
    case_snapshot: dict[str, Any]
    human_proposal: dict[str, Any] | None
    path: dict[str, Any]
    execution_skills: tuple[dict[str, Any], ...]
    knowledge: tuple[dict[str, Any], ...]
    authorized_options: tuple[dict[str, Any], ...]
    tool_results: tuple[dict[str, Any], ...]
    required_role_reports: tuple[dict[str, str], ...]
    previous_solution_revision: SolutionRevision | None

    def prompt_payload(self) -> dict[str, Any]:
        grouped_tool_results: list[dict[str, Any]] = []
        tools_by_id: dict[str, dict[str, Any]] = {}
        for result in self.tool_results:
            tool_id = str(result["tool_id"])
            tool = tools_by_id.get(tool_id)
            if tool is None:
                tool = {"tool_id": tool_id, "records": {}}
                if "description" in result:
                    tool["description"] = result["description"]
                tools_by_id[tool_id] = tool
                grouped_tool_results.append(tool)
            option_id = next(iter(result["input"].values()))
            tool["records"][str(option_id)] = result["output"]

        payload: dict[str, Any] = {
            "case_snapshot": {
                key: self.case_snapshot[key]
                for key in ("description", "business_payload")
                if key in self.case_snapshot
            },
            "execution_skills": [
                {"id": skill["id"]}
                for skill in self.execution_skills
            ],
            "knowledge": [
                {
                    key: item[key]
                    for key in (
                        "title", "knowledge_type",
                        "source", "confidence", "content",
                    )
                    if key in item
                }
                for item in self.knowledge
            ],
            "authorized_options": list(self.authorized_options),
            "tool_results": grouped_tool_results,
            "required_role_reports": list(self.required_role_reports),
        }
        if self.human_proposal is not None:
            payload["human_proposal"] = {
                key: self.human_proposal[key]
                for key in ("author", "role", "content")
                if key in self.human_proposal
            }
        if self.previous_solution_revision is not None:
            payload["previous_solution_revision"] = self.previous_solution_revision.model_dump(
                mode="json",
                include={"recommendation", "role_reports"},
            )
        return payload


class PathAgentAdapter(Protocol):
    async def generate(self, context: PathAgentContext, trace: AgentTraceSink) -> PathAgentResult: ...


def _skill_files(context: PathAgentContext) -> dict[str, str]:
    return {
        f"/skills/{skill['id']}/SKILL.md": (
            "---\n"
            f"name: {skill['id']}\n"
            f"description: {skill.get('description', skill['id'])}\n"
            "---\n\n"
            f"{skill['instructions_markdown'].rstrip()}\n"
        )
        for skill in context.execution_skills
    }


def _truncate_error(value: str, *, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _exception_trace_details(exc: BaseException) -> dict[str, Any]:
    details: dict[str, Any] = {
        "error_type": type(exc).__name__,
        "error": _truncate_error(str(exc)),
    }
    cause = exc.__cause__ or exc.__context__
    if isinstance(cause, BaseException) and cause is not exc:
        details["cause_type"] = type(cause).__name__
        details["cause"] = _truncate_error(str(cause))
    return details


class DeepAgentPathAdapter:
    def __init__(self, model: BaseChatModel, *, profile: str) -> None:
        self._model = model
        self.profile = profile

    async def generate(
        self, context: PathAgentContext, trace: AgentTraceSink
    ) -> PathAgentResult:
        skill_files = _skill_files(context)
        trace(
            "deepagent.runtime.started",
            "STARTED",
            "启动 Deep Agents Path Runtime",
            {"profile": self.profile, "path": context.path.get("definition")},
        )
        trace(
            "deepagent.skill.projected",
            "COMPLETED",
            "投影 Manifest 授权的执行 Skill",
            {"skills": list(skill_files)},
        )
        try:
            agent = create_deep_agent(
                model=self._model,
                system_prompt=_PATH_AGENT_SYSTEM_PROMPT,
                skills=["/skills/"],
                backend=StateBackend(),
                subagents=[],
                response_format=ToolStrategy(PathAgentResult),
            )
            state = await agent.ainvoke(
                {
                    "messages": [{
                        "role": "user",
                        "content": json.dumps(context.prompt_payload(), ensure_ascii=False),
                    }],
                    "files": {
                        path: create_file_data(content)
                        for path, content in skill_files.items()
                    },
                },
                config={"recursion_limit": 20},
            )
        except GraphRecursionError as exc:
            trace(
                "deepagent.runtime.failed",
                "FAILED",
                "Deep Agents Path Runtime 未能收敛",
                _exception_trace_details(exc),
            )
            raise AgentOutputError("Path Agent did not produce structured output") from exc
        except Exception as exc:
            details = _exception_trace_details(exc)
            trace(
                "deepagent.runtime.failed",
                "FAILED",
                "Deep Agents Path Runtime 执行失败",
                details,
            )
            raise AgentExecutionError(
                "Path Agent model execution failed "
                f"({details['error_type']}: {details['error']})"
            ) from exc
        result: PathAgentResult | None = None
        raw_response = state.get("structured_response")
        try:
            result = PathAgentResult.model_validate(raw_response)
            _require_chinese(result)
            _validate_result_against_context(result, context)
        except (ValidationError, AgentOutputError) as exc:
            details = _exception_trace_details(exc)
            if result is not None:
                details["rejected_result"] = result.model_dump(mode="json")
            elif raw_response is not None:
                details["rejected_result"] = raw_response
            trace(
                "deepagent.runtime.failed",
                "FAILED",
                "Deep Agents Path Runtime 输出无效",
                details,
            )
            raise AgentOutputError(str(exc)) from exc
        trace(
            "deepagent.model.completed",
            "COMPLETED",
            "Deep Agents Path Runtime 返回结构化方案",
            {"result": result.model_dump(mode="json")},
        )
        return result


class _DeterministicPathChatModel(BaseChatModel):
    delay_seconds: float = 0.0

    @property
    def _llm_type(self) -> str:
        return "agentic-cm-deterministic-path"

    def _get_ls_params(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "ls_provider": "agentic-cm",
            "ls_model_name": "deterministic-path",
        }

    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any) -> BaseChatModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._response(messages))])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        await asyncio.sleep(self.delay_seconds)
        return self._generate(messages, stop=stop)

    def _response(self, messages: list[BaseMessage]) -> AIMessage:
        user_message = next(
            message for message in reversed(messages) if isinstance(message, HumanMessage)
        )
        prompt = json.loads(str(user_message.content))
        option_ids = [str(item["id"]) for item in prompt.get("authorized_options", [])]
        option_reference = "、".join(option_ids) if option_ids else "授权候选"
        result = PathAgentResult(
            recommendation=(
                f"已依据 Manifest 冻结的执行 Skill 对{option_reference}形成推荐方案草案；"
                "尚未作出业务承诺，待责任角色按各维度确认。"
            ),
            role_reports=[
                RoleReport(
                    role=contract["role"],
                    dimension=contract["dimension"],
                    report=(
                        f"{contract['role']}维度：推荐方案已按{contract['dimension']}对照"
                        f"{option_reference}形成判断，但模拟查询结果仍须由"
                        f"{contract['role']}核验后才能形成业务承诺。"
                    ),
                )
                for contract in prompt["required_role_reports"]
            ],
        )
        return AIMessage(
            content="",
            tool_calls=[{
                "name": "PathAgentResult",
                "args": result.model_dump(mode="json"),
                "id": "deterministic-path-result",
                "type": "tool_call",
            }],
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
                "title": case.title,
                "description": case.description,
                "business_payload": dict(case.business_payload),
            },
            human_proposal=case.human_proposal.model_dump(mode="json") if case.human_proposal else None,
            path=path.model_dump(mode="json") | {"title": path_title},
            execution_skills=execution_skills,
            knowledge=knowledge,
            authorized_options=authorized_options,
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
        result.recommendation,
        *(value for report in result.role_reports for value in (report.role, report.dimension, report.report)),
    ]
    if any(not contains_chinese(value) for value in values):
        raise AgentOutputError("Path Agent 的全部面向人字段必须使用中文")


def _validate_result_against_context(result: PathAgentResult, context: PathAgentContext) -> None:
    returned = {(item.role, item.dimension): item for item in result.role_reports}
    required = {(item["role"], item["dimension"]): item for item in context.required_role_reports}
    if set(returned) != set(required):
        raise AgentOutputError(
            "Path Agent must return every Skill-required role report exactly once; "
            f"missing={sorted(set(required) - set(returned))}, "
            f"unknown={sorted(set(returned) - set(required))}"
        )


def path_agent_from_environment() -> PathAgentAdapter:
    adapter = agent_adapter_from_environment()
    if adapter == "deterministic":
        return DeepAgentPathAdapter(
            _DeterministicPathChatModel(
                delay_seconds=deterministic_delay_seconds_from_environment()
            ),
            profile="deterministic-path/v1",
        )
    if adapter == "openai-compatible":
        llm = agent_llm_config_from_environment("path")
        api_key = os.getenv("AGENTIC_CM_LLM_API_KEY")
        api_key_header = os.getenv("AGENTIC_CM_LLM_API_KEY_HEADER", "Authorization")
        api_key_prefix = os.getenv("AGENTIC_CM_LLM_API_KEY_PREFIX", "Bearer")
        default_headers = None
        if api_key and api_key_header.lower() != "authorization":
            default_headers = {
                api_key_header: f"{api_key_prefix} {api_key}".strip()
            }
        max_output_tokens = int(os.getenv("AGENTIC_CM_PATH_MAX_OUTPUT_TOKENS", "6000"))
        if max_output_tokens < 1000:
            raise AgentError("Path Agent max output tokens must be at least 1000")
        model = ChatOpenAI(
            model=llm.model,
            base_url=os.getenv("AGENTIC_CM_LLM_BASE_URL", ""),
            api_key=api_key or "not-configured",
            timeout=llm_timeout_seconds_from_environment(),
            max_tokens=max_output_tokens,
            default_headers=default_headers,
            extra_body={
                "thinking": {
                    "type": "enabled" if llm.thinking_enabled else "disabled"
                }
            },
            reasoning_effort=llm.reasoning_effort if llm.thinking_enabled else None,
        )
        return DeepAgentPathAdapter(
            model,
            profile=f"openai-compatible-path/{llm.model}",
        )
    raise AgentError(f"Unknown Path Agent adapter: {adapter}")
