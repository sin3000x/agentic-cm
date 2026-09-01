from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable, Protocol
from uuid import UUID

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import StateBackend
from deepagents.backends.utils import create_file_data
from deepagents.graph import DeepAgentState
from deepagents.profiles import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    register_harness_profile,
)
from langchain.agents.structured_output import ToolStrategy
from langchain.tools import ToolRuntime
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    BaseCallbackHandler,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult, LLMResult
from langchain_core.tools import BaseTool, StructuredTool, ToolException
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError
from pydantic import ValidationError, create_model

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
    "Read and follow the authorized Skills under /skills, and read only the projected Case, "
    "Knowledge, and evidence files. Call the registered read-only Function Tools when a Skill "
    "requires current frozen records. Treat Knowledge as advisory, never as current Case fact. "
    "Write one Chinese recommendation for this Path. Do not make business commitments, claim "
    "actions were executed, remove Policy duties, or invent confirmed quantities, dates, "
    "certifications, or approvals. Return role_reports for exactly the contracts in "
    "/evidence/required-role-reports.json, with no missing or extra role/dimension pair; each "
    "report explains why this recommendation should be approved from that role's dimension and "
    "what that role still needs to confirm."
)

_PATH_AGENT_USER_TASK = (
    "分析当前已批准 Path。先读取 Manifest 授权的 Skill 和只读上下文文件，"
    "按需调用可用 Function Tools，最后返回 PathAgentResult。"
)

_PATH_FILESYSTEM_PERMISSIONS = [
    FilesystemPermission(
        operations=["read"],
        paths=["/skills/**", "/case/**", "/knowledge/**", "/evidence/**"],
        mode="allow",
    ),
    FilesystemPermission(operations=["read"], paths=["/**"], mode="deny"),
    FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
]

_PATH_HARNESS_PROFILE = HarnessProfile(
    excluded_tools=frozenset({"write_file", "edit_file", "delete", "execute"}),
    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
)
register_harness_profile("agentic-cm", _PATH_HARNESS_PROFILE)

_PATH_RECURSION_LIMIT = 20
_FILESYSTEM_TOOLS = frozenset({"ls", "read_file", "glob", "grep"})
_STRUCTURED_OUTPUT_TOOLS = frozenset({"PathAgentResult"})


class _PathChatOpenAI(ChatOpenAI):
    def _get_ls_params(self, **kwargs: Any) -> dict[str, Any]:
        params = super()._get_ls_params(**kwargs)
        params["ls_provider"] = "agentic-cm"
        return params


@dataclass(frozen=True, slots=True)
class PathAgentContext:
    case_snapshot: dict[str, Any]
    human_proposal: dict[str, Any] | None
    path: dict[str, Any]
    execution_skills: tuple[dict[str, Any], ...]
    knowledge: tuple[dict[str, Any], ...]
    authorized_options: tuple[dict[str, Any], ...]
    tool_contracts: tuple[dict[str, Any], ...]
    required_role_reports: tuple[dict[str, str], ...]
    previous_solution_revision: SolutionRevision | None


class PathAgentAdapter(Protocol):
    async def generate(self, context: PathAgentContext, trace: AgentTraceSink) -> PathAgentResult: ...


class _PathAgentState(DeepAgentState):
    path_tool_records: dict[str, dict[str, Any]]
    authorized_option_ids: list[str]


@dataclass(frozen=True)
class _PathRuntimeContext:
    trace: AgentTraceSink


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


def _context_files(context: PathAgentContext) -> dict[str, str]:
    files = _skill_files(context)
    for selection in context.path.get("skill_selections", []):
        entrypoint = selection.get("entrypoint", {})
        entrypoint_id = entrypoint.get("id")
        if not isinstance(entrypoint_id, str) or not entrypoint_id:
            continue
        member_ids = [
            member["id"]
            for member in selection.get("members", [])
            if isinstance(member, dict)
            and isinstance(member.get("id"), str)
            and member["id"]
        ]
        files[f"/skills/{entrypoint_id}/bundle.json"] = json.dumps(
            {"entrypoint": entrypoint_id, "members": member_ids},
            ensure_ascii=False,
            indent=2,
        )

    def add_json(path: str, value: Any) -> None:
        files[path] = json.dumps(value, ensure_ascii=False, indent=2)

    add_json(
        "/case/snapshot.json",
        {
            key: context.case_snapshot[key]
            for key in ("description", "business_payload")
            if key in context.case_snapshot
        },
    )
    add_json(
        "/case/path.json",
        {
            key: context.path[key]
            for key in ("id", "definition", "title", "rationale")
            if key in context.path
        },
    )
    if context.human_proposal is not None:
        add_json(
            "/case/human-proposal.json",
            {
                key: context.human_proposal[key]
                for key in ("author", "role", "content")
                if key in context.human_proposal
            },
        )
    if context.previous_solution_revision is not None:
        add_json(
            "/case/previous-solution-revision.json",
            context.previous_solution_revision.model_dump(
                mode="json", include={"recommendation", "role_reports"}
            ),
        )
    add_json(
        "/knowledge/context.json",
        [
            {
                key: item[key]
                for key in ("title", "knowledge_type", "source", "confidence", "content")
                if key in item
            }
            for item in context.knowledge
        ],
    )
    add_json("/evidence/authorized-options.json", list(context.authorized_options))
    add_json("/evidence/required-role-reports.json", list(context.required_role_reports))
    return files


