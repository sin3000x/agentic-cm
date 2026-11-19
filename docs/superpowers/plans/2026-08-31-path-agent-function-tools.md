# Path Agent Function Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register Manifest-frozen Skill queries as real Deep Agents Function Tools and move Path business inputs from a one-shot JSON message into a constrained read-only virtual filesystem.

**Architecture:** `PathAgent` validates and freezes tool contracts but does not execute them. `DeepAgentPathAdapter` projects invocation files, builds or reuses a graph keyed by authorized tool schemas, and lets tools read current frozen records from invocation state; `PathAgent` remains the only business-semantic validation boundary.

**Tech Stack:** Python 3.11+, Deep Agents 0.7.11, LangChain 1.x, Pydantic 2, pytest

**Spec:** `docs/superpowers/specs/2026-08-31-path-agent-function-tools-design.md`

## Global Constraints

- Keep HTTP API, Manifest, Commitment DAG, `PathAgentResult`, and `SolutionRevision` unchanged.
- Capability assets and Manifest snapshots remain authoritative; do not hardcode a second result dataset in Python.
- Expose only current-Manifest Skills, files, options, and Function Tools.
- Do not add external system access, subagents, writable files, checkpointing, or human interrupts.
- Keep `docs/superpowers` local and ignored; do not commit or push.

---

### Task 1: Define the observable Function Tool contract

**Files:**
- Modify: `tests/test_agents.py`
- Modify: `backend/agentic_cm/path_agent.py`

**Interfaces:**
- Consumes: `PathAgentContext.tool_contracts`, `PathAgentContext.authorized_options`.
- Produces: `_function_tools(context, trace) -> tuple[BaseTool, ...]` whose tools return frozen records and reject unauthorized ids.

- [ ] Add a failing test that constructs one frozen tool with records for A and B, authorizes only A, invokes the real generated tool, asserts A's literal record is returned, and asserts B is rejected.
- [ ] Run the single test and confirm failure because `tool_contracts` and `_function_tools` do not exist.
- [ ] Add the minimal context field and Function Tool builder using the frozen tool definition; do not invoke tools in `PathAgent.run()`.
- [ ] Run the focused test and confirm it passes.

### Task 2: Prove the Deep Agents tool loop and virtual-file projection

**Files:**
- Modify: `tests/test_agents.py`
- Modify: `backend/agentic_cm/path_agent.py`

**Interfaces:**
- Consumes: `_function_tools`, `_context_files`, `PathAgentResult`.
- Produces: a graph invocation whose first user message is a short task and whose `files` contain only approved `/skills`, `/case`, `/knowledge`, and `/evidence` paths.

- [ ] Add a failing scripted-model test whose first AI message calls `lookup_material_master` and whose second calls `PathAgentResult`; assert the returned recommendation incorporates the tool result and the captured request contains the required files rather than a JSON payload.
- [ ] Add failing assertions for `bundle.json`, optional HumanProposal/previous-revision files, the `Manifest` Skill label, and correct read/write permission rules.
- [ ] Run the focused tests and confirm failures identify the old one-shot payload and absent Function Tool.
- [ ] Implement `_context_files`, bundle projection, concise user task, Function Tool registration, correct permissions, and safe tool-call trace extraction.
- [ ] Run all `deep_agent` and context tests and confirm they pass.

### Task 3: Move tool execution and validation to their correct boundaries

**Files:**
- Modify: `tests/test_agents.py`
- Modify: `backend/agentic_cm/path_agent.py`

**Interfaces:**
- Consumes: frozen Skill payloads from `CapabilityResolution`.
- Produces: `PathAgent.run()` that validates tool coverage and passes contracts without emitting precomputed `tool_results`; `DeepAgentPathAdapter` that performs only schema/runtime validation.

- [ ] Add a failing service-level test proving no `tools.query` precomputation occurs and a missing authorized record fails before model invocation.
- [ ] Add a failing adapter test proving semantic validation happens once at the `PathAgent` boundary while malformed structured output still fails in the Adapter.
- [ ] Remove `tool_results` and `prompt_payload`; add frozen `tool_contracts`; retain record conflict and coverage checks.
- [ ] Move `_require_chinese` and `_validate_result_against_context` calls out of Adapter and keep them after `adapter.generate()` in `PathAgent.run()`.
- [ ] Run `tests/test_agents.py` and confirm all tests pass.

### Task 4: Scope provider profiles and reuse graphs safely

**Files:**
- Modify: `tests/test_agents.py`
- Modify: `tests/test_adapter_environment.py`
- Modify: `backend/agentic_cm/path_agent.py`

**Interfaces:**
- Produces: Path-specific model wrappers reporting `ls_provider="agentic-cm"`; graph cache keyed by tool name, description, and input key.

- [ ] Add a failing test proving importing `path_agent` does not add Path exclusions to provider-wide `openai` and both deterministic/production models resolve `agentic-cm`.
- [ ] Add a failing test invoking the Adapter twice with the same tool schema and different records, asserting one compiled graph and isolated per-invocation results.
- [ ] Implement the Path-specific ChatOpenAI subclass/provider identity and graph cache without storing Case data on the graph or adapter.
- [ ] Run adapter/environment tests and confirm they pass.

### Task 5: Rewrite capability Skills and tool names

**Files:**
- Modify: `capabilities/builtin/skills/material-substitution-analysis/SKILL.md`
- Modify: `capabilities/builtin/skills/material-substitution-analysis/tools.json`
- Modify: the five remaining built-in `SKILL.md` files
- Modify: `tests/test_capabilities.py`

**Interfaces:**
- Produces: valid callable tool names and method-oriented Chinese Skill instructions.

- [ ] Add capability behavior tests that load the real registry and assert Function Tool names are valid and the material entrypoint expands to the same three members.
- [ ] Run the tests and confirm failure on the current `mock.*` names.
- [ ] Rename the three tools, rewrite all six Skills, and preserve the existing frozen record values.
- [ ] Run capability tests and `PYTHONPATH=backend .venv/bin/python -m agentic_cm.capabilities validate`.

### Task 6: Full verification

**Files:**
- Review all modified production and test files.

- [ ] Run `.venv/bin/python -m pytest`.
- [ ] Run `PYTHONPATH=backend .venv/bin/python -m agentic_cm.capabilities validate`.
- [ ] From `frontend/`, run `npm run lint`, `npm run build`, and `npm test`.
- [ ] Inspect `git status --short`, `git diff --stat`, and the full diff; verify no ignored design record, credentials, generated cache, commit, or push entered the product change.
