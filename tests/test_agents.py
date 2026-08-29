import asyncio
import json
from pathlib import Path
from time import perf_counter

import httpx
import pytest

from agentic_cm.agent_runtime import AgentError, AgentOutputError
from agentic_cm.domain import PathAgentResult, ProposedOption, Recommendation, RoleReport
from agentic_cm.orchestrator import (
    planner_from_environment,
    OpenAICompatiblePlannerAdapter,
    PlannerOutput,
    PlannerPath,
    PlannerSkillChoice,
)
from agentic_cm.path_agent import (
    DeterministicPathAgentAdapter,
    OpenAICompatiblePathAgentAdapter,
    PathAgentContext,
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


class _InventingPathAgent:
    profile = "test/inventing-path"

    async def generate(self, context, trace):
        return PathAgentResult(
            summary="引入了清单外选项。",
            options=[
                ProposedOption(
                    id="INVENTED",
                    title="清单外选项",
                    description="模型自行发明的方案。",
                    benefits=["无"],
                    risks=["越权"],
                    assumptions=["无依据"],
                )
            ],
            recommendation=Recommendation(option_ids=["INVENTED"], rationale="发明了未授权选项。"),
            evidence_gaps=["缺少授权"],
            role_reports=[
                RoleReport(role=item["role"], dimension=item["dimension"], report=f"{item['role']}维度：未授权。")
                for item in context.required_role_reports
            ],
        )


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


def test_path_agent_cannot_invent_unauthorized_option(tmp_path: Path) -> None:
    service = make_service(tmp_path, path_agent=_InventingPathAgent())
    orchestrate(service)
    service.approve_manifest(DEMO_CASE_ID, ["PATH-01"], actor=OWNER_ACTOR, role=OWNER_ROLE)
    with pytest.raises(AgentOutputError):
        asyncio.run(service.execute_path(DEMO_CASE_ID, "PATH-01", actor=OWNER_ACTOR, role=OWNER_ROLE))
    case = service.get_case(DEMO_CASE_ID)
    assert case.path_attempts[0].solution_revision is None


def test_path_agent_request_uses_compact_output_schema() -> None:
    captured_request: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request.update(json.loads(request.content))
        return chat_completion_response({
            "summary": "已形成一项待复核方案。",
            "options": [{
                "id": "A",
                "title": "候选方案甲",
                "description": "依据冻结信息形成的候选方案。",
                "benefits": ["便于责任角色复核。"],
                "risks": ["当前证据仍不完整。"],
                "assumptions": ["尚未形成业务承诺。"],
            }],
            "recommendation": {
                "option_ids": ["A"],
                "rationale": "建议优先复核候选方案甲。",
            },
            "evidence_gaps": ["需要补充当前业务证据。"],
            "role_reports": [],
        })

    context = PathAgentContext(
        case_snapshot={"case_id": "CM-1"},
        human_proposal=None,
        manifest_ref={"id": "manifest-1", "revision": 1},
        path={"id": "PATH-01", "title": "物料替代"},
        path_attempt={"path_id": "PATH-01", "state": "PLANNED"},
        execution_skills=[],
        knowledge=[],
        authorized_options=[{"id": "A", "title": "候选方案甲"}],
        authorized_option_ids=("A",),
        tool_results=[],
        required_role_reports=[],
        previous_solution_revision=None,
    )

    async def run() -> PathAgentResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = OpenAICompatiblePathAgentAdapter(
                "secret-key",
                model="vendor-model-42",
                base_url="https://gateway.example/v1",
                http_client=client,
            )
            return await adapter.generate(context, lambda *args, **kwargs: None)

    result = asyncio.run(run())
    system_prompt = captured_request["messages"][0]["content"]
    schema_text = system_prompt.split(
        "Match this compact JSON Schema exactly: ", maxsplit=1
    )[1].split(". Return role_reports", maxsplit=1)[0]
    output_schema = json.loads(schema_text)
    option_schema = output_schema["$defs"]["ProposedOption"]

    assert result.options[0].id == "A"
    assert output_schema["required"] == [
        "summary", "options", "recommendation", "evidence_gaps", "role_reports"
    ]
    assert option_schema["properties"]["title"] == {"type": "string"}
    assert option_schema["properties"]["description"] == {"type": "string"}
    assert '"title":"' not in schema_text
    assert '"description":"' not in schema_text
    assert '"additionalProperties"' not in schema_text
    assert '"minLength"' not in schema_text
    assert '"minItems"' not in schema_text
    assert "title" not in output_schema
    assert "description" not in output_schema
    assert "additionalProperties" not in output_schema
    assert "title" not in option_schema
    assert "additionalProperties" not in option_schema
    assert "minLength" not in option_schema["properties"]["id"]
    assert "minItems" not in output_schema["properties"]["options"]


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
                path_agent=DeterministicPathAgentAdapter(),
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
