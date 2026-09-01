import asyncio
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from time import perf_counter

import httpx
import pytest
from deepagents import create_deep_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agentic_cm.agent_runtime import AgentError, AgentExecutionError, AgentOutputError
from agentic_cm.domain import PathAgentResult, RoleReport, SolutionRevision
from agentic_cm.orchestrator import (
    DeterministicPlannerAdapter,
    planner_from_environment,
    OpenAICompatiblePlannerAdapter,
    PlannerOutput,
    PlannerPath,
    PlannerSkillChoice,
)
from agentic_cm.path_agent import (
    DeepAgentPathAdapter,
    PathAgentContext,
    _context_files,
    _skill_files,
    path_agent_from_environment,
)
from agentic_cm.repository import CaseRepository
from agentic_cm.service import CaseService
from agentic_cm.synthesis_agent import (
    OpenAICompatibleSynthesisAgentAdapter,
    synthesis_agent_from_environment,
)
from conftest import (
    AllMatchedSkillPathsPlanner,
    DEMO_CASE_ID,
    OWNER_ACTOR,
    OWNER_ROLE,
    chat_completion_response,
    deterministic_path_adapter,
    make_service,
    orchestrate,
)


class _InventingPlanner:
    async def propose(self, context, candidates, skill_catalog, trace):
        return PlannerOutput(
            paths=(PlannerPath(
                definition="InventedByModel",
                rationale="不受支持",
                skills=[PlannerSkillChoice(id="invented-skill", reason="发明了未知技能。")],
            ),),
            planner_profile="test/inventing",
        )


class _OmittingPlanner:
    async def propose(self, context, candidates, skill_catalog, trace):
        candidate = candidates[0]
        return PlannerOutput(
            paths=(PlannerPath(
                definition=candidate["definition"],
                rationale="只返回一条",
                skills=[PlannerSkillChoice(id="material-substitution-analysis", reason="需要完整评估替代方案。")],
            ),),
            planner_profile="test/omitting",
        )


class _OmittingRoleReportsPathAgent:
    profile = "test/omitting-role-reports"

    async def generate(self, context, trace):
        return PathAgentResult(
            recommendation="省略了责任角色报告。",
            role_reports=[],
        )


class _CapturingFunctionToolPathAgent:
    profile = "test/capturing-function-tools"

    def __init__(self) -> None:
        self.context: PathAgentContext | None = None

    async def generate(self, context, trace):
        self.context = context
        return PathAgentResult(
            recommendation="建议依据冻结证据评审授权候选，尚未形成业务承诺。",
            role_reports=[
                RoleReport(
                    role=item["role"],
                    dimension=item["dimension"],
                    report=f"{item['role']}需核验{item['dimension']}证据后确认。",
                )
                for item in context.required_role_reports
            ],
        )


def test_deep_agent_projects_only_authorized_skills() -> None:
    context = PathAgentContext(
        case_snapshot={"description": "关键物料存在缺口。"},
        human_proposal=None,
        path={"definition": "MaterialSubstitution", "title": "物料替代"},
        execution_skills=(
            {
                "id": "material-analysis",
                "description": "分析替代物料。",
                "instructions_markdown": "只分析 Manifest 授权的候选。",
            },
            {
                "id": "supply-review",
                "description": "复核供应证据。",
                "instructions_markdown": "标记需要主计划确认的信息。",
            },
        ),
        knowledge=(),
        authorized_options=({"id": "A", "title": "候选方案甲"},),
        tool_contracts=(),
        required_role_reports=(),
        previous_solution_revision=None,
    )

    assert _skill_files(context) == {
        "/skills/material-analysis/SKILL.md": (
            "---\n"
            "name: material-analysis\n"
            "description: 分析替代物料。\n"
            "---\n\n"
            "只分析 Manifest 授权的候选。\n"
        ),
        "/skills/supply-review/SKILL.md": (
            "---\n"
            "name: supply-review\n"
            "description: 复核供应证据。\n"
            "---\n\n"
            "标记需要主计划确认的信息。\n"
        ),
    }