def _function_tools(context: PathAgentContext) -> tuple[BaseTool, ...]:
    def build_tool(contract: dict[str, Any]) -> BaseTool:
        tool_id = str(contract["id"])
        input_key = str(contract["input_key"])
        args_schema = create_model(
            f"{''.join(part.title() for part in tool_id.split('_'))}Input",
            **{input_key: (str, ...)},
        )

        def query(
            runtime: ToolRuntime[_PathRuntimeContext, _PathAgentState],
            **arguments: str,
        ) -> dict[str, Any]:
            option_id = arguments[input_key]
            authorized_ids = set(runtime.state["authorized_option_ids"])
            records = runtime.state["path_tool_records"][tool_id]
            if option_id not in authorized_ids:
                raise ToolException(
                    f"Tool {tool_id} cannot query unauthorized option {option_id!r}"
                )
            if option_id not in records:
                raise ToolException(
                    f"Tool {tool_id} has no frozen record for option {option_id!r}"
                )
            return records[option_id]

        return StructuredTool.from_function(
            func=query,
            name=tool_id,
            description=str(contract["description"]),
            args_schema=args_schema,
        )

    return tuple(build_tool(contract) for contract in context.tool_contracts)


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


def _tool_name(serialized: dict[str, Any] | None, kwargs: dict[str, Any]) -> str:
    name = kwargs.get("name") or (serialized or {}).get("name")
    return str(name or "")


