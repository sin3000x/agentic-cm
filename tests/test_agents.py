import asyncio
from pathlib import Path

import httpx
import pytest

from agentic_cm.agent_runtime import AgentError, AgentOutputError
from agentic_cm.domain import PathAgentResult, ProposedOption, Recommendation, RoleReport
from agentic_cm.orchestrator import (
    OpenAICompatiblePlannerAdapter,
    PlannerOutput,
    PlannerPath,
    PlannerSkillChoice,
)
from agentic_cm.path_agent import DeterministicPathAgentAdapter
from agentic_cm.repository import CaseRepository
from agentic_cm.service import CaseService
from agentic_cm.synthesis_agent import OpenAICompatibleSynthesisAgentAdapter
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
