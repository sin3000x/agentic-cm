"""Provider streams must expose progress before completion without changing Agent output."""
import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from langchain_core.messages import HumanMessage

from agentic_cm.llm import ProviderTextStream, provider_reasoning
from agentic_cm.orchestrator import OpenAICompatiblePlannerAdapter
from agentic_cm.path_agent import DeepAgentPathAdapter, _PathChatOpenAI
from agentic_cm.synthesis_agent import OpenAICompatibleSynthesisAgentAdapter, SynthesisContext
from test_path_convergence import context_for


def frame(delta=None, *, finish=None, usage=None):
    body = {
        "id": "stream-test", "object": "chat.completion.chunk", "created": 1,
        "model": "test-model", "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}],
    }
    if usage:
        body["usage"] = usage
    return ("data: " + json.dumps(body, ensure_ascii=False) + "\n\n").encode()


class GatedStream(httpx.AsyncByteStream):
    def __init__(self, release, output, *, style="field", fail=False):
        self.release, self.output, self.style, self.fail = release, output, style, fail
        self.closed = False

    async def __aiter__(self):
        if self.style == "field":
            yield frame({"reasoning_content": "正在核查供应证据。"})
        else:
            yield frame({"content": "<thi"})
            yield frame({"content": "nk>正在核查供应证据。"})
        await self.release.wait()
        if self.fail:
            raise httpx.ReadError("connection interrupted")
        if self.style == "tags":
            yield frame({"content": "</thi"})
            yield frame({"content": "nk>"})
        yield frame(self.output)
        yield frame(finish="tool_calls" if "tool_calls" in self.output else "stop", usage={
            "prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30,
        })
        yield b"data: [DONE]\n\n"

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("agent_type", ["orchestrator", "path", "synthesis"])
@pytest.mark.parametrize("style", ["field", "tags"])
def test_all_agents_publish_provider_reasoning_before_result(agent_type, style):
    async def scenario():
        release, observed = asyncio.Event(), asyncio.Event()
        events, requests = [], []
        answer = {
            "recommendation": "请依据供应证据完成人工评审。", "role_reports": [],
        }
        if agent_type == "orchestrator":
            output = {"content": json.dumps({"paths": [{
                "definition": "MaterialSubstitution", "rationale": "需要核查物料替代。",
                "skills": [{"id": "review-bundle", "reason": "需要评估供应证据。"}],
            }]}, ensure_ascii=False)}
        elif agent_type == "synthesis":
            output = {"content": json.dumps({
                "summary": "已汇总评审结果。", "path_assessments": [{
                    "path_id": "PATH-01", "status": "SUCCEEDED", "conclusion": "人工评审已完成。",
                    "supporting_refs": ["PATH-01/solution-revision/1"], "risks": ["仍需最终决策。"],
                }], "cross_path_findings": ["无跨路径冲突。"], "remaining_risks": ["等待最终决策。"],
                "recommended_owner_action": "KEEP_OPEN", "decision_brief": "请责任人审查并决策。",
            }, ensure_ascii=False)}
        else:
            output = {"tool_calls": [{"index": 0, "id": "final-1", "type": "function", "function": {
                "name": "PathAgentResult", "arguments": json.dumps(answer, ensure_ascii=False),
            }}]}
        stream = GatedStream(release, output, style=style)

        def handle(request):
            payload = json.loads(request.content)
            assert payload["stream"] is True
            assert payload["thinking"] == {"type": "disabled"}
            assert "reasoning_effort" not in payload
            requests.append(payload)
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

        def trace(*event):
            events.append(event)
            if event[0] == "model.reasoning.delta":
                observed.set()

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            common = {"model": "test-model", "base_url": "https://mock.invalid/v1"}
            if agent_type == "orchestrator":
                adapter = OpenAICompatiblePlannerAdapter("test", http_client=client, **common)
                operation = adapter.propose({}, ({
                    "definition": "MaterialSubstitution", "title": "物料替代", "description": "分析供应。",
                    "required_review_dimensions": ["供应"],
                },), ({"id": "review-bundle", "title": "供应评审", "description": "核查供应", "kind": "bundle"},), trace)
            elif agent_type == "synthesis":
                adapter = OpenAICompatibleSynthesisAgentAdapter("test", http_client=client, **common)
                operation = adapter.generate(SynthesisContext(
                    case_snapshot={}, manifest_ref={}, path_results=[{
                        "path_id": "PATH-01", "status": "SUCCEEDED", "definition": "MaterialSubstitution",
                        "title": "物料替代", "solution_revision": {}, "commitments": [],
                        "authorized_supporting_refs": ["PATH-01/solution-revision/1"],
                    }],
                ), trace)
            else:
                model = _PathChatOpenAI(
                    api_key="test", http_async_client=client, streaming=True, max_retries=0,
                    extra_body={"thinking": {"type": "disabled"}}, **common,
                )
                adapter = DeepAgentPathAdapter(model, profile="test/streaming-path")
                operation = adapter.generate(replace(context_for(), required_role_reports=()), trace)
            pending = asyncio.create_task(operation)
            try:
                await asyncio.wait_for(observed.wait(), timeout=5)
                assert not pending.done(), "reasoning must be visible while the provider is still generating"
                assert "正在核查供应证据。" == "".join(e[3]["text"] for e in events if e[0] == "model.reasoning.delta")
                release.set()
                result = await asyncio.wait_for(pending, timeout=10)
                assert result is not None
                assert len(requests) == 1
                assert stream.closed
                if agent_type == "path":
                    assert result.recommendation == answer["recommendation"]
                assert all(e[3]["call_id"] for e in events if e[0] == "model.reasoning.delta")
            finally:
                release.set()
                if not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)

    asyncio.run(scenario())


