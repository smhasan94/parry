# Parry

Runtime security for AI agents. Parry sits between your AI agents and the LLMs they call, detecting prompt injection, data exfiltration, tool misuse, and anomalous behavior in real time.

## What is Parry?

AI agents are powerful but dangerous. They execute tool calls, handle sensitive data, and operate with broad permissions. A single prompt injection can hijack an agent's actions. A misconfigured tool policy can leak customer data. An anomalous behavior pattern can indicate a compromised agent.

Parry is a security layer that monitors every LLM call your agents make. A lightweight Python SDK wraps your existing OpenAI, Anthropic, or LangChain client. Every prompt and response flows through a detection pipeline of 7 specialized detectors, policy enforcers, and an LLM-powered fallback classifier. When something looks wrong, Parry creates an incident, alerts your team via the dashboard, and logs the full context for investigation.

The SDK adds zero latency to your agent's calls. Events are sent asynchronously in the background. If Parry's backend goes down, your agent keeps running. Fail-open by design.

**Two lines to integrate:**

```python
import parry
parry.init(api_key="sk-parry-...")

from parry.wrappers.openai import ParryOpenAI
client = ParryOpenAI()  # drop-in replacement for openai.OpenAI()
```

Every LLM call after that is monitored. Streaming and non-streaming. OpenAI, Anthropic, and LangChain.

---

## Architecture Overview

```
                         Your AI Agent
                              │
                              │  LLM call (sync or streaming)
                              ▼
                    ┌─────────────────────┐
                    │     Parry SDK        │
                    │                     │
                    │  • PII stripped      │
                    │    client-side       │
                    │  • fire-and-forget   │
                    │  • fail-open         │
                    └────────┬────────────┘
                             │ async POST /api/v1/events/ingest
                             ▼
                    ┌─────────────────────┐          ┌──────────────┐
                    │  FastAPI Backend     │◄────────►│  PostgreSQL  │
                    │                     │          │  TimescaleDB │
                    │  • Auth (Clerk JWT  │          └──────────────┘
                    │    + API keys)      │
                    │  • Rate limiting    │          ┌──────────────┐
                    │  • 202 Accepted     │◄────────►│    Redis     │
                    └────────┬────────────┘          └──────────────┘
                             │ Celery task
                             ▼
                    ┌─────────────────────┐
                    │  Detection Pipeline  │
                    │                     │
                    │  6 detectors run    │
                    │  in parallel:       │
                    │  • Prompt Injection │
                    │  • Jailbreak        │
                    │  • Tool Misuse      │
                    │  • Data Exfil       │
                    │  • Priv Escalation  │
                    │  • Anomaly          │
                    │                     │
                    │  + LLM fallback for │
                    │    ambiguous scores  │
                    │  + Auto-baseline    │
                    │    generation       │
                    └────────┬────────────┘
                             │ persist results
                             ▼
                    ┌─────────────────────┐
                    │  Incident created   │
                    │  if HIGH/CRITICAL   │
                    └────────┬────────────┘
                             │ SSE stream
                             ▼
                    ┌─────────────────────┐
                    │  React Dashboard    │
                    │                     │
                    │  • Live event feed  │
                    │  • Incident mgmt    │
                    │  • Charts & trends  │
                    │  • Policy editor    │
                    │  • API key mgmt     │
                    └─────────────────────┘
```

---

## Technical Deep Dive

### Detection Engine

Every ingested event triggers an async Celery task that runs the full detection pipeline:

1. **Load context** -- fetch agent record, behavioral baseline, and all active org policies
2. **Merge policies** -- combine allowed/blocked tools, domains, and forbidden patterns across policies
3. **Run 6 detectors in parallel** -- ThreadPoolExecutor, each returns a `DetectionResult` with `triggered`, `severity`, `confidence`, and `reason`
4. **LLM fallback** -- if any detector scores in the ambiguous range (0.4-0.7 confidence), call Claude to make a final judgment
5. **Auto-baseline** -- if the agent has no behavioral baseline and has 20+ events, compute one from historical data (avg/std of latency, token count, tool calls, known models)
6. **Persist** -- write all Detection rows to DB
7. **Create incident** -- if any detection triggered at HIGH or CRITICAL, auto-create an Incident linking the triggered detections
8. **Retry on failure** -- 3 retries with exponential backoff, 30s soft timeout, 60s hard kill