def test_deep_agent_projects_complete_read_only_context_files() -> None:
    context = PathAgentContext(
        case_snapshot={
            "description": "关键物料存在缺口。",
            "business_payload": {"gap_quantity": 18400},
        },
        human_proposal={
            "author": "陈澄",
            "role": "订单统筹经理",
            "content": "优先评估认证范围内的替代料。",
        },
        path={
            "id": "PATH-01",
            "definition": "MaterialSubstitution",
            "skill_selections": [{
                "entrypoint": {"id": "material-substitution-analysis"},
                "members": [
                    {"id": "material-substitution-engineering-review"},
                    {"id": "material-substitution-master-planning-review"},
                ],
            }],
        },
        execution_skills=({
            "id": "material-substitution-analysis",
            "description": "分析物料替代。",
            "instructions_markdown": "读取冻结 Bundle 和证据。",
        },),
        knowledge=({"title": "历史案例", "content": {"summary": "认证可能返工"}},),
        authorized_options=({"id": "A", "material_id": "MCU-X7A"},),
        tool_contracts=(),
        required_role_reports=({"role": "研发", "dimension": "技术可行性"},),
        previous_solution_revision=SolutionRevision(
            recommendation="上一版建议。",
            role_reports=[],
            revision=1,
            generated_by="test/path",
        ),
    )

    files = _context_files(context)

    assert set(files) == {
        "/skills/material-substitution-analysis/SKILL.md",
        "/skills/material-substitution-analysis/bundle.json",
        "/case/snapshot.json",
        "/case/path.json",
        "/case/human-proposal.json",
        "/case/previous-solution-revision.json",
        "/knowledge/context.json",
        "/evidence/authorized-options.json",
        "/evidence/required-role-reports.json",
    }
    assert json.loads(files["/skills/material-substitution-analysis/bundle.json"])["members"] == [
        "material-substitution-engineering-review",
        "material-substitution-master-planning-review",
    ]
    assert json.loads(files["/case/snapshot.json"])["business_payload"]["gap_quantity"] == 18400
    assert json.loads(files["/knowledge/context.json"])[0]["title"] == "历史案例"
    assert json.loads(files["/evidence/authorized-options.json"])[0]["id"] == "A"


def test_deep_agent_returns_existing_path_result_contract() -> None:
    payload = {
        "recommendation": "建议按授权候选推进物料替代，待责任角色确认供应与技术证据。",
        "role_reports": [],
    }

    class ScriptedModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, *, tool_choice=None, **kwargs):
            return self

        def _get_ls_params(self, **kwargs):
            return {
                "ls_provider": "agentic-cm",
                "ls_model_name": "path-scripted",
            }

    context = PathAgentContext(
        case_snapshot={"description": "关键物料存在缺口。"},
        human_proposal=None,
        path={"definition": "MaterialSubstitution", "title": "物料替代"},
        execution_skills=({
            "id": "material-analysis",
            "description": "分析替代物料。",
            "instructions_markdown": "只分析 Manifest 授权的候选。",
        },),
        knowledge=(),
        authorized_options=({"id": "A", "title": "候选方案甲"},),
        tool_contracts=(),
        required_role_reports=(),
        previous_solution_revision=None,
    )
    model = ScriptedModel(responses=[AIMessage(
        content="",
        tool_calls=[{
            "name": "PathAgentResult",
            "args": payload,
            "id": "result-1",
            "type": "tool_call",
        }],
    )])

    result = asyncio.run(
        DeepAgentPathAdapter(model, profile="test/path").generate(
            context, lambda *args, **kwargs: None
        )
    )

    assert result == PathAgentResult.model_validate(payload)


