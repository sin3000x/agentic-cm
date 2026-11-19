# Path Agent Deep Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Path Agent's hand-written one-shot model request with one constrained Deep Agents runtime while preserving all current domain and API behavior.

**Architecture:** Keep `PathAgent` as the capability-resolution and business-validation boundary. Replace the two model adapters with one `DeepAgentPathAdapter` that projects only Manifest-authorized skills into an in-memory backend, invokes a Deep Agents graph, and returns the existing `PathAgentResult`; deterministic mode injects a scripted chat model into the same adapter.

**Tech Stack:** Python 3.11+, Deep Agents 0.7.x, LangChain OpenAI 1.x, Pydantic 2, pytest

**Spec:** `docs/superpowers/specs/2026-08-31-path-agent-deepagents-design.md`

## Global Constraints

- Keep HTTP API, Manifest, Policy, Commitment DAG, `PathAgentResult`, and `SolutionRevision` contracts unchanged.
- Add only `deepagents>=0.7.11,<0.8` and the compatible `langchain-openai>=1,<2` direct dependencies.
- Do not add Explore, `ask_human`, persistence checkpoints, subagents, shell access, writable files, or dynamic `tools.json` registration.
- Deep Agents may see only the skills already resolved into `PathAgentContext.execution_skills`.
- Keep current server-side Chinese, option-whitelist, recommendation, and role-report validation fail closed.
- Do not commit or push without explicit user authorization.

---

### Task 1: Constrained Deep Agents adapter

**Files:**
- Modify: `pyproject.toml`
- Modify: `backend/agentic_cm/path_agent.py`
- Modify: `tests/test_agents.py`

**Interfaces:**
- Consumes: `PathAgentContext.execution_skills`, `PathAgentResult`, `AgentTraceSink`.
- Produces: `DeepAgentPathAdapter(model: BaseChatModel, *, profile: str, delay_seconds: float = 0.0)` implementing `PathAgentAdapter.generate(context, trace) -> PathAgentResult`.
- Produces: `_skill_files(context: PathAgentContext) -> dict[str, str]` containing only `/skills/<id>/SKILL.md` files.

- [ ] **Step 1: Add failing tests for authorized Skill projection and graph output**

  Add tests that construct a real `PathAgentContext` containing two authorized Skill payloads, assert the adapter's in-memory backend contains exactly their standard `SKILL.md` paths, and invoke a scripted LangChain chat model through the real Deep Agents graph to obtain a `PathAgentResult`. The observable break is either exposing an unauthorized Skill or bypassing the Deep Agents structured-response path.

- [ ] **Step 2: Run the focused tests and verify RED**

  Run: `.venv/bin/python -m pytest tests/test_agents.py -k 'deep_agent' -v`

  Expected: collection/import failure because `DeepAgentPathAdapter` and its Skill projection do not exist.

- [ ] **Step 3: Add dependencies and implement the smallest adapter**

  Add the two dependencies, install the editable project, and replace `DeterministicPathAgentAdapter` plus `OpenAICompatiblePathAgentAdapter` with a single adapter. Its `generate()` must:

  ```python
  files = _skill_files(context)
  backend = StateBackend(Runtime(state={"files": files}))
  agent = create_deep_agent(
      model=self._model,
      system_prompt=_PATH_AGENT_SYSTEM_PROMPT,
      skills=["/skills/"],
      backend=backend,
      response_format=PathAgentResult,
      # disable the default general-purpose subagent and mutating tools
  )
  state = await agent.ainvoke(
      {"messages": [{"role": "user", "content": json.dumps(context.prompt_payload(), ensure_ascii=False)}]},
      config={"recursion_limit": _PATH_AGENT_RECURSION_LIMIT},
  )
  result = PathAgentResult.model_validate(state["structured_response"])
  ```

  Construct each Skill file from literal YAML frontmatter (`name`, `description`) plus `instructions_markdown`; reject missing identifiers or instructions rather than scanning the filesystem. Trace only runtime start, projected Skill refs, completion summary, and safe failure metadata.

- [ ] **Step 4: Run focused tests and verify GREEN**

  Run: `.venv/bin/python -m pytest tests/test_agents.py -k 'deep_agent' -v`

  Expected: all selected tests pass with no external model request.

- [ ] **Step 5: Inspect the diff without committing**

  Run: `git diff -- pyproject.toml backend/agentic_cm/path_agent.py tests/test_agents.py`

  Confirm the adapter does not add Explore, Inbox, checkpoint, subagent, shell, or writable-file behavior.