| Detector | What it catches | Method |
|---|---|---|
| **Prompt Injection** | "ignore previous instructions", fake system prompts, model-specific tokens (`[INST]`, `<\|system\|>`) | 10 regex patterns, confidence-weighted |
| **Jailbreak** | DAN, developer mode, uncensored mode, "do anything now" | 8 known jailbreak patterns |
| **Tool Misuse** | Agent calling tools outside its org policy allowlist or on the blocklist | Policy comparison |
| **Data Exfiltration** | Credit cards, SSNs, API keys, private keys, AWS credentials in responses | 6 PII/secret patterns |
| **Privilege Escalation** | sudo/admin access, disable auth/logging, modify permissions | 6 escalation patterns |
| **Anomaly** | Token count drift (3-sigma), latency drift, unknown models, excessive tool calls | Statistical comparison against agent baseline |
| **LLM Fallback** | Ambiguous cases where rule-based detectors aren't confident | Claude-powered classification |

### SDK

The SDK provides drop-in wrappers for the three major LLM ecosystems:

**Sync client** (`ParryClient`) -- sends events in background threads, never blocks the caller.

**Async client** (`AsyncParryClient`) -- for async codebases like FastAPI. Uses `asyncio.create_task()` for fire-and-forget, or `send_event_blocking()` when you need delivery guarantees.

**Wrappers:**
- `ParryOpenAI` -- wraps `openai.OpenAI()`. Intercepts `chat.completions.create()` for both sync and streaming.
- `ParryAnthropic` -- wraps `anthropic.Anthropic()`. Intercepts `messages.create()` for both sync and streaming.
- `ParryCallbackHandler` -- LangChain `BaseCallbackHandler`. Works with any chain, model, or agent via the `callbacks` config.

All wrappers strip PII (credit cards, SSNs, emails) client-side before sending events to the backend.

### Data Model

```
Org (tenant)
 ├── ApiKey[]          -- hashed keys, org-scoped, last_used_at tracking
 ├── Agent[]           -- named AI processes with behavioral baselines
 │    ├── AgentSession[]
 │    └── AgentEvent[] -- TimescaleDB hypertable (prompt, response, model, tool_calls, latency, tokens)
 │         └── Detection[] -- per-detector results (triggered, severity, confidence, reason)
 ├── Incident[]        -- grouped detections requiring human review (open -> acknowledged -> resolved)
 └── Policy[]          -- allowed_tools, blocked_tools, max_token_budget, forbidden_patterns
```

`agent_events` is a TimescaleDB hypertable partitioned by timestamp. Always queried with `agent_id` + time range. A 90-day retention policy auto-drops old chunks.

### Authentication

Two auth modes coexist (see [docs/CLERK_SETUP.md](docs/CLERK_SETUP.md) for full setup):

- **SDK requests** use `X-Parry-Secret: sk-parry-...` header. The key is SHA256-hashed and looked up in the `api_keys` table.
- **Dashboard requests** use `Authorization: Bearer <token>`. Clerk JWTs (RS256, verified via JWKS) authenticate with the role Clerk assigns. Parry API keys (`sk-parry-...`) are accepted on this path too but resolve to **viewer** (read-only) — they're runtime credentials, not management credentials, and a leaked SDK key must not grant mutating access to the dashboard.

### API Endpoints