def test_deep_agent_invokes_manifest_function_tool() -> None:
    class ToolCallingModel(BaseChatModel):
        calls: int = 0
        observed_tool_result: str = ""
        observed_user_message: str = ""
        observed_system_message: str = ""

        @property
        def _llm_type(self) -> str:
            return "test-tool-calling-model"

        def _get_ls_params(self, **kwargs):
            return {"ls_provider": "agentic-cm", "ls_model_name": "tool-calling"}

        def bind_tools(self, tools, *, tool_choice=None, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if self.calls == 0:
                self.observed_user_message = str(next(
                    item.content for item in messages if isinstance(item, HumanMessage)
                ))
                self.observed_system_message = str(next(
                    item.content for item in messages if isinstance(item, SystemMessage)
                ))
                message = AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "lookup_material_master",
                        "args": {"option_id": "A"},
                        "id": "lookup-1",
                        "type": "tool_call",
                    }],
                )
            else:
                tool_message = next(
                    item for item in reversed(messages) if isinstance(item, ToolMessage)
                )
                self.observed_tool_result = str(tool_message.content)
                message = AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "PathAgentResult",
                        "args": {
                            "recommendation": "建议优先评审封装为 QFN-48 的候选 A。",
                            "role_reports": [],
                        },
                        "id": "result-1",
                        "type": "tool_call",
                    }],
                )
            self.calls += 1
            return ChatResult(generations=[ChatGeneration(message=message)])

    context = PathAgentContext(
        case_snapshot={"description": "关键物料存在缺口。"},
        human_proposal=None,
        path={"definition": "MaterialSubstitution", "skill_selections": []},
        execution_skills=(),
        knowledge=(),
        authorized_options=({"id": "A"},),
        tool_contracts=({
            "id": "lookup_material_master",
            "description": "查询冻结的物料主数据。",
            "read_only": True,
            "input_key": "option_id",
            "records": {
                "A": {"package": "QFN-48"},
                "B": {"package": "BGA-64"},
            },
        },),
        required_role_reports=(),
        previous_solution_revision=None,
    )
    model = ToolCallingModel()

    result = asyncio.run(
        DeepAgentPathAdapter(model, profile="test/function-tools").generate(
            context, lambda *args: None
        )
    )

    assert result.recommendation == "建议优先评审封装为 QFN-48 的候选 A。"
    assert '"package":"QFN-48"' in model.observed_tool_result.replace(" ", "")
    assert model.observed_user_message == (
        "分析当前已批准 Path。先读取 Manifest 授权的 Skill 和只读上下文文件，"
        "按需调用可用 Function Tools，最后返回 PathAgentResult。"
    )
    assert "**Manifest Skills**" in model.observed_system_message
    assert "**Skills Skills**" not in model.observed_system_message


def test_deep_agent_trace_records_internal_turns_and_tools() -> None:
    skill_body = "只分析 Manifest 授权的候选，并调用冻结查询。"

    class InternalTraceModel(BaseChatModel):
        calls: int = 0

        @property
        def _llm_type(self) -> str:
            return "test-internal-trace-model"

        def _get_ls_params(self, **kwargs):
            return {"ls_provider": "agentic-cm", "ls_model_name": "internal-trace"}

        def bind_tools(self, tools, *, tool_choice=None, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if self.calls == 0:
                message = AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "read_file",
                        "args": {"file_path": "/skills/material-analysis/SKILL.md"},
                        "id": "read-skill",
                        "type": "tool_call",
                    }, {
                        "name": "lookup_material_master",
                        "args": {"option_id": "A"},
                        "id": "lookup-1",
                        "type": "tool_call",
                    }],
                )
            else:
                message = AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "PathAgentResult",
                        "args": {
                            "recommendation": "建议依据冻结物料主数据评审候选 A，尚未形成业务承诺。",
                            "role_reports": [],
                        },
                        "id": "result-1",
                        "type": "tool_call",
                    }],
                )
            self.calls += 1
            return ChatResult(generations=[ChatGeneration(message=message)])

    context = PathAgentContext(
        case_snapshot={"description": "关键物料存在缺口。"},
        human_proposal=None,
        path={"definition": "MaterialSubstitution"},
        execution_skills=({
            "id": "material-analysis",
            "description": "分析替代物料。",
            "instructions_markdown": skill_body,
        },),
        knowledge=(),
        authorized_options=({"id": "A"},),
        tool_contracts=({
            "id": "lookup_material_master",
            "description": "查询冻结的物料主数据。",
            "read_only": True,
            "input_key": "option_id",
            "records": {"A": {"package": "QFN-48"}},
        },),
        required_role_reports=(),
        previous_solution_revision=None,
    )
    traces: list[tuple] = []

    result = asyncio.run(
        DeepAgentPathAdapter(InternalTraceModel(), profile="test/internal-trace").generate(
            context, lambda *args: traces.append(args)
        )
    )

    steps = [item[0] for item in traces]
    started = traces[0][3]
    assert traces[0][0:2] == ("deepagent.runtime.started", "STARTED")
    assert started["skills"] == ["material-analysis"]
    assert started["recursion_limit"] == 20
    assert "deepagent.turn.started" in steps
    assert "deepagent.tool.started" in steps

    read_events = [
        item[3] for item in traces
        if item[0] == "deepagent.tool.completed" and item[3].get("tool") == "read_file"
    ]
    assert read_events[0]["input"]["file_path"] == "/skills/material-analysis/SKILL.md"
    assert read_events[0]["output"]["chars"] > 0
    assert skill_body not in json.dumps(traces, ensure_ascii=False)

    lookup_events = [
        item[3] for item in traces
        if item[0] == "deepagent.tool.completed" and item[3].get("tool") == "lookup_material_master"
    ]
    assert lookup_events == [{
        "tool": "lookup_material_master",
        "input": {"option_id": "A"},
        "output": {"package": "QFN-48"},
    }]

    final = traces[-1]
    assert final[0:2] == ("deepagent.model.completed", "COMPLETED")
    assert final[3]["turns"] == 2
    assert set(final[3]["token_usage"]) == {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }
    assert final[3]["result"]["role_report_count"] == 0
    assert "recommendation" not in final[3]["result"]
    assert result.recommendation not in json.dumps(final[3], ensure_ascii=False)


