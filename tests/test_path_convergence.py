import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agentic_cm.agent_runtime import AgentOutputError
from agentic_cm.path_agent import DeepAgentPathAdapter, PathAgentContext, _DeterministicPathChatModel, _PathChatOpenAI


class ConvergenceModel(BaseChatModel):
    mode: str = "duplicates"
    calls: int = 0
    tools_available: list[str] = []
    observed_records: list[str] = []

    @property
    def _llm_type(self):
        return "test-path-convergence"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        self.tools_available = [tool.name for tool in tools]
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        finalizing = self.tools_available == ["PathAgentResult"]
        if finalizing and self.mode != "ignore-finalization":
            assert "禁止继续查询" in str(messages[0].content)
            if self.mode == "invalid":
                name, args = "PathAgentResult", {"role_reports": "invalid"}
            else:
                replies = [m for m in messages if isinstance(m, ToolMessage)]
                self.observed_records.append(str(replies[0].content))
                name, args = "PathAgentResult", {
                    "recommendation": "", "role_reports": [],
                    "information_requests": [{
                        "role": "主计划", "question": "请确认截止日前可供数量。",
                        "reason": "冻结记录缺少日期供货确认。",
                    }],
                }
            calls = [{"name": name, "args": args, "id": f"final-{self.calls}", "type": "tool_call"}]
        else:
            if self.mode == "reads":
                name, args = "read_file", {"file_path": "/case/snapshot.json"}
                count = 1
            else:
                name, args = "lookup_material_substitutes", {"material_id": "SOURCE"}
                count = 4
            calls = [{"name": name, "args": args, "id": f"query-{self.calls}-{i}", "type": "tool_call"}
                     for i in range(count)]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=calls))])


def context_for(value="FIRST"):
    return PathAgentContext(
        case_snapshot={"business_payload": {"material": "SOURCE"}},
        human_proposal=None, path={}, execution_skills=(), knowledge=(),
        tool_contracts=({"id": "lookup_material_substitutes", "description": "查询冻结候选",
                         "input_key": "material_id", "records": {"SOURCE": {"candidate": value}}},),
        required_role_reports=({"role": "主计划", "dimension": "供应"},),
        previous_solution_revision=None,
    )


def test_parallel_duplicate_queries_finalize_and_cache_is_per_invocation():
    model = ConvergenceModel()
    adapter = DeepAgentPathAdapter(model, profile="test/convergence")
    for value in ("FIRST", "SECOND"):
        model.calls = 0
        events = []
        result = asyncio.run(adapter.generate(context_for(value), lambda *args: events.append(args)))
        assert result.information_requests and not result.recommendation
        assert model.calls == 2
        assert sum(e[0] == "deepagent.tool.completed" for e in events) == 1
        assert sum(e[0] == "deepagent.tool.reused" for e in events) == 3
        assert any(e[0] == "deepagent.finalization.started" for e in events)
        assert value in model.observed_records[-1]


def test_filesystem_loop_reaches_bounded_finalization_instead_of_graph_limit():
    model = ConvergenceModel(mode="reads")
    result = asyncio.run(DeepAgentPathAdapter(model, profile="test/read-loop").generate(
        replace(context_for(), tool_contracts=()), lambda *args: None,
    ))
    assert result.information_requests
    assert model.calls == 5


def test_invalid_finalization_stops_after_two_attempts():
    model = ConvergenceModel(mode="invalid")
    with pytest.raises(AgentOutputError, match="role_reports"):
        asyncio.run(DeepAgentPathAdapter(model, profile="test/invalid-final").generate(
            context_for(), lambda *args: None,
        ))
    assert model.calls == 3


def test_model_cannot_keep_querying_after_finalization():
    model = ConvergenceModel(mode="ignore-finalization")
    events = []
    with pytest.raises(AgentOutputError, match="限定收尾轮次"):
        asyncio.run(DeepAgentPathAdapter(model, profile="test/ignored-final").generate(
            context_for(), lambda *args: events.append(args),
        ))
    assert model.calls == 3
    assert sum(e[0] == "deepagent.tool.completed" for e in events) == 1
    assert sum(e[0] == "deepagent.tool.reused" for e in events) == 3


@pytest.mark.parametrize("numbered", [True, False])
def test_demo_model_reads_supported_file_formats(numbered):
    def formatted(body):
        return f"1  {body}" if numbered else f"@@ lines 1-1 @@\n{body}"

    reply = _DeterministicPathChatModel()._response([
        HumanMessage(content="分析当前 Case"),
        ToolMessage(content=formatted('{"business_payload": {}}'), tool_call_id="deterministic-case"),
        ToolMessage(content=formatted('[]'), tool_call_id="deterministic-reports"),
    ])
    assert reply.tool_calls[0]["name"] == "PathAgentResult"
    assert reply.tool_calls[0]["args"]["recommendation"]


