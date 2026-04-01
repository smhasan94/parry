# Parry — Claude Code Context

## What this is
AI Agent Runtime Security platform. Sits between AI agents and the LLMs they call.
Detects prompt injection, tool misuse, and anomalous behavior in real time.
B2B SaaS — Python SDK + detection engine + web dashboard.

## Repo layout
```
parry/
├── backend/          # FastAPI app (main API + proxy + detection engine)
│   ├── app/
│   │   ├── main.py           # FastAPI entrypoint
│   │   ├── api/              # Route handlers (v1/)
│   │   ├── core/             # Config, settings, logging
│   │   ├── db/               # SQLAlchemy models + migrations (Alembic)
│   │   ├── detection/        # Detection engine (rules, classifiers, policies)
│   │   ├── proxy/            # LLM call interceptor logic
│   │   ├── services/         # Business logic layer
│   │   ├── schemas/          # Pydantic request/response schemas
│   │   └── workers/          # Celery tasks
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml
├── sdk/              # pip install parry — Python SDK
│   ├── parry/
│   │   ├── __init__.py
│   │   ├── client.py         # Main SDK client
│   │   ├── wrappers/         # openai.py, anthropic.py, langchain.py
│   │   └── interceptor.py    # Core call interception logic
│   ├── tests/
│   └── pyproject.toml
├── dashboard/        # React + Tailwind frontend
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   ├── hooks/
│   │   └── lib/
│   └── package.json
├── docs/             # Architecture, ADRs, API specs
├── docker-compose.yml
├── docker-compose.prod.yml
└── CLAUDE.md
```

## Stack
- **Backend:** FastAPI, Python 3.12, SQLAlchemy 2.x (async), Alembic, Pydantic v2
- **Database:** PostgreSQL 16 + TimescaleDB (hypertable for agent_events)
- **Cache/Queue:** Redis 7, Celery 5
- **Detection:** spaCy, scikit-learn, Anthropic API (claude-sonnet-4-6 for LLM fallback)
- **Auth:** Clerk (JWT verification middleware)
- **Billing:** Stripe (metered billing per agent)
- **Dashboard:** React 18, TypeScript, Tailwind CSS, shadcn/ui, TanStack Query
- **Infra:** Docker Compose (dev), Render (prod)
- **Testing:** pytest + pytest-asyncio (backend), Vitest (frontend)
- **Linting:** Ruff + mypy (backend), ESLint + Prettier (frontend)

## Key commands

### Backend
```bash
cd backend
uv run uvicorn app.main:app --reload          # dev server
uv run pytest                                  # run all tests
uv run pytest tests/detection/ -v             # run detection tests only
uv run mypy app/                              # type check
uv run ruff check app/ && uv run ruff format app/  # lint + format
uv run alembic upgrade head                   # apply migrations
uv run alembic revision --autogenerate -m "description"  # new migration
uv run celery -A app.workers.celery_app worker --loglevel=info  # worker
```

### SDK
```bash
cd sdk
uv run pytest
uv run python -m parry.examples.basic    # smoke test
```

### Dashboard
```bash
cd dashboard
npm run dev       # dev server :5173
npm run build     # production build
npm run lint
npm test          # vitest
```

### Docker
```bash
docker compose up -d                          # start all services
docker compose up -d --build backend          # rebuild backend only
docker compose logs -f backend                # tail logs
docker compose exec backend uv run alembic upgrade head
```

## Code conventions

### Python
- Use `uv` not `pip` or `poetry`
- Async everywhere — `async def` for all route handlers and service methods
- Pydantic v2 models for all request/response schemas (use `model_validate`, not `.parse_obj`)
- SQLAlchemy 2.x style — `select()` not `session.query()`
- Type annotations required on all functions
- Ruff for formatting (line length 100), isort via Ruff
- Never use `print()` — use `structlog` logger: `log = structlog.get_logger()`
- Raise `HTTPException` in route handlers only; raise domain exceptions in services

### Database / models
- All models extend `Base` from `app.db.base`
- Use `uuid` PKs (PostgreSQL `gen_random_uuid()`)
- `created_at` / `updated_at` on every model (auto-set via SQLAlchemy `onupdate`)
- Agent events table is a TimescaleDB hypertable — never do full table scans on it; always filter by `agent_id` and time range
- Use `JSONB` for flexible metadata fields, not text

### API design
- All routes under `/api/v1/`
- Auth via `Depends(get_current_org)` — injects `Org` object into route
- Pagination: cursor-based using `created_at` + `id`, not offset
- Return 202 Accepted for async jobs, not 200
- Error responses use `{"detail": "message", "code": "ERROR_CODE"}` format

### Detection engine
- Each detector is a class implementing `BaseDetector` protocol (see `detection/base.py`)
- Detectors are stateless — all context passed in, nothing stored on instance
- Rule-based detectors run sync; ML/LLM detectors run async
- Detection result always returns `DetectionResult(triggered: bool, severity: Severity, reason: str, detector: str)`
- LLM fallback (Claude API) only called when rule-based score is ambiguous (0.4–0.7 confidence)
- Never log raw prompt content at INFO level — only at DEBUG, and only first 200 chars

### SDK
- Zero required config beyond API key — works with 2 lines of code
- Never block the calling thread — all backend calls are async/fire-and-forget by default
- Fail open: if Parry backend is unreachable, SDK logs a warning and passes the call through
- Sensitive data stripping happens client-side in SDK before sending to backend

## Domain concepts
- **Agent** — a named, persistent AI process with a stable `agent_id`. Has a behavioral baseline.
- **Session** — one conversation/run of an agent. Groups related events.
- **Event** — a single LLM call: prompt + response + metadata. The atomic unit.
- **Policy** — org-defined rules: allowed tools, allowed domains, max token budgets, forbidden patterns.
- **Detection** — a result from running an event through the detection engine.
- **Incident** — one or more related detections grouped by the system; requires human review.
- **Org** — top-level tenant. Has API keys, agents, policies, billing.

## Environment variables
See `.env.example`. Never hardcode secrets. Always use `app.core.config.settings`.
Critical ones: `DATABASE_URL`, `REDIS_URL`, `ANTHROPIC_API_KEY`, `CLERK_SECRET_KEY`, `STRIPE_SECRET_KEY`, `SENTINEL_API_KEY` (internal service-to-service).

## Testing approach
- Unit tests: pure functions, mock all I/O
- Integration tests: use `pytest-asyncio` + test database (separate DB spun up by `conftest.py`)
- Detection tests: always test both trigger and non-trigger cases for every detector
- Never mock the detection engine in integration tests — run real detectors against fixture events
- Fixtures live in `tests/fixtures/` as JSON files (sample prompts, responses, events)

## What NOT to do
- Don't use `session.commit()` inside a service — let the route handler manage transactions
- Don't call the Anthropic API synchronously anywhere
- Don't store raw user prompts in plain text logs
- Don't add new pip dependencies without updating `pyproject.toml` and checking license
- Don't bypass the `BaseDetector` protocol — all detectors must implement it
- Don't use `.env` files in tests — use `pytest` fixtures to override settings

## Reference docs
- Architecture deep-dive: `docs/architecture.md`
- Detection engine design: `docs/detection-engine.md`
- API specification: `docs/api-spec.md`
- Database schema: `docs/schema.md`
- ADRs (Architecture Decision Records): `docs/adr/`
