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
    assert model.calls == 13


def test_invalid_finalization_stops_after_two_attempts():
    model = ConvergenceModel(mode="invalid")
    with pytest.raises(AgentOutputError, match="限定收尾轮次"):
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
                context_for(), lambda *args: None,
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