def test_manifest_function_tool_rejects_unauthorized_option() -> None:
    class UnauthorizedToolModel(BaseChatModel):
        calls: int = 0
        tool_error: str = ""

        @property
        def _llm_type(self) -> str:
            return "test-unauthorized-tool-model"

        def _get_ls_params(self, **kwargs):
            return {"ls_provider": "agentic-cm", "ls_model_name": "unauthorized-tool"}

        def bind_tools(self, tools, *, tool_choice=None, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if self.calls == 0:
                message = AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "lookup_material_master",
                        "args": {"option_id": "B"},
                        "id": "lookup-unauthorized",
                        "type": "tool_call",
                    }],
                )
            else:
                self.tool_error = str(next(
                    item.content for item in reversed(messages) if isinstance(item, ToolMessage)
                ))
                message = AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "PathAgentResult",
                        "args": {"recommendation": "未使用未授权候选。", "role_reports": []},
                        "id": "result-1",
                        "type": "tool_call",
                    }],
                )
            self.calls += 1
            return ChatResult(generations=[ChatGeneration(message=message)])

    context = PathAgentContext(
        case_snapshot={},
        human_proposal=None,
        path={"definition": "MaterialSubstitution"},
        execution_skills=(),
        knowledge=(),
        authorized_options=({"id": "A"},),
        tool_contracts=({
            "id": "lookup_material_master",
            "description": "查询冻结的物料主数据。",
            "read_only": True,
            "input_key": "option_id",
            "records": {
                "A": {"package": "QFN-48"},
                "B": {"package": "BGA-64"},
            },
        },),
        required_role_reports=(),
        previous_solution_revision=None,
    )
    model = UnauthorizedToolModel()
    traces: list[tuple] = []

    with pytest.raises(AgentExecutionError, match="unauthorized option 'B'"):
        asyncio.run(
            DeepAgentPathAdapter(model, profile="test/unauthorized-tool").generate(
                context, lambda *args: traces.append(args)
            )
        )

    failed_tools = [
        item[3] for item in traces
        if item[0] == "deepagent.tool.failed" and item[3].get("tool") == "lookup_material_master"
    ]
    assert failed_tools[0]["input"] == {"option_id": "B"}
    assert "unauthorized option 'B'" in failed_tools[0]["error"]


def test_deep_agent_denies_reads_outside_manifest_context() -> None:
    class OutsideReadModel(BaseChatModel):
        calls: int = 0
        read_result: str = ""

        @property
        def _llm_type(self) -> str:
            return "test-outside-read-model"

        def _get_ls_params(self, **kwargs):
            return {"ls_provider": "agentic-cm", "ls_model_name": "outside-read"}

        def bind_tools(self, tools, *, tool_choice=None, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if self.calls == 0:
                message = AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "read_file",
                        "args": {"file_path": "/outside.txt"},
                        "id": "read-1",
                        "type": "tool_call",
                    }],
                )
            else:
                self.read_result = str(next(
                    item.content for item in reversed(messages) if isinstance(item, ToolMessage)
                ))
                message = AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "PathAgentResult",
                        "args": {"recommendation": "未读取授权范围外文件。", "role_reports": []},
                        "id": "result-1",
                        "type": "tool_call",
                    }],
                )
            self.calls += 1
            return ChatResult(generations=[ChatGeneration(message=message)])

    context = PathAgentContext(
        case_snapshot={},
        human_proposal=None,
        path={"definition": "OrderSplit"},
        execution_skills=(),
        knowledge=(),
        authorized_options=(),
        tool_contracts=(),
        required_role_reports=(),
        previous_solution_revision=None,
    )
    model = OutsideReadModel()

    asyncio.run(
        DeepAgentPathAdapter(model, profile="test/permissions").generate(
            context, lambda *args: None
        )
    )

    assert "permission denied for read on /outside.txt" in model.read_result


