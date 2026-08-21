# Repository Guidelines

## Project Structure & Module Organization

`backend/agentic_cm/` is the Python modular monolith: domain models, SQLite persistence, orchestration, capability loading, services, and FastAPI routes. `tests/` contains backend integration and domain tests. `frontend/app/` holds React/TypeScript routes and shared UI, `frontend/tests/` contains server-rendered HTML tests, and `frontend/public/` stores static assets. Versioned built-in Policy, Skill, and Knowledge definitions live in `capabilities/builtin/`; use `examples/local-capabilities/` as the template for ignored local overrides. Architecture and acceptance decisions are documented in `docs/`.

## Build, Test, and Development Commands

- `python3 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'` installs the backend and test dependencies.
- `.venv/bin/python -m uvicorn agentic_cm.api:app --app-dir backend --reload --port 8000` starts the API and Swagger UI.
- `.venv/bin/python -m pytest` runs the backend suite.
- `PYTHONPATH=backend .venv/bin/python -m agentic_cm.capabilities validate` validates built-in and local capability contracts.
- From `frontend/`, run `npm ci`, `npm run dev`, `npm run lint`, `npm run build`, or `npm test`. The test command builds first, then exercises rendered routes with Node's test runner.

## Coding Style & Naming Conventions

Use four-space indentation, type hints, `snake_case` functions/modules, and `PascalCase` classes in Python. Keep domain transitions in services/domain objects rather than API handlers. TypeScript runs in strict mode; use `PascalCase` components, `camelCase` values, and route files following the existing vinext layout (`app/cases/[id]/page.tsx`). ESLint is the frontend formatter-quality gate; match nearby formatting and avoid unrelated mechanical rewrites. Capability directories use kebab-case names and require standard `SKILL.md` metadata.

## Testing Guidelines

Name Python tests `test_<behavior>` in `tests/test_*.py`. Add tests for authorization boundaries, state transitions, persistence, and fail-closed capability resolution. Frontend tests use `*.test.mjs` and should verify both rendered output and critical source-level interaction contracts. There is no enforced coverage percentage; every behavior change should include a focused regression test.

## Commit & Pull Request Guidelines

Recent commits use short imperative subjects, sometimes with Conventional Commit prefixes such as `feat:`, `fix:`, `refactor:`, or `docs:`. Keep each commit scoped to one concern. Pull requests should explain the user-visible change, affected architecture or capability contracts, and validation performed; link relevant issues and include screenshots for UI changes. Never commit `.env`, API keys, local `.agentic-cm/` overrides, SQLite data, or generated frontend output.

## Architecture & Safety

Preserve the governance boundary: Agents analyze and propose; humans approve business commitments; the platform owns state, dependencies, and audit history. Treat client-supplied demo identities as untrusted outside local demonstrations.