All routes under `/api/v1/`. Rate-limited per client via Redis sliding window.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | None | Dependency health check (DB + Redis) |
| `GET` | `/metrics` | None | Prometheus scrape endpoint |
| `POST` | `/api/v1/events/ingest` | SDK key | Ingest event (returns 202) |
| `GET` | `/api/v1/events` | Bearer | List events for agent (cursor-paginated) |
| `GET` | `/api/v1/events/stream` | Bearer | SSE real-time event stream |
| `GET` | `/api/v1/events/:id` | Bearer | Get single event |
| `GET` | `/api/v1/agents` | Bearer | List agents |
| `POST` | `/api/v1/agents` | Bearer | Create agent |
| `GET` | `/api/v1/agents/:id` | Bearer | Get agent |
| `PATCH` | `/api/v1/agents/:id` | Bearer | Update agent |
| `DELETE` | `/api/v1/agents/:id` | Bearer | Soft-delete agent |
| `GET` | `/api/v1/incidents` | Bearer | List incidents (filter by severity/status) |
| `GET` | `/api/v1/incidents/:id` | Bearer | Get incident with detections |
| `PATCH` | `/api/v1/incidents/:id` | Bearer | Update incident status |
| `GET` | `/api/v1/policies` | Bearer | List policies |
| `POST` | `/api/v1/policies` | Bearer | Create policy |
| `PATCH` | `/api/v1/policies/:id` | Bearer | Update policy |
| `DELETE` | `/api/v1/policies/:id` | Bearer | Delete policy |
| `GET` | `/api/v1/api-keys` | Bearer | List API keys |
| `POST` | `/api/v1/api-keys` | Bearer | Create API key (returns raw key once) |
| `DELETE` | `/api/v1/api-keys/:id` | Bearer | Revoke API key |
| `POST` | `/api/v1/billing/checkout` | Bearer | Create Stripe checkout session |
| `POST` | `/api/v1/billing/portal` | Bearer | Create Stripe billing portal session |
| `POST` | `/api/v1/billing/webhooks/stripe` | Stripe sig | Handle subscription events |
| `POST` | `/api/v1/webhooks/clerk` | Svix sig | Handle org lifecycle events |

### Tech Stack

| Layer | Technology |
|---|---|
| **API** | FastAPI, Python 3.12, Pydantic v2 |
| **ORM** | SQLAlchemy 2.x (async), Alembic |
| **Database** | PostgreSQL 16 + TimescaleDB |
| **Queue** | Redis 7, Celery 5 |
| **Detection** | 6 rule-based detectors + Claude LLM fallback |
| **Auth** | Clerk (JWT/JWKS), API keys (SHA256) |
| **Billing** | Stripe (checkout, portal, webhooks) |
| **Dashboard** | React 18, TypeScript, Tailwind CSS 4, shadcn/ui, Recharts |
| **Real-time** | Server-Sent Events |
| **Testing** | pytest + pytest-asyncio (75+), Vitest (15), SDK pytest (49) -- 139+ total |
| **CI** | GitHub Actions (4 parallel jobs) |
| **Infra** | Docker Compose (dev), multi-stage Dockerfiles (prod) |

### Repo Structure