def test_deep_agent_reuses_graph_without_reusing_frozen_tool_records() -> None:
    class ReusableToolModel(BaseChatModel):
        observed_results: list[str] = []

        @property
        def _llm_type(self) -> str:
            return "test-reusable-tool-model"

        def _get_ls_params(self, **kwargs):
            return {"ls_provider": "agentic-cm", "ls_model_name": "reusable-tool"}

        def bind_tools(self, tools, *, tool_choice=None, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            tool_messages = [item for item in messages if isinstance(item, ToolMessage)]
            if not tool_messages:
                message = AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "lookup_material_master",
                        "args": {"option_id": "A"},
                        "id": "lookup-1",
                        "type": "tool_call",
                    }],
                )
            else:
                self.observed_results.append(str(tool_messages[-1].content))
                message = AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "PathAgentResult",
                        "args": {"recommendation": "已读取本次冻结记录。", "role_reports": []},
                        "id": "result-1",
                        "type": "tool_call",
                    }],
                )
            return ChatResult(generations=[ChatGeneration(message=message)])

    def context_with_package(package: str) -> PathAgentContext:
        return PathAgentContext(
            case_snapshot={},
            human_proposal=None,
            path={"definition": "MaterialSubstitution"},
            execution_skills=(),
            knowledge=(),
            authorized_options=({"id": "A"},),
            tool_contracts=({
                "id": "lookup_material_master",
                "description": "查询冻结的物料主数据。",
                "read_only": True,
                "input_key": "option_id",
                "records": {"A": {"package": package}},
            },),
            required_role_reports=(),
            previous_solution_revision=None,
        )

    compile_count = 0

    def counting_graph_factory(**kwargs):
        nonlocal compile_count
        compile_count += 1
        return create_deep_agent(**kwargs)

    model = ReusableToolModel()
    adapter = DeepAgentPathAdapter(
        model,
        profile="test/graph-cache",
        graph_factory=counting_graph_factory,
    )

    asyncio.run(adapter.generate(context_with_package("QFN-48"), lambda *args: None))
    asyncio.run(adapter.generate(context_with_package("LGA-64"), lambda *args: None))

    assert compile_count == 1
    assert '"package":"QFN-48"' in model.observed_results[0].replace(" ", "")
    assert '"package":"LGA-64"' in model.observed_results[1].replace(" ", "")


def test_deep_agent_maps_model_failure_to_execution_error() -> None:
    class FailingModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, *, tool_choice=None, **kwargs):
            return self

        def _get_ls_params(self, **kwargs):
            return {"ls_provider": "agentic-cm", "ls_model_name": "failing"}

        def _generate(self, *args, **kwargs):
            raise RuntimeError("provider unavailable")

    context = PathAgentContext(
        case_snapshot={"description": "关键物料存在缺口。"},
        human_proposal=None,
        path={"definition": "MaterialSubstitution", "title": "物料替代"},
        execution_skills=(),
        knowledge=(),
        authorized_options=({"id": "A", "title": "候选方案甲"},),
        tool_contracts=(),
        required_role_reports=(),
        previous_solution_revision=None,
    )
    traces = []

    with pytest.raises(AgentExecutionError, match="provider unavailable"):
        asyncio.run(
            DeepAgentPathAdapter(
                FailingModel(responses=[AIMessage(content="")]),
                profile="test/failing",
            ).generate(context, lambda *args: traces.append(args))
        )

    details = traces[-1][3]
    assert traces[-1][0:2] == ("deepagent.runtime.failed", "FAILED")
    assert details["error_type"] == "RuntimeError"
    assert "provider unavailable" in details["error"]


def test_deep_agent_rejects_missing_structured_response() -> None:
    class TextOnlyModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, *, tool_choice=None, **kwargs):
            return self

        def _get_ls_params(self, **kwargs):
            return {"ls_provider": "agentic-cm", "ls_model_name": "text-only"}

    context = PathAgentContext(
        case_snapshot={"description": "关键物料存在缺口。"},
        human_proposal=None,
        path={"definition": "MaterialSubstitution", "title": "物料替代"},
        execution_skills=(),
        knowledge=(),
        authorized_options=({"id": "A", "title": "候选方案甲"},),
        tool_contracts=(),
        required_role_reports=(),
        previous_solution_revision=None,
    )

    with pytest.raises(AgentOutputError):
        asyncio.run(
            DeepAgentPathAdapter(
                TextOnlyModel(responses=[AIMessage(content="只有文本，没有结构化结果。")]),
                profile="test/text-only",
            ).generate(context, lambda *args: None)
        )


