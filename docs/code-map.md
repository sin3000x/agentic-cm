# Code map

This is the live map of the demo. Read this before the longer docs.

## Layout

- `backend/agentic_cm/` — single-process Python control plane
- `capabilities/builtin/` — versioned Policy, Skill, Knowledge, and Case Type catalogs
- `.agentic-cm/capabilities/` — optional local overrides (gitignored)
- `frontend/app/` — React workbench
- `tests/` — backend pytest; `frontend/tests/` — SSR smoke tests

## One type per artifact

Defined in `backend/agentic_cm/domain.py` and persisted as JSON on `Case`:

| Concept | Type | Notes |
|---|---|---|
| Frozen capability pointer | `AssetRef` | `{id, version, digest}` |
| Path plan | `Manifest` / `ManifestPath` | Skills live only as `skill_selections` |
| Exploration instance | `PathAttempt` | Holds `SolutionRevision` or none |
| Path Agent output | `PathAgentResult` | LLM schema; `SolutionRevision` adds revision + `generated_by` |
| Synthesis output | `SynthesisResult` | LLM schema; `SynthesisReport` adds revision + `generated_by` |
| Human node | `CommitmentNode` | Status is the DAG |
| Final call | `OwnerDecision` | |

Do not add parallel dataclasses, prompt-context clones, or a flattened `ManifestPath.skills` field. If a caller needs every Skill ref, call `path.skill_refs()`.

Registry identity (`capabilities.AssetRef`) also has `kind` and `source`. Convert to `domain.AssetRef` once when freezing a Manifest.

## Where behavior lives

| File | Job |
|---|---|
| `domain.py` | Canonical models |
| `repository.py` | SQLite Case JSON + events + agent traces |
| `service.py` | Lifecycle, views, inbox |
| `capabilities.py` | Load, validate, resolve by digest |
| `orchestrator.py` | Planner draft → frozen Manifest |
| `path_agent.py` | Frozen Manifest → `SolutionRevision` |
| `synthesis_agent.py` | Terminal PathAttempts → `SynthesisReport` |
| `agent_runtime.py` | Shared LLM call, retry, `AgentError` |
| `api.py` | HTTP; exception handlers map domain errors |

Invalid persisted Case JSON is treated as empty and `ensure_demo_data()` reseeds the demo. There is no legacy decoder.

## Lifecycle

```
INTAKE → MANIFEST_REVIEW → PATH_EXPLORATION → PROFESSIONAL_COMMITMENT → FINAL_REVIEW
```

Agents propose. Humans approve commitments and the Owner decision. The platform owns Case state.
