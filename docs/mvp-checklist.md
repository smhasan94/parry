# Parry — MVP Build Checklist

Track progress here. Claude Code can check off items as they're completed.

Last updated: 2026-04-07 (plans 00–12 complete).

---

## Phase 0 — Foundation (Week 1–2)

### Repo & infra
- [x] Monorepo structure created (backend/, sdk/, dashboard/, docs/)
- [x] `docker-compose.yml` with postgres, redis, backend, worker, dashboard
- [x] PostgreSQL + TimescaleDB extension enabled
- [x] `.env.example` with all required vars documented
- [x] GitHub Actions CI: lint + test on push
- [ ] Pre-commit hooks: ruff, mypy, eslint

### Backend skeleton
- [x] FastAPI app entrypoint (`app/main.py`)
- [x] Config via `pydantic-settings` (`app/core/config.py`)
- [x] Structlog JSON logging setup
- [x] SQLAlchemy async engine + session factory
- [x] Alembic configured, initial migration
- [x] Health check endpoint `GET /health`
- [x] Celery app configured with Redis broker

### Initial DB migrations
- [x] `orgs` table
- [x] `api_keys` table
- [x] `agents` table
- [x] `policies` table
- [x] `agent_events` hypertable (TimescaleDB)
- [x] `detections` table
- [x] `incidents` table

---

## Phase 1 — SDK & Proxy Core (Week 3–5)

### SDK
- [x] `sdk/` package structure with `pyproject.toml`
- [x] `parry.init(api_key, agent_id)` entrypoint
- [x] `SentinelOpenAI` wrapper (wraps `openai.OpenAI`)
- [x] `SentinelAnthropic` wrapper (wraps `anthropic.Anthropic`)
- [x] `interceptor.py` — core interception + event construction
- [x] PII stripping (credit card, SSN, email patterns)
- [x] Async fire-and-forget event send to backend
- [x] Fail-open: if backend unreachable, log + continue
- [x] SDK unit tests (no network required)
- [x] `pip install parry` smoke test example

### Backend — event ingest
- [x] `POST /api/v1/events` — receive event from SDK
- [x] API key authentication middleware
- [x] Org + agent lookup / creation on first event
- [x] Event written to `agent_events` hypertable
- [x] Celery task queued for detection pipeline
- [x] Returns 202 Accepted immediately (non-blocking)

---

## Phase 2 — Detection Engine (Week 6–8)

### Core pipeline
- [x] `BaseDetector` protocol defined
- [x] `EventContext` dataclass
- [x] `DetectionResult` dataclass with `Severity` enum
- [x] `PreProcessor` — normalise, extract tool calls, truncate
- [x] `Aggregator` — combine scores, decide LLM fallback threshold
- [x] Detection pipeline runner (asyncio.gather across detectors)
- [x] Write results to `detections` table

### Detectors (implement in order)
- [x] `PromptInjectionDetector` — pattern-based (regex + keyword)
- [x] `JailbreakDetector` — known jailbreak phrase list
- [x] `ToolMisuseDetector` — tool calls vs policy allowlist
- [x] `PolicyEnforcer` — domains, forbidden patterns
- [x] `DataExfiltrationDetector` — PII/secrets in response
- [x] `PrivilegeEscalationDetector` — escalation language patterns
- [x] `AnomalyDetector` — z-score vs agent baseline
- [x] `LLMFallbackDetector` — Claude API for ambiguous cases

### Tests
- [x] Unit tests for every detector (trigger + non-trigger + edge case)
- [x] Integration test: full pipeline against fixture events
- [x] Fixture JSON files for each detector in `tests/fixtures/`

### Incident correlator
- [x] Celery task: group related detections → incident
- [x] Auto-title generation for incidents
- [x] SSE push for HIGH/CRITICAL incidents

---

## Phase 3 — Dashboard MVP (Week 9–10)

### Setup
- [x] React 18 + TypeScript + Tailwind + shadcn/ui scaffolded
- [x] TanStack Router file-based routing
- [x] TanStack Query client configured
- [x] Clerk auth integrated (`<ClerkProvider>`)
- [x] API client (`src/lib/api.ts`) with auth headers