def test_deep_agent_leaves_semantic_output_validation_to_path_agent() -> None:
    class ScriptedModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, *, tool_choice=None, **kwargs):
            return self

        def _get_ls_params(self, **kwargs):
            return {"ls_provider": "agentic-cm", "ls_model_name": "invalid-report"}

    payload = {
        "recommendation": "建议按授权候选推进物料替代，待责任角色确认供应证据。",
        "role_reports": [],
    }
    context = PathAgentContext(
        case_snapshot={"description": "关键物料存在缺口。"},
        human_proposal=None,
        path={"definition": "MaterialSubstitution", "title": "物料替代"},
        execution_skills=(),
        knowledge=(),
        authorized_options=({"id": "A"}, {"id": "B"}),
        tool_contracts=(),
        required_role_reports=({
            "role": "主计划",
            "dimension": "供应与交付可行性",
        },),
        previous_solution_revision=None,
    )
    model = ScriptedModel(responses=[AIMessage(
        content="",
        tool_calls=[{
            "name": "PathAgentResult",
            "args": payload,
            "id": "invalid-result",
            "type": "tool_call",
        }],
    )])
    traces = []

    result = asyncio.run(
        DeepAgentPathAdapter(model, profile="test/invalid-report").generate(
            context, lambda *args: traces.append(args)
        )
    )

    assert result == PathAgentResult.model_validate(payload)
    assert traces[-1][0:2] == ("deepagent.model.completed", "COMPLETED")


def test_deterministic_mode_delays_every_agent_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTIC_CM_ADAPTER", "deterministic")
    monkeypatch.setenv("AGENTIC_CM_DETERMINISTIC_DELAY_SECONDS", "0.03")
    service = CaseService(
        CaseRepository(tmp_path / "test.db"),
        planner=planner_from_environment(),
        path_agent=path_agent_from_environment(),
        synthesis_agent=synthesis_agent_from_environment(),
    )
    service.ensure_demo_data()

    async def scenario() -> tuple[float, float, float]:
        started = perf_counter()
        await service.orchestrate_case(
            DEMO_CASE_ID, actor=OWNER_ACTOR, role=OWNER_ROLE
        )
        orchestrator_elapsed = perf_counter() - started

        service.approve_manifest(
            DEMO_CASE_ID,
            ["PATH-01"],
            actor=OWNER_ACTOR,
            role=OWNER_ROLE,
        )
        started = perf_counter()
        await service.execute_path(
            DEMO_CASE_ID, "PATH-01", actor=OWNER_ACTOR, role=OWNER_ROLE
        )
        path_elapsed = perf_counter() - started

        for node_id, actor, role in (
            ("SUPPLY", "王淼", "主计划"),
            ("TECH", "林乔", "研发"),
            ("CUSTOMER", "赵宁", "供应经理"),
        ):
            service.approve_commitment(
                DEMO_CASE_ID,
                "PATH-01",
                node_id,
                actor=actor,
                role=role,
            )
        started = perf_counter()
        await service.synthesize_case(
            DEMO_CASE_ID, actor=OWNER_ACTOR, role=OWNER_ROLE
        )
        synthesis_elapsed = perf_counter() - started
        return orchestrator_elapsed, path_elapsed, synthesis_elapsed

    elapsed = asyncio.run(scenario())

    assert all(duration >= 0.025 for duration in elapsed)


def test_planner_cannot_invent_or_omit_catalog_paths(tmp_path: Path) -> None:
    for planner in (_InventingPlanner(), _OmittingPlanner()):
        service = make_service(tmp_path, planner=planner)
        service.reset_demo("supply-chain-golden-path-v1")
        with pytest.raises(AgentOutputError):
            orchestrate(service)
        case = service.get_case(DEMO_CASE_ID)
        assert case.manifest is None
        assert case.phase.value == "INTAKE"


def test_path_agent_cannot_omit_required_role_reports(tmp_path: Path) -> None:
    service = make_service(tmp_path, path_agent=_OmittingRoleReportsPathAgent())
    orchestrate(service)
    service.approve_manifest(DEMO_CASE_ID, ["PATH-01"], actor=OWNER_ACTOR, role=OWNER_ROLE)
    with pytest.raises(AgentOutputError):
        asyncio.run(service.execute_path(DEMO_CASE_ID, "PATH-01", actor=OWNER_ACTOR, role=OWNER_ROLE))
    case = service.get_case(DEMO_CASE_ID)
    assert case.path_attempts[0].solution_revision is None