### Task 2: Environment factory and deterministic model

**Files:**
- Modify: `backend/agentic_cm/path_agent.py`
- Modify: `tests/test_adapter_environment.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_lifecycle.py`

**Interfaces:**
- Consumes: existing `agent_adapter_from_environment()`, `agent_llm_config_from_environment("path")`, timeout, API header/prefix, max-output-token, and deterministic-delay settings.
- Produces: `path_agent_from_environment() -> DeepAgentPathAdapter` for both `deterministic` and `openai-compatible` modes.
- Produces: a private scripted `BaseChatModel` used only for deterministic local execution, returning the existing deterministic Chinese proposal through the graph's structured output contract.

- [ ] **Step 1: Rewrite environment tests first**

  Assert both adapter modes return `DeepAgentPathAdapter`; OpenAI-compatible mode contains a `ChatOpenAI` configured with the existing model/base URL/timeout/auth/thinking values, while deterministic mode contains the scripted model and preserves `AGENTIC_CM_DETERMINISTIC_DELAY_SECONDS`. The observable break is selecting a legacy adapter or dropping current configuration.

- [ ] **Step 2: Run environment tests and verify RED**

  Run: `.venv/bin/python -m pytest tests/test_adapter_environment.py -v`

  Expected: failures because the factory still returns the legacy adapter classes.

- [ ] **Step 3: Implement the unified factory**

  Build `ChatOpenAI` using current environment values and `default_headers` for the configurable authentication header. Map current thinking settings through `extra_body`; do not introduce new environment variables. In deterministic mode, construct the scripted model and inject it into `DeepAgentPathAdapter`. Update fixtures and lifecycle test doubles to use the unified adapter or the unchanged `PathAgentAdapter` protocol.

- [ ] **Step 4: Run environment and lifecycle tests and verify GREEN**

  Run: `.venv/bin/python -m pytest tests/test_adapter_environment.py tests/test_lifecycle.py -v`

  Expected: all tests pass.

- [ ] **Step 5: Inspect the diff without committing**

  Run: `git diff -- backend/agentic_cm/path_agent.py tests/test_adapter_environment.py tests/conftest.py tests/test_lifecycle.py`

  Confirm that Orchestrator and Synthesis factories are untouched.

### Task 3: Preserve domain failures and complete verification

**Files:**
- Modify: `tests/test_agents.py`
- Modify only if a failing behavior test requires it: `backend/agentic_cm/path_agent.py`

**Interfaces:**
- Consumes: `DeepAgentPathAdapter.generate`, existing `_require_chinese`, `_validate_result_against_context`, and AgentRun persistence in `CaseService`.
- Produces: unchanged fail-closed behavior and auditable runtime failure traces.

- [ ] **Step 1: Add failing boundary tests**

  Add focused cases for missing `structured_response` mapping to `AgentOutputError`, graph invocation failure mapping to `AgentExecutionError`, and a graph result that invents an option being rejected before `SolutionRevision` persistence. Assert the real Case state and trace outcome, not private call counts.

- [ ] **Step 2: Run the boundary tests and verify RED**

  Run: `.venv/bin/python -m pytest tests/test_agents.py -k 'deep_agent or rejects_invented' -v`

  Expected: the new failure-path tests fail until error mapping and post-graph semantic validation are complete.

- [ ] **Step 3: Add only the missing mappings and validation calls**

  Wrap graph execution errors as `AgentExecutionError`; treat absent/malformed structured output or recursion exhaustion as `AgentOutputError`; call `_require_chinese(result)` and `_validate_result_against_context(result, context)` once after model validation. Do not add retries beyond the graph loop.

- [ ] **Step 4: Run all backend checks**

  Run:

  ```bash
  .venv/bin/python -m pytest
  PYTHONPATH=backend .venv/bin/python -m agentic_cm.capabilities validate
  ```

  Expected: all backend tests pass and capability validation exits zero.

- [ ] **Step 5: Run frontend regression checks**

  Run from `frontend/`:

  ```bash
  npm run lint
  npm run build
  npm test
  ```

  Expected: lint, build, and all frontend tests exit zero.

- [ ] **Step 6: Final scope and mutation review without committing**

  Run: `git status --short && git diff --stat && git diff`

  Verify that removing Skill projection, returning a malformed structured result, or restoring a legacy adapter would fail at least one focused test; confirm no API/frontend/domain schema change and no credentials or hidden reasoning in traces.
