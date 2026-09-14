import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ValidationError

from agentic_cm.path_agent import DeepAgentPathAdapter, PathAgentContext, _function_tools


def context_for() -> PathAgentContext:
    return PathAgentContext(
        case_snapshot={"business_payload": {"material": "SOURCE-42"}},
        human_proposal=None, path={}, execution_skills=(), knowledge=(),
        tool_contracts=({
            "id": "lookup_material_substitutes", "description": "按缺料编码查询替代关系",
            "input_key": "material_id", "records": {},
        },),
        required_role_reports=(), previous_solution_revision=None,
    )


def test_provider_schema_accepts_business_codes_without_candidate_enum():
    tool, = _function_tools(context_for())
    parameters = convert_to_openai_tool(tool)["function"]["parameters"]
    assert "enum" not in parameters["properties"]["material_id"]
    for code in ("SOURCE-42", "ALTERNATIVE-900", "MCU-X7"):
        assert tool.args_schema.model_validate({"material_id": code}).material_id == code
    with pytest.raises(ValidationError):
        tool.args_schema.model_validate({"material_id": ""})


def test_query_uses_invocation_records_and_reports_missing_evidence():
    tool, = _function_tools(context_for())
    runtime = SimpleNamespace(state={"path_tool_records": {
        tool.name: {"SOURCE-42": {"candidates": [{"material_id": "ALTERNATIVE-900"}]}}
    }})
    assert tool.func(runtime=runtime, material_id="SOURCE-42")["candidates"] == [
        {"material_id": "ALTERNATIVE-900"}
    ]
    assert tool.func(runtime=runtime, material_id="UNKNOWN")["status"] == "not_found"
    other_runtime = SimpleNamespace(state={"path_tool_records": {tool.name: {}}})
    assert tool.func(runtime=other_runtime, material_id="SOURCE-42")["status"] == "not_found"


def test_graph_reuses_contract_without_freezing_business_data():
    builds = []

    def factory(**kwargs):
        graph = SimpleNamespace(**kwargs)
        builds.append(graph)
        return graph

    adapter = DeepAgentPathAdapter(None, profile="test", graph_factory=factory)
    context = context_for()
    first = adapter._graph_for(context)
    changed = replace(context, tool_contracts=({
        **context.tool_contracts[0], "records": {"OTHER-SOURCE": {"candidates": []}},
    },))
    assert adapter._graph_for(changed) is first
    assert len(builds) == 1


def test_case_material_drives_demo_discovery_and_candidate_evidence():
    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "capabilities/builtin/skills/material-substitution-analysis/tools.json").read_text())
    context = replace(context_for(), tool_contracts=tuple(data["tools"]),
                      case_snapshot={"business_payload": {"material": "MCU-X7"}})
    tools = {tool.name: tool for tool in _function_tools(context)}
    runtime = SimpleNamespace(state={"path_tool_records": {
        contract["id"]: contract["records"] for contract in context.tool_contracts
    }})
    source = context.case_snapshot["business_payload"]["material"]
    candidates = tools["lookup_material_substitutes"].func(runtime=runtime, material_id=source)["candidates"]
    assert candidates
    for candidate in candidates:
        for name in ("lookup_material_master", "lookup_supply_snapshot", "lookup_customer_acceptance"):
            result = tools[name].func(runtime=runtime, material_id=candidate["material_id"])
            assert result and result.get("status") != "not_found"
    assert tools["lookup_material_substitutes"].func(runtime=runtime, material_id="UNLISTED")["status"] == "not_found"
