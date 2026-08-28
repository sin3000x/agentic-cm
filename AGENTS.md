# Repository Guidelines

## Project Structure

`backend/agentic_cm/` is the Python control plane. Canonical models live in `domain.py`; persistence is SQLite JSON in `repository.py`; transitions live in `service.py`. `capabilities/builtin/` holds Policy, Skill, Knowledge, and Case Type catalogs. `frontend/app/` is the React workbench. See `docs/code-map.md` before adding types or files.

## Commands

- `python3 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'`
- `.venv/bin/python -m uvicorn agentic_cm.api:app --app-dir backend --reload --port 8000`
- `.venv/bin/python -m pytest`
- `PYTHONPATH=backend .venv/bin/python -m agentic_cm.capabilities validate`
- From `frontend/`: `npm ci`, `npm run dev`, `npm run lint`, `npm run build`, `npm test`

## Style

Python: four-space indent, type hints, `snake_case` functions, `PascalCase` models. TypeScript: strict, `PascalCase` components, `camelCase` values. Do not introduce DTO/mapper layers or a second class for the same artifact.

## Testing

Name tests `test_<behavior>` in `tests/test_*.py`. Prefer one golden path, one authorization test, one fail-closed capability test, and agent output subset checks. Do not pin copy, CSS class names, or source-string presence.

## Safety

Agents analyze and propose; humans approve commitments; the platform owns state and audit history. Client-supplied demo identities are untrusted outside local demonstrations.