def test_path_agent_registers_frozen_tools_without_precomputing_results(tmp_path: Path) -> None:
    adapter = _CapturingFunctionToolPathAgent()
    service = make_service(
        tmp_path,
        planner=AllMatchedSkillPathsPlanner(),
        path_agent=adapter,
    )
    orchestrate(service)
    service.approve_manifest(
        DEMO_CASE_ID, ["PATH-01"], actor=OWNER_ACTOR, role=OWNER_ROLE
    )

    asyncio.run(
        service.execute_path(
            DEMO_CASE_ID, "PATH-01", actor=OWNER_ACTOR, role=OWNER_ROLE
        )
    )

    assert adapter.context is not None
    assert {tool["id"] for tool in adapter.context.tool_contracts} == {
        "lookup_material_master",
        "lookup_supply_snapshot",
        "lookup_customer_acceptance",
    }
    assert not hasattr(adapter.context, "tool_results")
    path_run = service.get_agent_runs(
        DEMO_CASE_ID,
        actor=OWNER_ACTOR,
        role=OWNER_ROLE,
        agent_type="path",
    )[0]
    assert "tools.query" not in {event["step"] for event in path_run["events"]}


def test_path_agent_context_files_project_only_generation_inputs() -> None:
    context = PathAgentContext(
        case_snapshot={
            "title": "订单延期",
            "description": "关键物料存在缺口。",
            "business_payload": {"gap_quantity": 100},
            "id": "CM-1",
            "version": 3,
            "classification": {"case_type": "ORDER_DELIVERY_RISK"},
        },
        human_proposal={
            "revision": 2,
            "author": "陈澄",
            "role": "订单统筹经理",
            "content": "优先评估认证范围内的替代料。",
        },
        path={
            "id": "PATH-01",
            "definition": "MaterialSubstitution",
            "title": "物料替代",
            "rationale": "存在替代候选。",
            "selected": True,
            "policies": [{"id": "POL-1"}],
        },
        execution_skills=({
            "id": "material-substitution-analysis",
            "version": "abc123",
            "description": "分析替代候选。",
            "instructions_markdown": "只分析授权候选。",
        },),
        knowledge=({
            "id": "KNOW-1",
            "version": "1.0.0",
            "title": "历史观察",
            "knowledge_type": "experience",
            "source": {"type": "closed_case"},
            "confidence": "medium",
            "content": {"summary": "客户认证可能造成返工。"},
        },),
        authorized_options=({"id": "A", "material_id": "MCU-X7A"},),
        tool_contracts=({
            "id": "lookup_supply_snapshot",
            "description": "查询冻结快照。",
            "read_only": True,
            "input_key": "option_id",
            "records": {
                "A": {"available_quantity": 100},
                "B": {"available_quantity": 80},
            },
        },),
        required_role_reports=({"role": "主计划", "dimension": "供应可行性"},),
        previous_solution_revision=None,
    )

    files = _context_files(context)

    assert json.loads(files["/case/human-proposal.json"]) == {
        "author": "陈澄",
        "role": "订单统筹经理",
        "content": "优先评估认证范围内的替代料。",
    }
    assert json.loads(files["/knowledge/context.json"]) == [{
        "title": "历史观察",
        "knowledge_type": "experience",
        "source": {"type": "closed_case"},
        "confidence": "medium",
        "content": {"summary": "客户认证可能造成返工。"},
    }]
    snapshot = json.loads(files["/case/snapshot.json"])
    assert "id" not in snapshot
    assert "title" not in snapshot
    assert "classification" not in snapshot
    assert not any("tool-results" in path for path in files)
    with pytest.raises(FrozenInstanceError):
        context.path = {}


