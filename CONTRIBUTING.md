# Contributing to Parry

Thanks for taking the time to look at the codebase. This guide
covers what you need to get a working development environment, the
conventions we follow, and what to do before opening a pull
request.

For an architectural overview of the codebase, read `CLAUDE.md` at
the repo root — it's the same file our AI development agents read,
and it covers stack, layout, and house rules.

## Repo layout (short version)

```
parry/
├── backend/    # FastAPI + detection engine + Celery workers
├── sdk/        # Python SDK (pip install parry)
├── sdk-ts/     # TypeScript SDK (@parry/sdk)
├── sdk-go/     # Go SDK
├── dashboard/  # React + TypeScript + Tailwind
├── landing/    # Astro marketing site
├── docs/       # Architecture, ADRs, API specs, ops guides
└── CLAUDE.md   # House rules (read this first)
```

## Local setup

You'll need Docker, [`uv`](https://github.com/astral-sh/uv) for
Python, Node 20+, and Go 1.25+ if you're touching `sdk-go`.

```bash
# 1. Bring up Postgres + Redis.
docker compose up -d postgres redis

# 2. Install Python deps (backend + Python SDK use uv, not pip).
cd backend && uv sync && cd ..
cd sdk && uv sync && cd ..

# 3. Apply DB migrations.
cd backend && uv run alembic upgrade head && cd ..

# 4. Install JS deps.
cd dashboard && npm install && cd ..
cd sdk-ts && npm install && cd ..

# 5. Copy env template and fill secrets you need.
cp .env.example .env
```

Run things:

```bash
# Backend API (auto-reload).
cd backend && uv run uvicorn app.main:app --reload

# Celery worker (separate terminal).
cd backend && uv run celery -A app.workers.celery_app worker --loglevel=info

# Dashboard (separate terminal, :5173).
cd dashboard && npm run dev
```

Without an `ANTHROPIC_API_KEY`, the LLM fallback detector logs a
warning and stays disabled — every other detector still works.
Without `CLERK_SECRET_KEY`, auth runs in demo-org mode for local
dev. The startup log tells you what's degraded.

## Running tests

| What | Command |
| --- | --- |
| Backend unit | `cd backend && uv run pytest tests/ --ignore=tests/e2e` |
| Backend e2e | `cd backend && uv run pytest tests/e2e/` (needs Postgres) |
| Python SDK | `cd sdk && uv run pytest` |
| TS SDK | `cd sdk-ts && npm test` |
| Go SDK | `cd sdk-go && go test ./...` |
| Dashboard | `cd dashboard && npm test` |
| Lint (backend) | `cd backend && uv run ruff check app/` |
| Type check (backend) | `cd backend && uv run mypy app/` |
| Lint (dashboard) | `cd dashboard && npm run lint` |

CI runs all of these on every PR. Match those commands locally
before pushing — it's faster than waiting for the build.

## Code conventions

The full set lives in `CLAUDE.md`. The ones you'll trip over first:

- **Python:** `uv` not pip; async everywhere; SQLAlchemy 2.x style
  (`select()`, not `session.query()`); Pydantic v2; no `print()`,
  use `structlog`; line length 100.
- **TypeScript:** strict mode on; no `any` in non-test code (the
  test override exists for legitimate mock shapes only).
- **Detection engine:** every detector implements `BaseDetector`;
  rule-based detectors stay synchronous, ML/LLM detectors are
  async; never log raw prompt content above DEBUG.
- **Database:** all models extend `Base`; UUID PKs; `created_at` /
  `updated_at` on every row; the `agent_events` table is a
  TimescaleDB hypertable — always filter by `agent_id` and a time
  range, never full-scan it.
- **API:** routes under `/api/v1/`; auth via
  `Depends(get_current_org)`; cursor pagination on `created_at + id`;
  202 for async jobs; error format
  `{"detail": "...", "code": "..."}`.
- **SDKs:** zero required config beyond an API key; always fail
  open if the backend is unreachable; strip sensitive data before
  it leaves the SDK.

## Commits and PRs

- One logical change per commit. Don't bundle "fix typo" with a
  feature PR — split it.
- Conventional-ish prefixes (`feat:`, `fix:`, `chore:`, `docs:`,
  `test:`, `ci:`, `refactor:`) help the changelog generator.
- Commit body: 2–3 sentences max, focused on **why** and any
  non-obvious tradeoff. Don't restate the diff.
- PRs to `main`. We use squash merges, so PR titles become commit
  messages — write them carefully.
- Link the PR description to relevant `docs/plans/*` entries if
  the work is part of a planned feature.

## Tests are mandatory for new behaviour

- Bug fix? Reproduce in a failing test first, then fix.
- New detector? Add at least one `triggered` and one
  `not-triggered` fixture-driven test. Detection tests must run
  the **real** pipeline; never mock the detection engine in
  integration tests.
- New API route? At least one happy-path test plus one auth/role
  failure test.
- Touching the schema? Add an Alembic revision and verify it
  applies cleanly against a fresh DB and via `downgrade`.

## What's hard to get past review

- Adding `print()` statements (use `structlog`).
- Swallowing exceptions silently in services.
- New pip / npm deps without a license check and a one-line
  rationale in the PR description.
- Calling Anthropic API synchronously anywhere.
- Storing raw prompts in plain-text logs.
- `--no-verify` on commits, `git push --force` on `main`.

## Reporting security issues

Please don't open public issues for security findings — see
`SECURITY.md`.

## Where to ask questions

- **GitHub Discussions** for design questions and proposals.
- **Issues** for bugs and concrete feature requests.
- **security@parry.dev** for vulnerabilities.

Welcome aboard.