def test_think_tag_parser_preserves_answer_for_every_chunk_boundary():
    body = '<think>核查真实证据。</think>{"note":"正文中的 <think> 标签"}'
    for boundary in range(len(body) + 1):
        parser = ProviderTextStream()
        fragments = [parser.feed(body[:boundary]), parser.feed(body[boundary:]), parser.finish()]
        assert "".join(pair[0] for pair in fragments) == '{"note":"正文中的 <think> 标签"}'
        assert "".join(pair[1] for pair in fragments) == "核查真实证据。"


def test_reasoning_aliases_do_not_duplicate_or_include_signatures():
    assert provider_reasoning({"reasoning_content": "分析", "reasoning": "分析"}) == "分析"
    assert provider_reasoning({"thinking": [{"thinking": "分析"}]}) == "分析"
    assert provider_reasoning({"reasoning_details": [
        {"type": "reasoning.text", "text": "分析"}, {"type": "reasoning.signature", "text": "opaque"},
    ]}) == "分析"


def test_parallel_path_streams_keep_reasoning_separate():
    async def scenario():
        def handle(request):
            label = json.loads(request.content)["messages"][-1]["content"]
            class Stream(httpx.AsyncByteStream):
                async def __aiter__(self):
                    yield frame({"reasoning_content": f"分析{label}。"})
                    await asyncio.sleep(0)
                    yield frame({"content": f"答案{label}。"}, finish="stop")
                    yield b"data: [DONE]\n\n"
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Stream())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            model = _PathChatOpenAI(
                model="test", api_key="test", base_url="https://mock.invalid/v1",
                http_async_client=client, streaming=True,
            )
            results = await asyncio.gather(*(model.ainvoke([HumanMessage(content=label)]) for label in ("甲", "乙")))
            assert [message.content for message in results] == ["答案甲。", "答案乙。"]
            assert [message.additional_kwargs["provider_reasoning"] for message in results] == ["分析甲。", "分析乙。"]
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["cancel", "disconnect", "truncated"])
@pytest.mark.parametrize("agent_type", ["orchestrator", "path"])
def test_interrupted_reasoning_is_preserved_without_committing_a_result(tmp_path, failure, agent_type):
    from agentic_cm.agent_runtime import AgentExecutionError
    from conftest import DEMO_CASE_ID, OWNER, make_service

    async def scenario():
        release, observed = asyncio.Event(), asyncio.Event()
        class TruncatedStream(GatedStream):
            async def __aiter__(self):
                yield frame({"reasoning_content": "已查询供应证据，尚未形成结论。"})
                await release.wait()
                yield frame({"content": '{"paths":'})
        stream = (TruncatedStream(release, {}) if failure == "truncated"
                  else GatedStream(release, {}, fail=failure == "disconnect"))
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=stream,
        ))) as client:
            if agent_type == "orchestrator":
                service = make_service(tmp_path, planner=OpenAICompatiblePlannerAdapter(
                    "test-secret", model="test-model", base_url="https://mock.invalid/v1", http_client=client,
                ))
                operation = service.orchestrate_case(DEMO_CASE_ID, **OWNER)
            else:
                service = make_service(tmp_path)
                await service.orchestrate_case(DEMO_CASE_ID, **OWNER)
                service.approve_manifest(DEMO_CASE_ID, ["PATH-01"], **OWNER)
                service.path_agent.adapter = DeepAgentPathAdapter(_PathChatOpenAI(
                    api_key="test-secret", model="test-model", base_url="https://mock.invalid/v1",
                    http_async_client=client, streaming=True, max_retries=0,
                ), profile="test/interrupted-path")
                operation = service.execute_path(DEMO_CASE_ID, "PATH-01", **OWNER)
            append = service.repository.append_agent_trace
            def capture(*args, **kwargs):
                append(*args, **kwargs)
                if kwargs["step"] == "model.reasoning.delta":
                    observed.set()
            service.repository.append_agent_trace = capture
            before = service.get_case(DEMO_CASE_ID).to_dict()
            pending = asyncio.create_task(operation)
            try:
                await asyncio.wait_for(observed.wait(), 5)
                if failure == "cancel":
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
                else:
                    release.set()
                    with pytest.raises(AgentExecutionError):
                        await pending
                assert service.get_case(DEMO_CASE_ID).to_dict() == before
                run = service.repository.list_agent_runs(DEMO_CASE_ID)[0]
                assert run["status"] == ("CANCELLED" if failure == "cancel" else "FAILED")
                assert any(event["step"] == "model.reasoning.delta" for event in run["events"])
                assert stream.closed
                assert "test-secret" not in json.dumps(run, ensure_ascii=False)
            finally:
                release.set()
                if not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)

    asyncio.run(scenario())
