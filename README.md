# Parry

Runtime security for AI agents. Detect prompt injection, tool misuse, and anomalous behavior before damage is done.

---

## What is Parry?

Parry is an inline security layer that sits between your AI agents and the LLMs they call. Every prompt and response is intercepted by a lightweight Python SDK, shipped to the detection engine, and checked against a pipeline of rule-based detectors and org-defined policies — in real time, without blocking your agent.

**Two lines to integrate:**

```python
import parry
parry.init(api_key="sk-parry-...")

from parry.wrappers.openai import ParryOpenAI
client = ParryOpenAI()  # drop-in replacement for openai.OpenAI()
```

From that point on, every LLM call your agent makes is monitored. Streaming and non-streaming responses are both supported.

---

## What it detects

| Detector | Description | Type |
|---|---|---|
| **Prompt Injection** | Instruction override, fake system prompts, model-specific token injection (`[INST]`, `<\|system\|>`) | Rule-based |
| **Jailbreak** | DAN, developer mode, uncensored mode, safety bypass patterns | Rule-based |
| **Tool Misuse** | Agent calling tools outside its org policy allowlist or on the blocklist | Policy-based |
| **Data Exfiltration** | Credit cards, SSNs, API keys, private keys, AWS credentials in model responses | Pattern matching |
| **Privilege Escalation** | Attempts to gain sudo/admin access, disable auth/logging, modify permissions | Rule-based |
| **Behavioral Anomaly** | Drift from agent's baseline — token count, latency, tool call frequency, unknown models | Statistical |
| **Policy Violations** | Domain restrictions, token budget caps, forbidden pattern breaches | Policy-based |

Each detector returns a `DetectionResult` with `triggered`, `severity` (critical/high/medium/low), `confidence` (0.0–1.0), and `reason`. Critical and high severity results block the call; medium flags for review; low logs only.

---

## Architecture

```
Your AI Agent
     │
     │  every LLM call (streaming + non-streaming)
     ▼
 Parry SDK (pip install parry)
     │  • PII stripped client-side (credit cards, SSNs, emails)
     │  • async fire-and-forget via background thread
     │  • fail-open: if backend unreachable, call passes through
     ▼
 FastAPI Backend (:8000)
     │
     ├── POST /api/v1/events/ingest  → persists event, returns 202
     │       │
     │       └── dispatches Celery task (async)
     │               │
     │               ├── 6 rule-based detectors (parallel, < 5ms)
     │               ├── Aggregator (scores 0.4–0.7 → LLM fallback)
     │               ├── Policy enforcer (org rules)
     │               └── Incident correlator (groups detections)
     │
     ├── PostgreSQL + TimescaleDB
     │       • agent_events hypertable (time-series, always filtered by agent_id + time)
     │       • orgs, agents, sessions, detections, incidents, policies, api_keys
     │
     ├── Redis + Celery
     │       • async detection pipeline
     │       • 3 retries, exponential backoff, 30s soft / 60s hard timeout
     │
     └── SSE stream → Dashboard
             • real-time event feed per agent
             • auth-scoped to org

 React Dashboard (:5173)
     ├── /dashboard      — org overview, agent grid, incident feed
     ├── /agents/:id     — event timeline, live SSE stream, model/latency stats
     ├── /incidents       — severity + status filters, acknowledge/resolve/dismiss
     ├── /policies        — create/edit allowed tools, blocked tools, token budgets
     └── /settings        — API key management (create/revoke), billing, SDK quick start
```

### Repo structure

