# Repository Guidelines

## Project Structure & Module Organization
- `backend/app/`: FastAPI app, CLI, and core services (`graph/`, `graphrag/`, `wiki/`, `incremental/`, `repo_scanner/`).
- `backend/app/api/`: HTTP routes (`ask`, `wiki`, `graph`, `repos`, `files`, `runs`, `settings`).
- `backend/app/db/`: SQLAlchemy schema, repositories, and persistence helpers.
- `frontend/src/`: React + TypeScript UI (`pages/`, `api/`, `graph/`, `wiki/`, `ask/`, `styles/`).
- `tests/backend/`: pytest suite for backend services, CLI, and API behavior.
- `docs/`: design and architecture notes. `scripts/`: local dev utilities (for example `kill_ports.py`).

## Build, Test, and Development Commands
- `make install`: install backend (`pip install -e ".[dev]"`) and frontend deps.
- `make dev` (or `make start`): run FastAPI on `127.0.0.1:8000` and Vite on `127.0.0.1:5173`.
- `make backend` / `make frontend`: run one side only.
- `make test`: run backend tests via `pytest -q`.
- `make lint`: run `ruff check backend tests` and frontend `eslint`.
- `make build`: type-check and build frontend (`tsc -b && vite build`).
- `make kill`: stop processes on dev ports.

## Coding Style & Naming Conventions
- Python: target `py312`, max line length 100, lint with Ruff. Use `snake_case` for modules/functions, `PascalCase` for classes.
- TypeScript/React: ESLint + TypeScript checks; components in `PascalCase` files (for example `GraphPage.tsx`), hooks prefixed with `use` (for example `useRepoGraph.ts`).
- Keep modules focused by domain (graph, wiki, ask, db) and colocate helpers with the feature directory.

## Python Typing Guidelines
- Use `mypy` for gradual Python type checking; run `make typecheck` when changing typed backend paths.
- Add explicit parameter and return types for new public service, repository, API helper, CLI helper, and shared utility functions.
- Prefer domain dataclasses, Pydantic models, `TypedDict`, or `Protocol` over broad `dict[str, Any]` when values cross module boundaries.
- Keep `Any` at integration edges only, such as LLM JSON payloads, SQLAlchemy JSON columns, tree-sitter parser output, and third-party SDK responses.
- Use `Protocol` for injectable services in tests when it avoids coupling to concrete implementations.
- Avoid `cast()` unless the invariant is checked nearby; add a short comment when the reason is not obvious.
- Tighten legacy modules incrementally rather than making unrelated typing-only rewrites during feature work.

## Architecture & Responsibility Boundaries
- Apply responsibility separation across the whole project, not only to a specific file or interface. Each module should have one clear reason to change and should avoid mixing transport, orchestration, domain logic, persistence, formatting, and configuration concerns.
- Keep entrypoints thin across all transports and runtimes. CLI commands, MCP handlers, FastAPI routes, frontend API wrappers, scripts, and build hooks should parse inputs, call focused services, format outputs, and handle transport-specific errors only.
- Put business workflows in focused service modules under `backend/app/services/`; keep persistence in `backend/app/db/` repositories; keep HTTP schemas, MCP tool schemas, CLI options, and frontend types at their respective boundaries.
- Extract shared behavior instead of duplicating it across interfaces. Repo selector resolution, JSON/dataclass serialization, graph status summaries, command/tool/API payload shaping, and validation helpers should live in reusable modules when used by more than one boundary.
- Split large modules before adding new feature families. Prefer domain-oriented packages and small files over growing entrypoints, service modules, API routes, or frontend components past a coherent responsibility.
- Keep protocol and framework concerns separate from domain concerns. JSON-RPC framing, HTTP request handling, Click command wiring, React state/rendering, and build tooling should not directly own graph/wiki/GraphRAG business rules.
- Add or update tests at the boundary being changed: service tests for shared workflows, repository tests for persistence, CLI tests for command wiring/output, MCP tests for tool schemas and JSON-RPC behavior, API tests for HTTP routes, and frontend tests/build checks for UI behavior.

## Testing Guidelines
- Framework: `pytest` with tests under `tests/backend/` and files named `test_*.py`.
- Prefer focused unit tests per service/module, with API/CLI coverage for user-facing flows.
- Run `make test` before opening a PR; add regression tests for bug fixes.

## Commit & Pull Request Guidelines
- Follow Conventional Commit style seen in history: `feat(scope): ...`, `fix(scope): ...`, `refactor(scope): ...`.
- Keep commit scope specific (`backend`, `frontend`, `wiki`, `graphrag`, etc.).
- PRs should include: purpose, key changes, test/lint results, linked issues, and screenshots/GIFs for UI changes.

## Environment & Configuration Tips
- Python 3.12 is required (`make` enforces it).
- Copy `.env.example` to configure local settings and LLM provider variables.
- Use `codewiki` CLI for local workflows, e.g. `codewiki analyze .` and `codewiki ask "..."`.

## Execution boundaries and completion

- Use the Makefile's Python 3.12 checks before ambient Python commands; `make install` creates/checks `.venv`. CI also uses Node 20 and `npm --prefix frontend ci`. Preserve `frontend/package-lock.json`. `make build` builds only the frontend; Python packaging invokes a frontend build hook and is a separate check when packaging changes.
- `make kill` and `make restart` terminate listeners on the configured ports. Check ownership with `make check-ports` and prefer alternate ports; do not kill an unrelated process as a setup shortcut. Local development does not require installing the bundled skill or editing a harness's MCP configuration.
- Source analysis and Lite Mode can be tested with a disposable repository/index. Wiki generation, embedding, and Q&A may transmit source to an LLM provider; use fixtures/mocks for unit checks and obtain task authorization before sending private code or spending on live provider calls. Keep secrets and stored repository content out of logs.
- Begin with `git status --short`, preserve unrelated work, and finish authorized changes through the relevant test/lint/typecheck/build gates and repairs. Routine reversible choices can proceed directly; ask only about material missing decisions or external actions. If a dependency, database, or provider prerequisite is blocked, give the exact failure and continue independent work.
- Prose-only edits need source/link inspection and `git diff --check`; keep the existing `make test` pre-PR requirement visible and report any explicit validation exemption. Close with changed paths, actual check outcomes, and unverified integration behavior. Publishing packages, deployments, shared-database changes, and global skill/MCP installation need explicit authorization.
