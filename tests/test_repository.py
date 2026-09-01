from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from agentic_cm.repository import CaseRepository


def test_agent_trace_sequences_are_unique_under_concurrent_writes(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "test.db")
    repository.create_agent_run(
        "RUN-CONCURRENT",
        "CASE-CONCURRENT",
        agent_type="path",
        adapter_profile="test",
        initiated_by="test",
    )
    writer_count = 16
    ready = Barrier(writer_count)

    def append_trace(index: int) -> None:
        ready.wait()
        repository.append_agent_trace(
            "RUN-CONCURRENT",
            step="tool.completed",
            status="COMPLETED",
            summary=f"tool {index}",
        )

    with ThreadPoolExecutor(max_workers=writer_count) as executor:
        list(executor.map(append_trace, range(writer_count)))

    events = repository.list_agent_runs("CASE-CONCURRENT")[0]["events"]
    assert [event["sequence"] for event in events] == list(range(1, writer_count + 1))