def test_openai_adapter_repairs_invalid_output_once() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return chat_completion_response({"paths": "not-a-list"})
        return chat_completion_response({
            "paths": [
                {
                    "definition": "MaterialSubstitution",
                    "rationale": "物料缺口与候选能力匹配",
                    "skills": [{"id": "review-bundle", "reason": "需要组合分析技术与供应证据。"}],
                },
                {
                    "definition": "OrderSplit",
                    "rationale": "可用数量支持分批交付探索",
                    "skills": [{"id": "standalone-review", "reason": "需要独立检查拆分风险。"}],
                },
            ]
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = OpenAICompatiblePlannerAdapter(
                "secret-key",
                model="vendor-model-42",
                base_url="https://gateway.example/v1",
                http_client=client,
            )
            return await adapter.propose(
                {"case_id": "CM-1", "title": "延期", "orchestration_knowledge": []},
                (
                    {
                        "definition": "MaterialSubstitution",
                        "title": "物料替代",
                        "description": "desc",
                        "required_review_dimensions": ["技术可行性"],
                    },
                    {
                        "definition": "OrderSplit",
                        "title": "订单拆分",
                        "description": "desc",
                        "required_review_dimensions": ["交付可行性"],
                    },
                ),
                (
                    {"id": "review-bundle", "title": "组合评审", "description": "组合评审。", "kind": "bundle"},
                    {"id": "standalone-review", "title": "独立评审", "description": "独立检查。", "kind": "atomic"},
                ),
                lambda *args, **kwargs: None,
            )

    result = asyncio.run(run())
    assert [path.definition for path in result.paths] == ["MaterialSubstitution", "OrderSplit"]
    assert attempts == 2


def test_synthesis_repairs_paraphrased_artifact_refs(tmp_path: Path) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        supporting_refs = (
            ["PATH-01 方案修订 v1"]
            if attempts == 1
            else ["PATH-01/solution-revision/1", "PATH-01/commitment/SUPPLY"]
        )
        return chat_completion_response({
            "summary": "已汇总一条审批成功的物料替代路径。",
            "path_assessments": [{
                "path_id": "PATH-01",
                "status": "SUCCEEDED",
                "conclusion": "物料替代路径的全部责任节点已经由对应人员批准。",
                "supporting_refs": supporting_refs,
                "risks": ["仍需由 Case Owner 决定是否关闭 Case"],
            }],
            "cross_path_findings": ["本轮仅探索一条 Path，无跨 Path 冲突。"],
            "remaining_risks": ["Agent 汇总不构成最终业务决定。"],
            "recommended_owner_action": "KEEP_OPEN",
            "decision_brief": "请 Case Owner 审查已批准结果并作出最终决定。",
        })

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = CaseService(
                CaseRepository(tmp_path / "test.db"),
                planner=DeterministicPlannerAdapter(),
                path_agent=deterministic_path_adapter(),
                synthesis_agent=OpenAICompatibleSynthesisAgentAdapter(
                    "synthesis-secret",
                    model="vendor-model-42",
                    base_url="https://gateway.example/v1",
                    http_client=client,
                ),
            )
            service.ensure_demo_data()
            await service.orchestrate_case(DEMO_CASE_ID, actor=OWNER_ACTOR, role=OWNER_ROLE)
            service.approve_manifest(DEMO_CASE_ID, ["PATH-01"], actor=OWNER_ACTOR, role=OWNER_ROLE)
            await service.execute_path(DEMO_CASE_ID, "PATH-01", actor=OWNER_ACTOR, role=OWNER_ROLE)
            for node_id, actor, role in (
                ("SUPPLY", "王淼", "主计划"),
                ("TECH", "林乔", "研发"),
                ("CUSTOMER", "赵宁", "供应经理"),
            ):
                service.approve_commitment(DEMO_CASE_ID, "PATH-01", node_id, actor=actor, role=role)
            return await service.synthesize_case(DEMO_CASE_ID, actor=OWNER_ACTOR, role=OWNER_ROLE)

    case = asyncio.run(scenario())
    assert attempts == 2
    assert case.synthesis_report.path_assessments[0].supporting_refs[0] == "PATH-01/solution-revision/1"


def test_failed_agent_run_is_kept_without_business_mutation(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = CaseService(
                CaseRepository(tmp_path / "test.db"),
                planner=OpenAICompatiblePlannerAdapter(
                    "secret",
                    model="vendor-model-42",
                    base_url="https://gateway.example/v1",
                    http_client=client,
                ),
            )
            service.ensure_demo_data()
            with pytest.raises(AgentError):
                await service.orchestrate_case(DEMO_CASE_ID, actor=OWNER_ACTOR, role=OWNER_ROLE)
            return service

    service = asyncio.run(run())
    case = service.get_case(DEMO_CASE_ID)
    assert case.manifest is None
    runs = service.get_agent_runs(DEMO_CASE_ID, actor=OWNER_ACTOR, role=OWNER_ROLE, agent_type="orchestrator")
    assert runs[0]["status"] == "FAILED"