```
parry/
├── backend/                      # FastAPI + Celery application
│   ├── app/
│   │   ├── main.py               # FastAPI entrypoint, CORS, exception handlers
│   │   ├── api/v1/               # Route handlers
│   │   │   ├── agents.py         # CRUD for agents
│   │   │   ├── api_keys.py       # Create, list, revoke API keys
│   │   │   ├── events.py         # Ingest, list, SSE stream
│   │   │   ├── incidents.py      # List, update status
│   │   │   └── policies.py       # CRUD for policies
│   │   ├── core/
│   │   │   ├── config.py         # Pydantic Settings (loads .env)
│   │   │   ├── dependencies.py   # Auth: get_current_org, get_org_from_sdk_key
│   │   │   ├── exceptions.py     # Domain exceptions (NotFound, Conflict, PolicyViolation)
│   │   │   └── logging.py        # structlog configuration
│   │   ├── db/
│   │   │   ├── base.py           # SQLAlchemy Base, UUID + timestamp mixins
│   │   │   ├── models.py         # All 8 domain models
│   │   │   └── session.py        # Async engine + session factory
│   │   ├── detection/
│   │   │   ├── base.py           # BaseDetector protocol, DetectionResult
│   │   │   ├── pipeline.py       # Orchestrator: parallel detect → aggregate → block?
│   │   │   ├── registry.py       # Detector registration + lookup
│   │   │   └── detectors/        # 6 detector implementations
│   │   ├── schemas/              # Pydantic v2 request/response models
│   │   ├── services/             # Business logic (no HTTP concerns)
│   │   │   ├── agent_service.py
│   │   │   ├── api_key_service.py
│   │   │   ├── detection_service.py  # Run pipeline + persist + create incidents
│   │   │   ├── event_service.py
│   │   │   ├── incident_service.py
│   │   │   └── policy_service.py
│   │   └── workers/
│   │       ├── celery_app.py     # Celery config
│   │       └── detection_task.py # Async detection task (retry + timeout)
│   ├── alembic/                  # Migrations (async engine)
│   ├── tests/                    # 48 tests
│   ├── Dockerfile
│   └── pyproject.toml
├── sdk/                          # pip install parry
│   ├── parry/
│   │   ├── __init__.py           # parry.init(), get_client()
│   │   ├── client.py             # ParryClient — fire-and-forget event sender
│   │   ├── interceptor.py        # PII stripping, intercept_completion(), TimingContext
│   │   └── wrappers/
│   │       ├── openai.py         # ParryOpenAI (streaming + non-streaming)
│   │       └── anthropic.py      # ParryAnthropic (streaming + non-streaming)
│   ├── tests/                    # 11 tests
│   └── pyproject.toml
├── dashboard/                    # React + TypeScript + Tailwind
│   ├── src/
│   │   ├── main.tsx              # Clerk + QueryClient + ErrorBoundary
│   │   ├── App.tsx               # Router + auth token injection
│   │   ├── components/           # Sidebar, Header, Layout, ErrorBoundary, shadcn/ui
│   │   ├── pages/                # 7 pages (Dashboard, Agents, AgentDetail, Incidents, Policies, Settings, NotFound)
│   │   ├── hooks/                # TanStack Query hooks + SSE stream hook
│   │   ├── lib/                  # API client, types, Zustand store, utils
│   │   └── routes/               # TanStack Router config
│   ├── eslint.config.js
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml            # Full stack: TimescaleDB, Redis, backend, Celery worker, dashboard
├── .env.example                  # All required environment variables
└── README.md
```

### Tech stack

| Layer | Technology | Notes |
|---|---|---|
| **API** | FastAPI, Python 3.12, Pydantic v2 | Async everywhere, cursor-based pagination |
| **ORM** | SQLAlchemy 2.x (async) | `select()` style, UUID PKs, JSONB metadata |
| **Database** | PostgreSQL 16 + TimescaleDB | `agent_events` is a hypertable; never full-scan |
| **Migrations** | Alembic | Async engine support |
| **Queue** | Redis 7 + Celery 5 | Detection runs async after 202 response |
| **Detection** | Custom rule engine | 6 detectors, parallel execution via thread pool |
| **Auth (dashboard)** | Clerk | JWT verification, org-scoped |
| **Auth (SDK)** | API key (`sk-parry-...`) | SHA256 hashed, org-resolved on every request |
| **Billing** | Stripe | Metered per agent |
| **Dashboard** | React 18, TypeScript strict, Tailwind CSS 4, shadcn/ui | TanStack Query + Router, Zustand, Recharts |
| **Real-time** | Server-Sent Events | Auth-scoped, 2s polling interval |
| **Logging** | structlog | JSON in production, console in dev |
| **Testing** | pytest + pytest-asyncio (backend), Vitest (dashboard) | 59 total tests |
| **Linting** | Ruff (backend), ESLint v9 (dashboard) | |

### Data model

```
Org (tenant)
 ├── ApiKey[]          — hashed keys, org-scoped, last_used_at tracking
 ├── Agent[]           — named AI processes with behavioral baselines
 │    ├── AgentSession[]
 │    └── AgentEvent[] — TimescaleDB hypertable (prompt, response, model, tool_calls, latency, tokens)
 │         └── Detection[] — per-detector results (triggered, severity, confidence, reason)
 ├── Incident[]        — grouped detections requiring human review (open → acknowledged → resolved/dismissed)
 └── Policy[]          — allowed_tools, blocked_tools, allowed_domains, blocked_domains, max_token_budget, forbidden_patterns
```