```
parry/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app, middleware, health check
│   │   ├── api/v1/
│   │   │   ├── agents.py             # CRUD + soft-delete
│   │   │   ├── api_keys.py           # Create, list, revoke
│   │   │   ├── billing.py            # Stripe checkout, portal, webhooks
│   │   │   ├── events.py             # Ingest, list, SSE stream
│   │   │   ├── incidents.py          # List, get, update status
│   │   │   ├── policies.py           # CRUD
│   │   │   └── webhooks.py           # Clerk org lifecycle webhooks
│   │   ├── core/
│   │   │   ├── config.py             # Pydantic Settings
│   │   │   ├── dependencies.py       # Auth: Clerk JWT + API key resolution
│   │   │   ├── rate_limit.py         # Redis sliding window rate limiter
│   │   │   └── exceptions.py         # Domain exceptions
│   │   ├── db/
│   │   │   ├── models.py             # 8 SQLAlchemy models
│   │   │   └── session.py            # Async engine + session factory
│   │   ├── detection/
│   │   │   ├── pipeline.py           # Orchestrator: parallel detect -> LLM fallback -> persist
│   │   │   ├── base.py               # BaseDetector protocol, DetectionResult
│   │   │   ├── registry.py           # Detector registration
│   │   │   └── detectors/            # 7 detector implementations
│   │   ├── services/
│   │   │   ├── baseline_service.py   # Auto-compute agent behavioral baselines
│   │   │   ├── billing_service.py    # Stripe customer, checkout, portal
│   │   │   ├── detection_service.py  # Run pipeline + persist + create incidents
│   │   │   ├── event_service.py      # Ingest, list, get events
│   │   │   ├── incident_service.py   # List, get, update incidents
│   │   │   └── agent_service.py      # CRUD + soft-delete
│   │   └── workers/
│   │       └── detection_task.py     # Celery task with retry + timeout
│   ├── alembic/versions/             # 3 migrations
│   ├── tests/                        # 80 tests (unit + E2E)
│   └── Dockerfile                    # Multi-stage production build
├── sdk/
│   ├── parry/
│   │   ├── client.py                 # Sync client (background threads)
│   │   ├── async_client.py           # Async client (asyncio tasks)
│   │   ├── interceptor.py            # PII stripping, intercept_completion()
│   │   └── wrappers/
│   │       ├── openai.py             # ParryOpenAI (sync + streaming)
│   │       ├── anthropic.py          # ParryAnthropic (sync + streaming)
│   │       └── langchain.py          # ParryCallbackHandler
│   ├── tests/                        # 49 tests
│   ├── README.md                     # PyPI-ready documentation
│   └── pyproject.toml
├── dashboard/
│   ├── src/
│   │   ├── pages/                    # 7 pages
│   │   ├── components/
│   │   │   ├── charts/               # Recharts: severity donut, trend, sparklines, detector bars
│   │   │   ├── EventDetailModal.tsx  # Full event detail view
│   │   │   └── ui/                   # shadcn/ui + toast system
│   │   ├── hooks/                    # TanStack Query + infinite scroll + SSE
│   │   └── lib/                      # API client, types, chart theme
│   ├── src/__tests__/                # 11 Vitest tests
│   ├── Dockerfile                    # Multi-stage: npm build -> nginx
│   └── vitest.config.ts
├── docs/
│   ├── CLERK_SETUP.md                # Clerk auth + webhook setup guide
│   └── OPERATIONS.md                 # Deployment, monitoring, troubleshooting runbook
├── .github/workflows/ci.yml          # 5 parallel CI jobs (incl. migration test)
├── docker-compose.yml                # Development (hot reload, debug ports)
├── docker-compose.prod.yml           # Production (nginx, restart policies)
└── .env.example
```

---

## Running Locally

### Prerequisites