def _json_content(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _tool_output_content(output: Any) -> Any:
    if isinstance(output, ToolMessage):
        return _json_content(output.content)
    if hasattr(output, "content"):
        return _json_content(output.content)
    return _json_content(output)


def _summarize_tool_input(name: str, inputs: dict[str, Any] | None, input_str: str) -> dict[str, Any]:
    payload = dict(inputs) if isinstance(inputs, dict) else {}
    if not payload and input_str:
        payload = {"input": input_str}
    if name in _FILESYSTEM_TOOLS:
        allowed = ("file_path", "path", "pattern", "offset", "limit")
        return {key: payload[key] for key in allowed if key in payload}
    return payload


def _summarize_tool_output(name: str, output: Any) -> Any:
    content = _tool_output_content(output)
    if name in _FILESYSTEM_TOOLS:
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        return {"chars": len(text), "lines": text.count("\n") + (1 if text else 0)}
    return content


def _tool_call_summaries(message: BaseMessage | None) -> list[dict[str, Any]]:
    if not isinstance(message, AIMessage):
        return []
    summaries: list[dict[str, Any]] = []
    for call in message.tool_calls or []:
        name = str(call.get("name") or "")
        item: dict[str, Any] = {"name": name}
        if name not in _STRUCTURED_OUTPUT_TOOLS:
            args = call.get("args")
            if isinstance(args, dict):
                item["input"] = _summarize_tool_input(name, args, "")
        summaries.append(item)
    return summaries


def _usage_from_llm_result(response: LLMResult) -> dict[str, int]:
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    llm_output = response.llm_output or {}
    raw = llm_output.get("token_usage") or llm_output.get("usage") or {}
    if isinstance(raw, dict):
        usage["prompt_tokens"] = int(raw.get("prompt_tokens") or raw.get("input_tokens") or 0)
        usage["completion_tokens"] = int(
            raw.get("completion_tokens") or raw.get("output_tokens") or 0
        )
        usage["total_tokens"] = int(raw.get("total_tokens") or 0)
    generations = response.generations[0] if response.generations else []
    message = generations[0].message if generations else None
    metadata = getattr(message, "usage_metadata", None) or {}
    if isinstance(metadata, dict) and metadata:
        usage["prompt_tokens"] = int(metadata.get("input_tokens") or usage["prompt_tokens"])
        usage["completion_tokens"] = int(
            metadata.get("output_tokens") or usage["completion_tokens"]
        )
        usage["total_tokens"] = int(metadata.get("total_tokens") or usage["total_tokens"])
    if usage["total_tokens"] == 0:
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    return usage


def _result_trace_details(
    result: PathAgentResult, callback: "_DeepAgentTraceCallback"
) -> dict[str, Any]:
    return {
        "turns": callback.turns,
        "token_usage": {
            "prompt_tokens": callback.prompt_tokens,
            "completion_tokens": callback.completion_tokens,
            "total_tokens": callback.total_tokens,
        },
        "result": {
            "recommendation_chars": len(result.recommendation),
            "role_report_count": len(result.role_reports),
            "roles": [item.role for item in result.role_reports],
        },
    }


class _DeepAgentTraceCallback(BaseCallbackHandler):
    """Bridge LangGraph/Deep Agents callbacks into the product AgentRun trace.

    Official Deep Agents tracing ships to LangSmith. This handler keeps the same
    internal events in `agent_trace_events` without that dependency, and never
    records hidden reasoning or full virtual-file bodies.
    """

    raise_error = True

    def __init__(self, trace: AgentTraceSink) -> None:
        super().__init__()
        self._trace = trace
        self._lock = Lock()
        self._pending_tools: dict[str, dict[str, Any]] = {}
        self.turns = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        with self._lock:
            self.turns += 1
            turn = self.turns
        self._trace(
            "deepagent.turn.started",
            "STARTED",
            "Deep Agents 模型轮次开始",
            {"turn": turn},
        )

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        usage = _usage_from_llm_result(response)
        generations = response.generations[0] if response.generations else []
        message = generations[0].message if generations else None
        with self._lock:
            self.prompt_tokens += usage["prompt_tokens"]
            self.completion_tokens += usage["completion_tokens"]
            self.total_tokens += usage["total_tokens"]
            turn = self.turns
        self._trace(
            "deepagent.turn.completed",
            "COMPLETED",
            "Deep Agents 模型轮次完成",
            {
                "turn": turn,
                "token_usage": usage,
                "tool_calls": _tool_call_summaries(message),
            },
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        with self._lock:
            turn = self.turns
        self._trace(
            "deepagent.turn.failed",
            "FAILED",
            "Deep Agents 模型轮次失败",
            {"turn": turn, **_exception_trace_details(error)},
        )

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        name = _tool_name(serialized, kwargs)
        if name in _STRUCTURED_OUTPUT_TOOLS:
            return
        tool_input = _summarize_tool_input(name, inputs, input_str)
        with self._lock:
            self._pending_tools[str(run_id)] = {"name": name, "input": tool_input}
        self._trace(
            "deepagent.tool.started",
            "STARTED",
            "Deep Agents 调用只读工具",
            {"tool": name, "input": tool_input},
        )

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        with self._lock:
            pending = self._pending_tools.pop(str(run_id), {})
        name = str(pending.get("name") or _tool_name(None, kwargs))
        if name in _STRUCTURED_OUTPUT_TOOLS:
            return
        details: dict[str, Any] = {
            "tool": name,
            "output": _summarize_tool_output(name, output),
        }
        if "input" in pending:
            details["input"] = pending["input"]
        self._trace(
            "deepagent.tool.completed",
            "COMPLETED",
            "Deep Agents 只读工具返回",
            details,
        )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        with self._lock:
            pending = self._pending_tools.pop(str(run_id), {})
        name = str(pending.get("name") or _tool_name(None, kwargs))
        if name in _STRUCTURED_OUTPUT_TOOLS:
            return
        details = {"tool": name, **_exception_trace_details(error)}
        if "input" in pending:
            details["input"] = pending["input"]
        self._trace(
            "deepagent.tool.failed",
            "FAILED",
            "Deep Agents 只读工具失败",
            details,
        )


class DeepAgentPathAdapter:
    def __init__(
        self,
        model: BaseChatModel,
        *,
        profile: str,
        graph_factory: Callable[..., Any] = create_deep_agent,
    ) -> None:
        self._model = model
        self.profile = profile
        self._graph_factory = graph_factory
        self._graphs: dict[tuple[tuple[str, str, str], ...], Any] = {}

    def _graph_for(self, context: PathAgentContext) -> Any:
        key = tuple(
            sorted(
                (
                    str(contract["id"]),
                    str(contract["description"]),
                    str(contract["input_key"]),
                )
                for contract in context.tool_contracts
            )
        )
        graph = self._graphs.get(key)
        if graph is None:
            graph = self._graph_factory(
                model=self._model,
                tools=list(_function_tools(context)),
                system_prompt=_PATH_AGENT_SYSTEM_PROMPT,
                skills=[("/skills/", "Manifest")],
                permissions=_PATH_FILESYSTEM_PERMISSIONS,
                backend=StateBackend(),
                subagents=[],
                response_format=ToolStrategy(PathAgentResult),
                state_schema=_PathAgentState,
                context_schema=_PathRuntimeContext,
            )
            self._graphs[key] = graph
        return graph

    async def generate(
        self, context: PathAgentContext, trace: AgentTraceSink
    ) -> PathAgentResult:
        context_files = _context_files(context)
        callback = _DeepAgentTraceCallback(trace)
        trace(
            "deepagent.runtime.started",
            "STARTED",
            "启动 Deep Agents Path Runtime",
            {
                "profile": self.profile,
                "path": context.path.get("definition"),
                "skills": [str(skill["id"]) for skill in context.execution_skills],
                "recursion_limit": _PATH_RECURSION_LIMIT,
            },
        )
        trace(
            "deepagent.skill.projected",
            "COMPLETED",
            "投影 Manifest 授权的执行 Skill",
            {"skills": list(_skill_files(context))},
        )
        try:
            agent = self._graph_for(context)
            state = await agent.ainvoke(
                {
                    "messages": [{
                        "role": "user",
                        "content": _PATH_AGENT_USER_TASK,
                    }],
                    "files": {
                        path: create_file_data(content)
                        for path, content in context_files.items()
                    },
                    "path_tool_records": {
                        str(contract["id"]): contract["records"]
                        for contract in context.tool_contracts
                    },
                    "authorized_option_ids": [
                        str(option["id"])
                        for option in context.authorized_options
                    ],
                },
                config={
                    "recursion_limit": _PATH_RECURSION_LIMIT,
                    "callbacks": [callback],
                },
                context=_PathRuntimeContext(trace=trace),
            )
        except GraphRecursionError as exc:
            trace(
                "deepagent.runtime.failed",
                "FAILED",
                "Deep Agents Path Runtime 未能收敛",
                {**_exception_trace_details(exc), "turns": callback.turns},
            )
            raise AgentOutputError("Path Agent did not produce structured output") from exc
        except Exception as exc:
            details = {**_exception_trace_details(exc), "turns": callback.turns}
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
        except ValidationError as exc:
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
            _result_trace_details(result, callback),
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
        tool_messages = {
            message.tool_call_id: message
            for message in messages
            if isinstance(message, ToolMessage)
        }
        if not {"deterministic-options", "deterministic-reports"} <= set(tool_messages):
            return AIMessage(
                content="",
                tool_calls=[{
                    "name": "read_file",
                    "args": {"file_path": "/evidence/authorized-options.json"},
                    "id": "deterministic-options",
                    "type": "tool_call",
                }, {
                    "name": "read_file",
                    "args": {"file_path": "/evidence/required-role-reports.json"},
                    "id": "deterministic-reports",
                    "type": "tool_call",
                }],
            )

        def read_json(tool_call_id: str) -> Any:
            numbered_content = str(tool_messages[tool_call_id].content)
            content = "\n".join(
                re.sub(r"^\s*\d+\s{2}", "", line)
                for line in numbered_content.splitlines()
            )
            return json.loads(content)

        authorized_options = read_json("deterministic-options")
        required_role_reports = read_json("deterministic-reports")
        option_ids = [str(item["id"]) for item in authorized_options]
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
                        f"{option_reference}形成判断，但冻结查询记录仍须由"
                        f"{contract['role']}核验后才能形成业务承诺。"
                    ),
                )
                for contract in required_role_reports
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
        for tool_id, (tool, _skill) in sorted(tools_by_id.items()):
            for option in authorized_options:
                option_id = option["id"]
                if option_id not in tool["records"]:
                    raise AgentError(f"Frozen tool {tool_id} has no record for option {option_id}")
        tool_contracts = tuple(
            tool for tool, _skill in (tools_by_id[tool_id] for tool_id in sorted(tools_by_id))
        )
        if tool_contracts:
            trace(
                "tools.register",
                "COMPLETED",
                "注册 Manifest 授权的只读 Function Tools",
                {"tool_ids": [tool["id"] for tool in tool_contracts]},
            )
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
            tool_contracts=tool_contracts,
            required_role_reports=required_role_reports,
            previous_solution_revision=previous,
        )
        trace(
            "agent.input",
            "COMPLETED",
            "构造冻结、最小授权的 Path Agent 上下文",
            {
                "files": sorted(_context_files(context)),
                "tool_ids": [tool["id"] for tool in tool_contracts],
            },
        )
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
        model = _PathChatOpenAI(
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
