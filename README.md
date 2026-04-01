# Parry

Runtime security for AI agents. Detect prompt injection, tool misuse, and anomalous behavior before damage is done.

---

## What is Parry?

Parry sits between your AI agents and the LLMs they call. Every prompt and response is intercepted, inspected by the detection engine, and checked against your org's policy — in real time, before damage is done.

**Two lines to integrate:**

```python
import parry
parry.init(api_key="pk-...")

from parry.wrappers.openai import ParryOpenAI
client = ParryOpenAI()  # drop-in replacement for openai.OpenAI()
```

From that point on, every LLM call your agent makes is monitored.

---

## What it detects

| Threat | Description |
|---|---|
| Prompt injection | Attempts to hijack agent instructions via crafted input |
| Jailbreaks | Known jailbreak patterns embedded in prompts |
| Tool misuse | Agent calling tools outside its defined policy |
| Data exfiltration | PII or secrets appearing in model responses |
| Privilege escalation | Attempts to gain elevated access or capabilities |
| Behavioral anomaly | Drift from the agent's established baseline |
| Policy violations | Domain, token budget, or pattern rule breaches |

---

## How it works

```
Your AI agent
     │
     │  every LLM call
     ▼
 Parry SDK          ← 2-line integration, fail-open, zero latency impact
     │
     │  async event (fire-and-forget)
     ▼
 Parry backend
     │
     ├── Rule-based detectors  (< 5ms, runs sync)
     ├── ML classifiers        (lightweight, local)
     └── LLM fallback          (Claude API, ambiguous cases only)
     │
     ▼
 PostgreSQL + TimescaleDB     ← agent events, detections, incidents
     │
     ▼
 Dashboard                    ← live feed, alerts, policy editor, audit log
```

**Fail-open by design.** If the Parry backend is unreachable, the SDK logs a warning and passes the call through unchanged. Your agents never go down because of us.

---

## Architecture

### Repo structure

```
parry/
├── backend/                  # FastAPI application
│   ├── app/
│   │   ├── api/              # Route handlers (v1/)
│   │   ├── core/             # Config, logging, middleware
│   │   ├── db/               # SQLAlchemy models, Alembic migrations
│   │   ├── detection/        # Detection engine — rules, classifiers, pipeline
│   │   ├── proxy/            # LLM call interceptor
│   │   ├── services/         # Business logic
│   │   ├── schemas/          # Pydantic request/response models
│   │   └── workers/          # Celery async tasks
│   └── tests/
├── sdk/                      # pip install parry
│   ├── parry/
│   │   ├── wrappers/         # openai.py, anthropic.py, langchain.py
│   │   └── interceptor.py    # Core interception logic
│   └── tests/
├── dashboard/                # React + Tailwind frontend
│   └── src/
│       ├── pages/
│       ├── components/
│       └── hooks/
└── docs/                     # Architecture, ADRs, specs
```

### Stack

| Layer | Technology |
|---|---|
| API | FastAPI, Python 3.12, Pydantic v2 |
| Database | PostgreSQL 16 + TimescaleDB |
| Cache / Queue | Redis 7, Celery 5 |
| Detection | spaCy, scikit-learn, Anthropic API (fallback) |
| Auth | Clerk |
| Billing | Stripe (metered per agent) |
| Dashboard | React 18, TypeScript, Tailwind CSS, shadcn/ui |
| Infra (dev) | Docker Compose |
| Infra (prod) | Render |

### Detection pipeline

Every event passes through this pipeline in order:

1. **PreProcessor** — normalise, strip PII, extract tool calls
2. **Rule-based detectors** — run in parallel via `asyncio.gather` (< 5ms)
3. **Aggregator** — combines scores; triggers LLM fallback if score is 0.4–0.7
4. **LLM fallback** — Claude API call for ambiguous cases only
5. **Policy enforcer** — checks against org-defined rules regardless of score
6. **Incident correlator** — groups related detections (async Celery task)

### Data model (key tables)

- `orgs` — top-level tenant, billing plan
- `agents` — named AI processes with behavioral baselines
- `agent_events` — TimescaleDB hypertable, every LLM call
- `detections` — results from the detection pipeline per event
- `incidents` — correlated detections requiring human review
- `policies` — org-defined rules: allowed tools, blocked domains, forbidden patterns
- `api_keys` — hashed, org-scoped authentication keys

---

## Quickstart

### Prerequisites

- Docker + Docker Compose
- Python 3.12+
- Node.js 20+
- `uv` (`pip install uv`)

### Run locally

```bash
git clone https://github.com/your-org/parry
cd parry

cp .env.example .env
# fill in ANTHROPIC_API_KEY, CLERK_SECRET_KEY, STRIPE_SECRET_KEY

docker compose up -d

cd backend
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Dashboard: `cd dashboard && npm install && npm run dev` → http://localhost:5173

Backend API: http://localhost:8000

### SDK install

```bash
pip install parry
```

```python
import parry

parry.init(
    api_key="pk-...",
    agent_id="my-agent",       # stable identifier for this agent
)

# OpenAI drop-in
from parry.wrappers.openai import ParryOpenAI
client = ParryOpenAI()
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "..."}]
)
# identical to openai.OpenAI() — Parry intercepts transparently
```

---

## Development

### Backend

```bash
cd backend

uv run uvicorn app.main:app --reload           # dev server :8000
uv run pytest                                  # all tests
uv run pytest tests/detection/ -v             # detection tests only
uv run mypy app/                               # type check
uv run ruff check app/ && uv run ruff format app/
uv run alembic upgrade head                    # apply migrations
uv run alembic revision --autogenerate -m ""   # new migration
uv run celery -A app.workers.celery_app worker --loglevel=info
```

### Dashboard

```bash
cd dashboard
npm run dev       # :5173
npm run build
npm run lint
npm test
```

### Docker

```bash
docker compose up -d                    # all services
docker compose up -d --build backend    # rebuild backend
docker compose logs -f backend
docker compose exec backend uv run alembic upgrade head
```

### Environment variables

See `.env.example` for the full list. Required to run locally:

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `ANTHROPIC_API_KEY` | For LLM fallback detector |
| `CLERK_SECRET_KEY` | Auth |
| `STRIPE_SECRET_KEY` | Billing |

---

## Pricing

| Plan | Price | Agents | Events/mo |
|---|---|---|---|
| Free | $0 | 1 | 10K |
| Growth | $99/mo | 10 | 500K |
| Pro | $499/mo | Unlimited | 1M |
| Enterprise | Custom | Unlimited | Unlimited |

---

## Roadmap

### MVP (weeks 1–12)
- [x] Repo structure and Docker Compose stack
- [ ] Python SDK with OpenAI + Anthropic wrappers
- [ ] Detection engine (6 detectors + LLM fallback)
- [ ] React dashboard (live feed, incidents, policy editor)
- [ ] Clerk auth + Stripe billing
- [ ] Deploy to Render

### Growth (months 4–6)
- [ ] EU AI Act compliance report export
- [ ] Slack + PagerDuty integrations
- [ ] LangChain / CrewAI / AutoGen native integrations
- [ ] REST API + auto-generated docs

### Enterprise (months 7–8)
- [ ] SSO (SAML via WorkOS)
- [ ] On-prem agent mode
- [ ] Custom detection rules via UI
- [ ] SOC 2 audit trail export

---

## License

MIT
