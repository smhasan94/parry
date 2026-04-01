# Parry — MVP Build Checklist

Track progress here. Claude Code can check off items as they're completed.

---

## Phase 0 — Foundation (Week 1–2)

### Repo & infra
- [ ] Monorepo structure created (backend/, sdk/, dashboard/, docs/)
- [ ] `docker-compose.yml` with postgres, redis, backend, worker, dashboard
- [ ] PostgreSQL + TimescaleDB extension enabled
- [ ] `.env.example` with all required vars documented
- [ ] GitHub Actions CI: lint + test on push
- [ ] Pre-commit hooks: ruff, mypy, eslint

### Backend skeleton
- [ ] FastAPI app entrypoint (`app/main.py`)
- [ ] Config via `pydantic-settings` (`app/core/config.py`)
- [ ] Structlog JSON logging setup
- [ ] SQLAlchemy async engine + session factory
- [ ] Alembic configured, initial migration
- [ ] Health check endpoint `GET /health`
- [ ] Celery app configured with Redis broker

### Initial DB migrations
- [ ] `orgs` table
- [ ] `api_keys` table
- [ ] `agents` table
- [ ] `policies` table
- [ ] `agent_events` hypertable (TimescaleDB)
- [ ] `detections` table
- [ ] `incidents` table

---

## Phase 1 — SDK & Proxy Core (Week 3–5)

### SDK
- [ ] `sdk/` package structure with `pyproject.toml`
- [ ] `parry.init(api_key, agent_id)` entrypoint
- [ ] `SentinelOpenAI` wrapper (wraps `openai.OpenAI`)
- [ ] `SentinelAnthropic` wrapper (wraps `anthropic.Anthropic`)
- [ ] `interceptor.py` — core interception + event construction
- [ ] PII stripping (credit card, SSN, email patterns)
- [ ] Async fire-and-forget event send to backend
- [ ] Fail-open: if backend unreachable, log + continue
- [ ] SDK unit tests (no network required)
- [ ] `pip install parry` smoke test example

### Backend — event ingest
- [ ] `POST /api/v1/events` — receive event from SDK
- [ ] API key authentication middleware
- [ ] Org + agent lookup / creation on first event
- [ ] Event written to `agent_events` hypertable
- [ ] Celery task queued for detection pipeline
- [ ] Returns 202 Accepted immediately (non-blocking)

---

## Phase 2 — Detection Engine (Week 6–8)

### Core pipeline
- [ ] `BaseDetector` protocol defined
- [ ] `EventContext` dataclass
- [ ] `DetectionResult` dataclass with `Severity` enum
- [ ] `PreProcessor` — normalise, extract tool calls, truncate
- [ ] `Aggregator` — combine scores, decide LLM fallback threshold
- [ ] Detection pipeline runner (asyncio.gather across detectors)
- [ ] Write results to `detections` table

### Detectors (implement in order)
- [ ] `PromptInjectionDetector` — pattern-based (regex + keyword)
- [ ] `JailbreakDetector` — known jailbreak phrase list
- [ ] `ToolMisuseDetector` — tool calls vs policy allowlist
- [ ] `PolicyEnforcer` — domains, forbidden patterns
- [ ] `DataExfiltrationDetector` — PII/secrets in response
- [ ] `PrivilegeEscalationDetector` — escalation language patterns
- [ ] `AnomalyDetector` — z-score vs agent baseline
- [ ] `LLMFallbackDetector` — Claude API for ambiguous cases

### Tests
- [ ] Unit tests for every detector (trigger + non-trigger + edge case)
- [ ] Integration test: full pipeline against fixture events
- [ ] Fixture JSON files for each detector in `tests/fixtures/`

### Incident correlator
- [ ] Celery task: group related detections → incident
- [ ] Auto-title generation for incidents
- [ ] SSE push for HIGH/CRITICAL incidents

---

## Phase 3 — Dashboard MVP (Week 9–10)

### Setup
- [ ] React 18 + TypeScript + Tailwind + shadcn/ui scaffolded
- [ ] TanStack Router file-based routing
- [ ] TanStack Query client configured
- [ ] Clerk auth integrated (`<ClerkProvider>`)
- [ ] API client (`src/lib/api.ts`) with auth headers

### Pages
- [ ] `/dashboard` — org overview, agent grid, metric cards
- [ ] `/agents/:agentId` — agent detail, event timeline
- [ ] `/incidents` — incident list with severity filter + status update
- [ ] `/policies` — policy editor (tools allowlist, blocked domains)
- [ ] `/settings/api-keys` — create/revoke API keys

### Real-time
- [ ] SSE endpoint `GET /api/v1/events/stream` (backend)
- [ ] `useAgentEventStream` hook (frontend)
- [ ] Live event feed on dashboard page

### Backend — dashboard API routes
- [ ] `GET /api/v1/agents` — list org's agents
- [ ] `GET /api/v1/agents/:id/events` — paginated event list
- [ ] `GET /api/v1/agents/:id/stats` — summary stats
- [ ] `GET /api/v1/incidents` — paginated, filterable
- [ ] `PATCH /api/v1/incidents/:id` — update status
- [ ] `GET /api/v1/policies` + `PUT /api/v1/policies/:id`
- [ ] `POST /api/v1/api-keys` + `DELETE /api/v1/api-keys/:id`

---

## Phase 4 — Auth, Billing & Launch (Week 11–12)

### Auth (Clerk)
- [ ] Clerk org-based multi-tenancy
- [ ] JWT verification middleware in FastAPI
- [ ] RBAC: owner / admin / viewer roles
- [ ] API key creation scoped to org

### Billing (Stripe)
- [ ] Stripe customer created on org signup
- [ ] Metered billing: report agent_events count to Stripe daily
- [ ] `GET /api/v1/billing/portal` — redirect to Stripe portal
- [ ] Plan enforcement: free tier limits (1 agent, 10K events/mo)
- [ ] Stripe webhook: handle `customer.subscription.updated`

### Launch prep
- [ ] Production `docker-compose.prod.yml`
- [ ] Render deployment configured (web + worker + static)
- [ ] `CLAUDE.local.md` created (gitignored, personal notes)
- [ ] README.md with quickstart
- [ ] Landing page (can be simple, outside this repo)
- [ ] `docs/runbook.md` — deploy, rollback, debug steps

---

## Phase 5 — Growth Features (Month 4–6)

- [ ] Compliance report export (PDF, EU AI Act format)
- [ ] Slack integration (incident alerts)
- [ ] PagerDuty integration (CRITICAL incidents)
- [ ] Webhook support (org-configurable)
- [ ] LangChain native integration
- [ ] CrewAI native integration
- [ ] REST API docs (auto-generated via FastAPI + Scalar)
- [ ] Usage analytics dashboard
- [ ] Agent baseline visualization

---

## Phase 6 — Enterprise (Month 7–8)

- [ ] SSO (SAML via WorkOS)
- [ ] On-prem agent mode (Docker image, no data leaves network)
- [ ] Custom detection rules (org-defined regex/patterns via UI)
- [ ] SLA dashboard
- [ ] SOC 2 audit trail export
- [ ] Enterprise tier billing
- [ ] Dedicated support Slack channel setup