### Detection pipeline

Every ingested event triggers this pipeline via Celery:

1. **Load context** — fetch agent, baseline, and all active org policies from DB
2. **Merge policies** — combine allowed/blocked tools, domains, patterns across all active policies
3. **Run 6 detectors in parallel** — thread pool executor, each returns `DetectionResult`
4. **Evaluate** — if any detector returns confidence 0.4–0.7, flag for LLM fallback (planned)
5. **Persist** — write all `Detection` rows to DB
6. **Create incident** — if any detection triggered at HIGH or CRITICAL, auto-create `Incident` linking the detections
7. **Retry on failure** — 3 retries with exponential backoff, 30s soft timeout, 60s hard kill

### API endpoints

All routes under `/api/v1/`. Dashboard routes use `Authorization: Bearer sk-parry-...`. SDK ingestion uses `X-Parry-Secret: sk-parry-...`.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | None | Health check |
| `POST` | `/api/v1/events/ingest` | SDK key | Ingest event from SDK (returns 202) |
| `GET` | `/api/v1/events` | Bearer | List events for an agent (cursor-paginated) |
| `GET` | `/api/v1/events/stream` | Bearer | SSE real-time event stream for an agent |
| `GET` | `/api/v1/events/:id` | Bearer | Get single event |
| `GET` | `/api/v1/agents` | Bearer | List org's agents |
| `POST` | `/api/v1/agents` | Bearer | Create agent |
| `GET` | `/api/v1/agents/:id` | Bearer | Get agent |
| `PATCH` | `/api/v1/agents/:id` | Bearer | Update agent |
| `GET` | `/api/v1/incidents` | Bearer | List incidents (filter by severity/status) |
| `PATCH` | `/api/v1/incidents/:id` | Bearer | Update incident status |
| `GET` | `/api/v1/policies` | Bearer | List policies |
| `POST` | `/api/v1/policies` | Bearer | Create policy |
| `PATCH` | `/api/v1/policies/:id` | Bearer | Update policy |
| `DELETE` | `/api/v1/policies/:id` | Bearer | Delete policy |
| `GET` | `/api/v1/api-keys` | Bearer | List API keys |
| `POST` | `/api/v1/api-keys` | Bearer | Create API key (returns raw key once) |
| `DELETE` | `/api/v1/api-keys/:id` | Bearer | Revoke API key |

---

## Running locally

### Prerequisites

