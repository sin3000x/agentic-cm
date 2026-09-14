from uuid import uuid4

from agentic_cm.path_agent import _DeepAgentTraceCallback


def test_tool_trace_correlates_overlapping_calls_and_errors() -> None:
    events = []
    callback = _DeepAgentTraceCallback(lambda *event: events.append(event))
    first, second = uuid4(), uuid4()
    for call_id in (first, second):
        callback.on_tool_start(
            {"name": "lookup_material_master"}, '{"material_code":"MAT-001"}',
            run_id=call_id, inputs={"material_code": "MAT-001"},
        )
    callback.on_tool_end('{"available":24}', run_id=second)
    callback.on_tool_error(ValueError("查询失败"), run_id=first)
    assert [event[3]["call_id"] for event in events] == [
        str(first), str(second), str(second), str(first),
    ]
    assert [event[1] for event in events] == ["STARTED", "STARTED", "COMPLETED", "FAILED"]
    assert events[0][3]["input"] == events[3][3]["input"]
    assert events[1][3]["input"] == events[2][3]["input"]