### Pages
- [x] `/dashboard` — org overview, agent grid, metric cards
- [x] `/agents/:agentId` — agent detail, event timeline
- [x] `/incidents` — incident list with severity filter + status update
- [x] `/policies` — policy editor (tools allowlist, blocked domains)
- [x] `/settings/api-keys` — create/revoke API keys

### Real-time
- [x] SSE endpoint `GET /api/v1/events/stream` (backend)
- [x] `useAgentEventStream` hook (frontend)
- [x] Live event feed on dashboard page

### Backend — dashboard API routes
- [x] `GET /api/v1/agents` — list org's agents
- [x] `GET /api/v1/agents/:id/events` — paginated event list
- [x] `GET /api/v1/agents/:id/stats` — summary stats
- [x] `GET /api/v1/incidents` — paginated, filterable
- [x] `PATCH /api/v1/incidents/:id` — update status
- [x] `GET /api/v1/policies` + `PUT /api/v1/policies/:id`
- [x] `POST /api/v1/api-keys` + `DELETE /api/v1/api-keys/:id`

---

## Phase 4 — Auth, Billing & Launch (Week 11–12)

### Auth (Clerk)
- [x] Clerk org-based multi-tenancy
- [x] JWT verification middleware in FastAPI
- [x] RBAC: owner / admin / viewer roles *(plan-03)*
- [x] API key creation scoped to org

### Billing (Stripe)
- [x] Stripe customer created on org signup
- [x] Metered billing: report agent_events count to Stripe daily *(plan-11)*
- [x] `GET /api/v1/billing/portal` — redirect to Stripe portal
- [x] Plan enforcement: free tier limits (1 agent, 10K events/mo) *(plan-11)*
- [x] Stripe webhook: handle `customer.subscription.updated` *(plan-11)*

### Launch prep
- [x] Production `docker-compose.prod.yml`
- [x] Render deployment configured (web + worker + static)
- [ ] `CLAUDE.local.md` created (gitignored, personal notes)
- [x] README.md with quickstart
- [ ] Landing page (can be simple, outside this repo)
- [x] `docs/runbook.md` — deploy, rollback, debug steps

---

## Phase 5 — Growth Features (Month 4–6)

- [x] Compliance report export (PDF, EU AI Act format) *(plan-06)*
- [x] Slack integration (incident alerts)
- [x] PagerDuty integration (CRITICAL incidents) *(plan-10)*
- [x] Webhook support (org-configurable)
- [x] LangChain native integration *(plan-04)*
- [x] CrewAI native integration *(plan-04)*
- [ ] REST API docs (auto-generated via FastAPI + Scalar)
- [x] Usage analytics dashboard *(plan-08 behavioural graph)*
- [x] Agent baseline visualization

---

## Phase 6 — Enterprise (Month 7–8)

- [ ] SSO (SAML via WorkOS)
- [ ] On-prem agent mode (Docker image, no data leaves network)
- [x] Custom detection rules (org-defined regex/patterns via UI) *(plan-05)*
- [ ] SLA dashboard
- [ ] SOC 2 audit trail export
- [ ] Enterprise tier billing
- [ ] Dedicated support Slack channel setup

---

## Completed in the plan-01 → plan-12 arc

Beyond the original MVP scope, these shipped as part of the 12-plan
roadmap and are worth tracking separately:

- [x] **plan-01** Active blocking mode (`/proxy/check`, SDK `ParryBlockedError`)
- [x] **plan-02** Response scanning (off/redact/block three-way posture)
- [x] **plan-03** Team RBAC (`VIEWER` / `ADMIN` / `OWNER`)
- [x] **plan-04** Multi-framework SDK wrappers (CrewAI, AutoGen, LlamaIndex, Pydantic AI)
- [x] **plan-05** Custom detection rules dashboard + `/custom-rules/test`
- [x] **plan-06** Compliance report PDF export (WeasyPrint)
- [x] **plan-07** Agent health score (Redis-cached, hourly Celery refresh)
- [x] **plan-08** Agent behavioural graph (event volume, tool calls, anomaly trend)
- [x] **plan-09** Real-time block feed (SSE fan-out via Redis pubsub)
- [x] **plan-10** PagerDuty + Opsgenie alert integrations
- [x] **plan-11** Billing plan enforcement + metered usage reporting
- [x] **plan-12** Session replay timeline
- [x] **plan-00** Stripe subscription sync, SDK publish workflow, api-spec + schema docs