- Docker + Docker Compose
- Python 3.12+
- Node.js 20+
- [uv](https://docs.astral.sh/uv/) (`pip install uv` or `brew install uv`)

### Docker Compose (recommended)

```bash
git clone https://github.com/sharukhhasan/parry.git
cd parry

# Configure environment
cp .env.example .env
# Edit .env -- set at minimum:
#   ANTHROPIC_API_KEY (for LLM fallback detector)
#   CLERK_SECRET_KEY + CLERK_PUBLISHABLE_KEY (for auth)

cp dashboard/.env.example dashboard/.env
# Edit dashboard/.env -- set VITE_CLERK_PUBLISHABLE_KEY

# Start all services (migrations run automatically)
docker compose up -d

# Seed demo data (org, API key, sample agent, policy)
docker compose exec backend uv run python scripts/seed.py
# Save the API key printed -- it's shown only once

# Verify
curl http://localhost:8000/health
# -> {"status": "ok", "version": "0.1.0", "checks": {"database": "ok", "redis": "ok"}}
```

| Service | URL | Hot Reload |
|---------|-----|------------|
| Backend API | http://localhost:8000 | Yes (uvicorn --reload) |
| Swagger UI | http://localhost:8000/docs | - |
| Scalar Reference | http://localhost:8000/docs/scalar | - |
| Dashboard | http://localhost:5173 | Yes (Vite HMR) |
| Celery Worker | - | Yes (watchmedo) |
| PostgreSQL | localhost:5434 | Persistent volume |
| Redis | localhost:6380 | - |

### Manual Setup (no Docker)

**1. Start PostgreSQL + Redis**

```bash
# TimescaleDB
docker run -d --name parry-db -p 5432:5432 \
  -e POSTGRES_USER=parry -e POSTGRES_PASSWORD=parry -e POSTGRES_DB=parry \
  timescale/timescaledb:latest-pg16

# Redis
docker run -d --name parry-redis -p 6379:6379 redis:7-alpine
```

**2. Backend**

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run python scripts/seed.py
uv run uvicorn app.main:app --reload --port 8000
```

**3. Celery Worker** (separate terminal)

```bash
cd backend
uv run celery -A app.workers.celery_app worker --loglevel=info
```

**4. Dashboard**

```bash
cd dashboard
npm install
npm run dev
```

**5. Test with the SDK**

```bash
cd sdk
uv sync

python -c "
import parry
parry.init(api_key='sk-parry-YOUR-KEY', base_url='http://localhost:8000')

from parry.wrappers.openai import ParryOpenAI
client = ParryOpenAI(agent_id='test-agent')
response = client.chat.completions.create(
    model='gpt-4o',
    messages=[{'role': 'user', 'content': 'Hello!'}]
)
print(response.choices[0].message.content)
"
```

### Running Tests

```bash
# Backend (75+ unit tests, 25 integration tests requiring DB)
cd backend && uv run pytest

# SDK (49 tests)
cd sdk && uv run pytest

# Dashboard (15 tests)
cd dashboard && npm test
```

### Docker Reference

```bash
docker compose up -d                          # start all
docker compose up -d --build                  # rebuild after dep changes
docker compose logs -f backend                # tail backend logs
docker compose logs -f worker                 # tail worker logs
docker compose exec backend uv run alembic upgrade head  # run migrations
docker compose down                           # stop all
docker compose down -v                        # stop + wipe data
```

---

## Production Deployment

Three supported paths, in order of recommendation:

| Path | Best for | Guide |
|---|---|---|
| **DigitalOcean droplet (or any VPS)** | Simplest. One $24/mo box runs the whole stack with auto-HTTPS via Caddy. | [docs/DROPLET.md](docs/DROPLET.md) |
| **Self-hosted docker-compose** | Existing infra you control. | [docs/OPERATIONS.md](docs/OPERATIONS.md) |
| **Railway (managed PaaS)** | Zero ops, but more setup steps and higher per-service cost. | [docs/RAILWAY.md](docs/RAILWAY.md) |

Quickest path on a fresh VPS:

```bash
git clone https://github.com/sharukhhasan/parry.git && cd parry
cp .env.example .env  # fill in DOMAIN, CADDY_EMAIL, Clerk keys
make prod-up          # automatic HTTPS via Let's Encrypt, migrations run on first boot
```

Run `make help` to see all dev/prod/backup shortcuts.

## Environment Variables

See `.env.example` for the full list.

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection (`postgresql+asyncpg://...`) |
| `REDIS_URL` | Yes | Redis connection |
| `ANTHROPIC_API_KEY` | No | LLM fallback detector (resolves ambiguous scores) |
| `CLERK_SECRET_KEY` | Yes | Backend JWT verification |
| `CLERK_PUBLISHABLE_KEY` | Yes | Used to derive JWKS URL |
| `CLERK_WEBHOOK_SECRET` | No | Svix signature verification for Clerk webhooks |
| `STRIPE_SECRET_KEY` | No | Billing integration |
| `STRIPE_WEBHOOK_SECRET` | No | Stripe webhook signature verification |
| `VITE_CLERK_PUBLISHABLE_KEY` | Yes | Dashboard Clerk auth |

---

## License

MIT
