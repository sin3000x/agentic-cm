import asyncio
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from time import perf_counter

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from agentic_cm.agent_runtime import AgentError, AgentExecutionError, AgentOutputError
from agentic_cm.domain import PathAgentResult, RoleReport
from agentic_cm.orchestrator import (
    planner_from_environment,
    OpenAICompatiblePlannerAdapter,
    PlannerOutput,
    PlannerPath,
    PlannerSkillChoice,
)
from agentic_cm.path_agent import (
    DeepAgentPathAdapter,
    PathAgentContext,
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
        tool_results=(),
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
        tool_results=(),
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
        tool_results=(),
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
        tool_results=(),
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


def test_deep_agent_traces_rejected_semantic_output() -> None:
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
        tool_results=(),
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

    with pytest.raises(AgentOutputError):
        asyncio.run(
            DeepAgentPathAdapter(model, profile="test/invalid-report").generate(
                context, lambda *args: traces.append(args)
            )
        )

    details = traces[-1][3]
    assert details["error_type"] == "AgentOutputError"
    assert "missing=" in details["error"]
    assert details["rejected_result"] == payload


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


def test_path_agent_context_projects_only_generation_inputs() -> None:
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
        tool_results=({
            "tool_id": "mock.lookup",
            "description": "查询冻结快照。",
            "read_only": True,
            "input": {"option_id": "A"},
            "output": {"available_quantity": 100},
            "source_skill": {"id": "material-substitution-analysis"},
        }, {
            "tool_id": "mock.lookup",
            "description": "查询冻结快照。",
            "read_only": True,
            "input": {"option_id": "B"},
            "output": {"available_quantity": 80},
            "source_skill": {"id": "material-substitution-analysis"},
        }),
        required_role_reports=({"role": "主计划", "dimension": "供应可行性"},),
        previous_solution_revision=None,
    )

    payload = context.prompt_payload()

    assert payload["human_proposal"] == {
        "author": "陈澄",
        "role": "订单统筹经理",
        "content": "优先评估认证范围内的替代料。",
    }
    assert payload["execution_skills"] == [{
        "id": "material-substitution-analysis",
    }]
    assert payload["knowledge"] == [{
        "title": "历史观察",
        "knowledge_type": "experience",
        "source": {"type": "closed_case"},
        "confidence": "medium",
        "content": {"summary": "客户认证可能造成返工。"},
    }]
    assert payload["tool_results"] == [{
        "tool_id": "mock.lookup",
        "records": {
            "A": {"available_quantity": 100},
            "B": {"available_quantity": 80},
        },
        "description": "查询冻结快照。",
    }]
    assert "id" not in payload["case_snapshot"]
    assert "title" not in payload["case_snapshot"]
    assert "classification" not in payload["case_snapshot"]
    assert "path" not in payload
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