def test_cache_replay_preserves_ordered_tool_history_on_the_wire():
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        turn = len(requests)
        if turn <= 4:
            name, args = "lookup_material_substitutes", {"material_id": "SOURCE"}
        else:
            name, args = "PathAgentResult", {"recommendation": "需要核实供货数量。", "role_reports": []}
        return httpx.Response(200, json={
            "id": f"completion-{turn}", "object": "chat.completion", "created": 1,
            "model": "test-path", "choices": [{"index": 0, "finish_reason": "tool_calls",
                "message": {"role": "assistant", "content": "", "tool_calls": [{
                    "id": f"call-{turn}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }]}}],
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            model = _PathChatOpenAI(
                model="test-path", api_key="test", base_url="https://mock.invalid/v1",
                http_async_client=client, max_retries=0,
            )
            return await DeepAgentPathAdapter(model, profile="test/wire-history").generate(
                replace(context_for(), required_role_reports=()), lambda *args: None,
            )

    assert asyncio.run(run()).recommendation
    assert len(requests) == 5
    for turn, request in enumerate(requests, start=1):
        history = [m for m in request["messages"] if m["role"] in {"assistant", "tool"}]
        assert [m["role"] for m in history] == ["assistant", "tool"] * (turn - 1)
        for index in range(turn - 1):
            call, result = history[index * 2:index * 2 + 2]
            assert call["tool_calls"][0]["id"] == result["tool_call_id"] == f"call-{index + 1}"
            assert json.loads(result["content"]) == {"candidate": "FIRST"}


@pytest.mark.parametrize("failure", ["missing_summary", "mixed_summary", "mixed_recommendation", "invalid_schema"])
def test_output_repair_keeps_evidence_and_only_binds_submission(failure):
    from agentic_cm.domain import SolutionRevision

    report = {"role": "主计划", "dimension": "供应", "report": "供应数量仍待确认。"}
    question = {"role": "主计划", "question": "请提供到货日期。", "reason": "缺少日期证据。"}
    corrected = ({"recommendation": "建议评估候选。", "role_reports": [report],
                  "change_summary": "已回应意见，明确供货条件。"}
                 if failure == "missing_summary" else
                 {"information_requests": [question]})
    rejected = ({"recommendation": "建议评估候选。", "role_reports": [report]}
                if failure == "missing_summary" else
                {"information_requests": [question],
                 "change_summary": "已修改。" if failure == "mixed_summary" else "",
                 "recommendation": "建议评估候选。" if failure == "mixed_recommendation" else "",
                 "role_reports": "invalid" if failure == "invalid_schema" else []})

    class RepairModel(BaseChatModel):
        calls: int = 0
        available: list[str] = []

        @property
        def _llm_type(self):
            return "repair-with-evidence"

        def bind_tools(self, tools, **kwargs):
            self.available = [tool.name for tool in tools]
            return self

        def _get_ls_params(self, **kwargs):
            return {"ls_provider": "agentic-cm", "ls_model_name": "repair-with-evidence"}

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            if self.calls == 1:
                name, args = "lookup_material_substitutes", {"material_id": "SOURCE"}
            else:
                name, args = "PathAgentResult", rejected if self.calls == 2 else corrected
                if self.calls == 3:
                    assert self.available == ["PathAgentResult"]
                    evidence = [m for m in messages if isinstance(m, ToolMessage)
                                and m.tool_call_id == "repair-1"]
                    assert len(evidence) == 1 and json.loads(evidence[0].content) == {"candidate": "FIRST"}
                    feedback = messages[-1]
                    assert isinstance(feedback, ToolMessage) and feedback.status == "error"
                    assert "禁止重新取证" in feedback.content
                    assert ("recommendation" if failure == "mixed_recommendation" else
                            "role_reports" if failure == "invalid_schema" else "change_summary") in feedback.content
                    if failure == "missing_summary":
                        assert "说明供货条件" in feedback.content
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[{
                "name": name, "args": args, "id": f"repair-{self.calls}", "type": "tool_call",
            }]))])

    context = context_for()
    if failure == "missing_summary":
        context = replace(context, previous_solution_revision=SolutionRevision(
            recommendation="旧方案。", role_reports=[report], revision=1, generated_by="test",
        ), revision_feedback=({"reason": "说明供货条件"},))
    model = RepairModel()
    events = []
    result = asyncio.run(DeepAgentPathAdapter(model, profile="test/repair").generate(
        context, lambda *args: events.append(args),
    ))
    assert model.calls == 3
    assert result.model_dump(exclude_defaults=True) == corrected
    assert sum(e[0] == "deepagent.runtime.started" for e in events) == 1
    assert sum(e[0] == "deepagent.tool.completed" for e in events) == 1
    assert sum(e[0] == "agent.repair_completed" for e in events) == 1


def test_supply_scope_repair_receives_exact_case_values_without_new_queries():
    class ScopeModel(BaseChatModel):
        calls: int = 0
        available: list[str] = []

        @property
        def _llm_type(self):
            return "scope-repair"

        def _get_ls_params(self, **kwargs):
            return {"ls_provider": "agentic-cm", "ls_model_name": "scope-repair"}

        def bind_tools(self, tools, **kwargs):
            self.available = [tool.name for tool in tools]
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            if self.calls == 1:
                name, args = "lookup_material_substitutes", {"material_id": "SOURCE"}
                assert "2026-11-15" in str(messages[1].content)
            else:
                name = "PathAgentResult"
                if self.calls == 3:
                    assert self.available == ["PathAgentResult"]
                    feedback = messages[-1].content
                    for value in ("information_requests[0]", "WRONG", "2026-10-01", "ALTERNATIVE", "2026-11-15"):
                        assert value in feedback
                    assert "OTHER-CASE-CANDIDATE" not in feedback
                args = {"information_requests": [{"role": "主计划", "question": "请确认截止日前可供数量。",
                        "reason": "缺少日期供货确认。", "material_id": "WRONG" if self.calls == 2 else "ALTERNATIVE",
                        "required_by": "2026-10-01" if self.calls == 2 else "2026-11-15"}]}
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[{
                "name": name, "args": args, "id": f"scope-{self.calls}", "type": "tool_call",
            }]))])

    context = replace(context_for(), case_snapshot={"business_payload": {"material": "SOURCE", "target_date": "2026-11-15"}},
                      tool_contracts=({**context_for().tool_contracts[0], "records": {
                          "SOURCE": {"candidates": [{"material_id": "ALTERNATIVE"}]},
                          "OTHER": {"candidates": [{"material_id": "OTHER-CASE-CANDIDATE"}]},
                      }},))
    events = []
    model = ScopeModel()
    result = asyncio.run(DeepAgentPathAdapter(model, profile="test/scope").generate(context, lambda *args: events.append(args)))
    assert result.information_requests[0].material_id == "ALTERNATIVE"
    assert sum(e[0] == "deepagent.tool.completed" for e in events) == 1
    assert model.calls == 3