- Docker + Docker Compose
- Python 3.12+
- Node.js 20+
- [uv](https://docs.astral.sh/uv/) (`pip install uv` or `brew install uv`)

### Option 1: Docker Compose (recommended)

Starts the full stack with hot reload on all services — edit code on your host and changes reflect immediately:

| Service | Port | Hot Reload |
|---------|------|------------|
| **Backend** (FastAPI) | `:8000` | `./backend/app` mounted, uvicorn `--reload` |
| **Worker** (Celery) | — | `./backend/app` mounted, `watchmedo` auto-restart on `*.py` changes |
| **Dashboard** (Vite) | `:5173` | `./dashboard/src` mounted, Vite HMR |
| **PostgreSQL** (TimescaleDB) | `:5432` | Persistent volume |
| **Redis** | `:6379` | — |

```bash
git clone https://github.com/sharukhhasan/parry.git
cd parry

# Configure environment
cp .env.example .env
# Edit .env — at minimum set:
#   ANTHROPIC_API_KEY (for LLM fallback detector)
#   CLERK_SECRET_KEY + CLERK_PUBLISHABLE_KEY (for auth)

cp dashboard/.env.example dashboard/.env
# Edit dashboard/.env — set VITE_CLERK_PUBLISHABLE_KEY

# Start all services (first run builds images)
docker compose up -d

# Apply database migrations
docker compose exec backend uv run alembic upgrade head

# Verify everything is running
curl http://localhost:8000/health
# → {"status": "ok", "version": "0.1.0"}

# Dashboard at http://localhost:5173
# API docs at http://localhost:8000/docs
```

Now edit any file:
- Change `backend/app/**/*.py` → backend auto-reloads, worker auto-restarts
- Change `dashboard/src/**` → Vite HMR updates the browser instantly

### Option 2: Manual (no Docker)

You'll need PostgreSQL 16 with TimescaleDB and Redis 7 running locally.

**1. Database**

```bash
# If using Homebrew:
brew install timescaledb
# Or pull the Docker image just for the DB:
docker run -d --name parry-db -p 5432:5432 \
  -e POSTGRES_USER=parry -e POSTGRES_PASSWORD=parry -e POSTGRES_DB=parry \
  timescale/timescaledb:latest-pg16
```

**2. Redis**

```bash
brew install redis && redis-server
# Or:
docker run -d --name parry-redis -p 6379:6379 redis:7-alpine
```

**3. Backend**

```bash
cd backend
cp ../.env.example ../.env
# Edit ../.env with your database/redis URLs and API keys

# Install dependencies
uv sync

# Apply migrations
uv run alembic upgrade head

# Start the API server
uv run uvicorn app.main:app --reload --port 8000

# In a separate terminal — start the Celery worker
cd backend
uv run celery -A app.workers.celery_app worker --loglevel=info
```

**4. Dashboard**

```bash
cd dashboard
cp .env.example .env
# Edit .env — set VITE_CLERK_PUBLISHABLE_KEY

npm install
npm run dev
# → http://localhost:5173
```

**5. SDK (for testing)**

```bash
cd sdk
uv sync

# In a Python shell:
import parry
parry.init(api_key="sk-parry-...", base_url="http://localhost:8000")

from parry.wrappers.openai import ParryOpenAI
client = ParryOpenAI(agent_id="test-agent")
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

### Docker commands reference

```bash
docker compose up -d                          # start all services
docker compose up -d --build                  # rebuild all images (after dependency changes)
docker compose up -d --build backend worker   # rebuild backend + worker only
docker compose logs -f backend                # tail backend logs
docker compose logs -f worker                 # tail Celery worker logs
docker compose logs -f dashboard              # tail dashboard logs
docker compose exec backend uv run alembic upgrade head   # run migrations
docker compose exec backend uv run alembic revision --autogenerate -m "description"  # new migration
docker compose exec backend uv run pytest     # run backend tests inside container
docker compose restart worker                 # restart worker (if watchmedo misses a change)
docker compose down                           # stop all services
docker compose down -v                        # stop + delete volumes (wipes DB)
```

---

## Development

### Running tests

```bash
# Backend (48 tests — detectors, pipeline, services)
cd backend
uv run pytest                              # all tests
uv run pytest tests/detection/ -v          # detection tests only
uv run pytest -k "test_prompt_injection"   # specific test

# SDK (11 tests — PII stripping, client, interceptor)
cd sdk
uv run pytest

# Dashboard
cd dashboard
npm test
```

### Code quality

```bash
# Backend
cd backend
uv run ruff check app/ && uv run ruff format app/   # lint + format
uv run mypy app/                                      # type check

# Dashboard
cd dashboard
npm run lint                                           # ESLint
npx tsc --noEmit                                       # TypeScript check
```

### Adding a new detector

1. Create `backend/app/detection/detectors/your_detector.py`
2. Implement the `BaseDetector` protocol — must have `name: str` and `def detect(self, event_data: dict) -> DetectionResult`
3. Register in `backend/app/detection/registry.py`
4. Add tests in `backend/tests/detection/test_your_detector.py` — cover trigger, non-trigger, and edge cases
5. Run `uv run pytest tests/detection/` to verify

---

## Environment variables

See `.env.example` for the full list. Critical ones:

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string (`postgresql+asyncpg://...`) |
| `REDIS_URL` | Yes | Redis connection string |
| `ANTHROPIC_API_KEY` | No | For LLM fallback detector (ambiguous cases) |
| `CLERK_SECRET_KEY` | Yes | Backend auth verification |
| `CLERK_PUBLISHABLE_KEY` | Yes | Dashboard auth |
| `STRIPE_SECRET_KEY` | No | Billing integration |
| `PARRY_INTERNAL_SECRET` | No | Legacy; SDK now uses API keys |
| `ALLOWED_ORIGINS` | No | CORS origins (defaults to localhost) |
| `VITE_CLERK_PUBLISHABLE_KEY` | Yes | Dashboard env (same value as `CLERK_PUBLISHABLE_KEY`) |
| `VITE_API_URL` | No | Dashboard API URL (empty = use Vite proxy) |

---

## License

MIT