def test_candidate_tools_unlock_only_after_discovery_and_reject_guessed_ids():
    class DiscoveryModel(BaseChatModel):
        calls: int = 0
        available: list[str] = []

        @property
        def _llm_type(self):
            return "discovery-gate"

        def _get_ls_params(self, **kwargs):
            return {"ls_provider": "agentic-cm", "ls_model_name": "discovery-gate"}

        def bind_tools(self, tools, **kwargs):
            self.available = [tool.name for tool in tools]
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            if self.calls == 1:
                assert "lookup_customer_acceptance" not in self.available
                # A provider may still emit a tool absent from its current schema.
                calls = [("lookup_customer_acceptance", {"material_id": "GUESS"}),
                         ("lookup_material_substitutes", {"material_id": "SOURCE"})]
            elif self.calls == 2:
                assert "lookup_customer_acceptance" in self.available
                rejected = next(m for m in messages if isinstance(m, ToolMessage) and m.tool_call_id == "gate-1-0")
                assert rejected.status == "error"
                calls = [("lookup_customer_acceptance", {"material_id": "ALTERNATIVE"})]
            else:
                calls = [("PathAgentResult", {"recommendation": "建议评估候选。", "role_reports": []})]
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[{
                "name": name, "args": args, "id": f"gate-{self.calls}-{i}", "type": "tool_call",
            } for i, (name, args) in enumerate(calls)]))])

    context = replace(context_for(), required_role_reports=(), tool_contracts=(
        {**context_for().tool_contracts[0], "records": {"SOURCE": {"candidates": [{"material_id": "ALTERNATIVE"}]}}},
        {"id": "lookup_customer_acceptance", "description": "查询客户记录", "input_key": "material_id",
         "records": {"ALTERNATIVE": {"accepted": False}, "GUESS": {"accepted": True}}},
    ))
    events = []
    result = asyncio.run(DeepAgentPathAdapter(DiscoveryModel(), profile="test/discovery").generate(context, lambda *args: events.append(args)))
    assert result.recommendation
    queries = [e[3]["input"] for e in events if e[0] == "deepagent.tool.started"]
    assert {"material_id": "GUESS"} not in queries
    assert queries == [{"material_id": "SOURCE"}, {"material_id": "ALTERNATIVE"}]
