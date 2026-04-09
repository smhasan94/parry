# Parry

Runtime security for AI agents. Parry sits between your AI agents and the LLMs they call, detecting prompt injection, data exfiltration, tool misuse, cost exploitation, and anomalous behavior in real time.

## What is Parry?

AI agents are powerful but dangerous. They execute tool calls, handle sensitive data, and operate with broad permissions. A single prompt injection can hijack an agent's actions. A misconfigured tool policy can leak customer data. A compromised MCP server can inject instructions into every tool description your agent reads. A runaway loop can burn thousands of dollars in LLM costs in minutes.

Parry is a security layer that monitors every LLM call your agents make. A lightweight Python SDK wraps your existing OpenAI, Anthropic, LangChain, CrewAI, AutoGen, LlamaIndex, or Pydantic AI client. Every prompt and response flows through a detection pipeline of 11 specialized detectors, policy enforcers, and an LLM-powered fallback classifier. When something looks wrong, Parry creates an incident, alerts your team via Slack/PagerDuty/OpsGenie, optionally blocks the call in real time, and logs the full context for investigation.

The SDK adds zero latency to your agent's calls. Events are sent asynchronously in the background. If Parry's backend goes down, your agent keeps running. Fail-open by design.

**Two lines to integrate:**

```python
import parry
parry.init(api_key="sk-parry-...")

from parry.wrappers.openai import ParryOpenAI
client = ParryOpenAI()  # drop-in replacement for openai.OpenAI()
```

Every LLM call after that is monitored. Streaming and non-streaming. Seven framework wrappers available.

---

## Features

### Detection Engine

11 detectors run in parallel on every event via a Celery task pipeline:

| Detector | What it catches | Method |
|---|---|---|
| **Prompt Injection** | "Ignore previous instructions", fake system prompts, model-specific tokens | 10 regex patterns, confidence-weighted |
| **Jailbreak** | DAN, developer mode, uncensored mode, persona hijacks | 8 known jailbreak pattern families |
| **Tool Misuse** | Agent calling tools outside its org policy allowlist or on the blocklist | Policy comparison against merged org policies |
| **Data Exfiltration** | Credit cards, SSNs, API keys, private keys, credentials in responses | 6 PII/secret regex patterns |
| **Privilege Escalation** | sudo/admin claims, disable auth/logging, permission modification | 6 escalation patterns |
| **Anomaly** | Token count drift (3-sigma), latency drift, unknown models, excessive tool calls | Statistical comparison against agent baseline |
| **Custom Rules** | Org-defined regex patterns (e.g., block competitor mentions, catch specific secrets) | Per-org regex rules with severity + target (prompt/response/both) |
| **MCP Manifest** | Instruction injection, jailbreaks, data exfil, suspicious cross-tool mentions, unicode smuggling in MCP tool descriptions and schema fields | 6 pattern categories; smuggling always escalates to CRITICAL |
| **Cost Exploit Loop** | Identical tool calls repeated in rapid succession (denial-of-wallet) | Session history analysis — ≥10/20 identical signatures |
| **Cost Exploit Verbosity** | Response token count >10x the agent's baseline mean | Statistical comparison against agent baseline |
| **Cost Exploit Model Escalation** | Sudden switch to a 3x+ more expensive model mid-session | Model pricing comparison against baseline known models |
| **LLM Fallback** | Ambiguous cases where rule-based detectors scored 0.4-0.7 confidence | Claude-powered classification |

### Active Blocking

Parry can block malicious calls before they reach the LLM. The SDK's sync `/proxy/check` path returns `allowed=false` for HIGH/CRITICAL detections, blocking the call before the agent incurs any cost. Budget enforcement blocks calls when an agent's rolling spend hits 95% of its cap.

### Response Scanning

Three modes for scanning LLM responses before they reach the caller: **off** (default), **redact** (strip sensitive patterns), or **block** (reject the entire response). Forensics always sees the original, unredacted content.

### Policy Regression Runner

Before enabling a custom rule or policy change, preview its impact against the last 30-90 days of historical events. See exactly how many events would have matched, which agents are affected, per-day match distribution, and sample matches with highlighted spans. Removes the fear of enabling rules blindly.

### Red Team Your Agent

One-click adversarial testing against a curated corpus of 48 attacks across 8 categories (instruction override, jailbreak, data exfiltration, tool hijack, privilege escalation, content smuggling, indirect injection, cost exploitation). Sandbox mode replays the corpus through the live detection pipeline without burning LLM tokens. Results show an overall score, per-category detection rates, and a detailed table of undetected attacks.

### MCP Server Security

The first security layer for the Model Context Protocol ecosystem. `SentinelMCPClient` wraps your MCP client connections, scans tool manifests for injection and unicode smuggling, tracks server identity via manifest hashing, and enforces trust levels (observed/trusted/suspicious/blocked) at the protocol boundary. Manifest drift on trusted servers auto-downgrades trust until an admin re-approves.

```python
from parry.mcp import SentinelMCPClient

async with SentinelMCPClient.stdio(
    command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    agent_id="dev-assistant",
    api_key="sk-parry-...",
) as client:
    tools = await client.list_tools()
    result = await client.call_tool("read_file", {"path": "/tmp/notes.md"})
```

### Cost Exploitation Detection + Budget Enforcement

Estimated cost computed on every event using a model pricing registry (15 models, quarterly review). Per-agent budget caps (hourly/daily/monthly) enforced in the blocking path via Redis rolling counters. The cost card on the agent detail page shows real-time spend with progress bars against budgets.

### Session Replay

Navigate the full timeline of a session — every prompt, response, tool call, and detection — with severity-colored borders and expandable content. Live-polls every 5s for open sessions.

### Agent Health Score

Composite score (0-100, A-F grade) combining detection frequency, anomaly rate, policy violations, and baseline stability. Hourly Celery refresh with 2-hour Redis read-through cache. Fleet-wide health card on the dashboard.

### Agent Behavioral Stats

Windowed charts (7d/30d/90d) for event volume, top tool calls, model usage, anomaly trend with reference lines, and detection counts. 5-minute Redis cache per agent per window.

### Compliance & Audit

- **Compliance report export**: HTML + PDF (WeasyPrint) with date range picker, admin-gated, audit-logged
- **SOC 2 audit log export**: Reproducible SHA-256 hash chain with GENESIS anchor, `verify_chain()` for offline auditor verification, CSV/JSON export with `X-Parry-Chain-Tip` header, monthly S3 auto-export
- **Full audit log**: Every mutating operation recorded with actor identity, action, resource, and structured details

### Alerting

Incident alerts via Slack webhook, PagerDuty (Events API v2), and OpsGenie (Alerts API). Minimum severity filter, test button per channel, masked secret display in settings.

### Team RBAC

Three roles (owner/admin/viewer) derived from Clerk organization membership. All mutating routes gated by `require_role`. Dashboard shows read-only badges for viewers.

### Billing & Plan Enforcement

Four tiers (Free/Growth/Pro/Enterprise) with limits on agents, events/month, retention, and feature gates. Stripe metered billing with daily event count reporting. 402 responses with `X-Upgrade-Required` trigger the dashboard's upgrade modal.

### SLO Tracking

Service Level Objectives for detection latency and false positive rates, with burn-rate alerting and a dedicated SLO dashboard page.

### SSO

Enterprise SAML SSO via WorkOS, layered on top of the standard Clerk auth flow. Per-org opt-in.

---

## Architecture

```
                         Your AI Agent
                              |
                              |  LLM call (sync or streaming)
                              v
                    +-------------------------+
                    |       Parry SDK          |
                    |                         |
                    |  7 framework wrappers   |
                    |  + MCP wrapper           |
                    |  + PII stripping        |
                    |  + fire-and-forget      |
                    |  + fail-open            |
                    +------------+------------+
                                 | async POST /api/v1/events/ingest
                                 | sync POST /api/v1/proxy/check (blocking mode)
                                 v
                    +-------------------------+          +--------------+
                    |    FastAPI Backend       |<-------->|  PostgreSQL  |
                    |                         |          |  TimescaleDB |
                    |  Auth: Clerk JWT        |          +--------------+
                    |      + API keys         |
                    |      + WorkOS SSO       |          +--------------+
                    |  Rate limiting          |<-------->|    Redis     |
                    |  Budget enforcement     |          +--------------+
                    +------------+------------+
                                 | Celery task
                                 v
                    +-------------------------+
                    |   Detection Pipeline     |
                    |                         |
                    |  11 detectors parallel   |
                    |  + LLM fallback          |
                    |  + Custom rules          |
                    |  + MCP manifest scan     |
                    |  + Cost exploit detect   |
                    |  + Policy enforcement    |
                    |  + Auto-baseline         |
                    +------------+------------+
                                 | persist results
                                 v
                    +-------------------------+
                    |   Incidents + Alerts     |
                    |                         |
                    |  Slack / PagerDuty /    |
                    |  OpsGenie dispatch       |
                    |  + SSE live stream       |
                    +------------+------------+
                                 |
                                 v
                    +-------------------------+
                    |    React Dashboard       |
                    |                         |
                    |  17 pages               |
                    |  Live event feed (SSE)  |
                    |  Session replay          |
                    |  Red team runs           |
                    |  MCP server registry     |
                    |  Cost + budget mgmt      |
                    |  Health scores           |
                    |  Behavioral charts       |
                    |  Policy regression       |
                    |  Compliance reports      |
                    |  Audit log               |
                    |  SLO tracking            |
                    +-------------------------+
```

---

## SDK

The SDK provides drop-in wrappers for seven AI frameworks:

| Wrapper | Framework | Import |
|---|---|---|
| `ParryOpenAI` | OpenAI | `from parry.wrappers.openai import ParryOpenAI` |
| `ParryAnthropic` | Anthropic | `from parry.wrappers.anthropic import ParryAnthropic` |
| `ParryCallbackHandler` | LangChain | `from parry.wrappers.langchain import ParryCallbackHandler` |
| `ParryCrewAI` | CrewAI | `from parry.wrappers.crewai import ParryCrewAI` |
| `ParryAutoGen` | AutoGen | `from parry.wrappers.autogen import ParryAutoGen` |
| `ParryLlamaIndex` | LlamaIndex | `from parry.wrappers.llamaindex import ParryLlamaIndex` |
| `ParryPydanticAI` | Pydantic AI | `from parry.wrappers.pydantic_ai import ParryPydanticAI` |
| `SentinelMCPClient` | MCP (stdio) | `from parry.mcp import SentinelMCPClient` |

All wrappers use lazy imports so the framework's package is only required if you use that specific wrapper. MCP support is an optional extra: `pip install parry[mcp]`.

**Sync client** (`ParryClient`) -- sends events in background threads, never blocks the caller.

**Async client** (`AsyncParryClient`) -- for async codebases. Uses `asyncio.create_task()` for fire-and-forget.

All wrappers strip PII (credit cards, SSNs, emails) client-side before sending events to the backend.

---

## Data Model

```
Org (tenant)
 |-- ApiKey[]              hashed keys, org-scoped
 |-- Agent[]               named AI processes with behavioral baselines
 |    |-- AgentSession[]   conversation/run grouping
 |    |-- AgentEvent[]     TimescaleDB hypertable (prompt, response, model, tool_calls,
 |    |                    latency, tokens, estimated_cost_usd)
 |    |    +-- Detection[] per-detector results (triggered, severity, confidence, reason)
 |    +-- AgentBudget[]    per-agent spend caps (hour/day/month period, Redis-enforced)
 |-- Incident[]            grouped detections requiring human review
 |-- Policy[]              allowed/blocked tools, domains, forbidden patterns, token budgets
 |-- MCPServer[]           MCP server registry (manifest, hash, trust level, reputation)
 |-- RedTeamRun[]          adversarial test runs against the detection pipeline
 |    +-- RedTeamResult[]  per-attack outcomes within a run
 +-- AuditLog[]            tamper-evident record of every mutation (hash-chained)
```

---

## API Endpoints

All routes under `/api/v1/`. Rate-limited per client via Redis sliding window. Interactive docs at `/docs/scalar`.

### Core

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/events/ingest` | SDK key | Ingest event with cost estimation (202) |
| `GET` | `/events` | Bearer | List events (cursor-paginated) |
| `GET` | `/events/live-stream` | Bearer | SSE blocked event feed |
| `POST` | `/proxy/check` | SDK key | Sync blocking check (detection + budget) |
| `POST` | `/proxy/scan-response` | SDK key | Response scanning (off/redact/block) |

### Agents

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET/POST` | `/agents` | Bearer | List / create agents |
| `GET/PATCH/DELETE` | `/agents/:id` | Bearer | Agent CRUD |
| `GET` | `/agents/:id/stats` | Bearer | Behavioral stats (7d/30d/90d) |
| `GET` | `/agents/:id/sessions` | Bearer | Session list |
| `GET` | `/agents/:id/spend` | Bearer | Current spend + budget status |

### Incidents & Detections

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/incidents` | Bearer | List incidents (filter by severity/status) |
| `PATCH` | `/incidents/:id` | Bearer | Update status (acknowledge/resolve/dismiss) |
| `GET` | `/sessions/:id` | Bearer | Session replay with detections |

### Policies & Rules

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET/POST/PATCH/DELETE` | `/policies[/:id]` | Bearer | Policy CRUD |
| `POST` | `/policies/simulate` | Bearer (admin) | Regression test a policy change |
| `GET/POST/PATCH/DELETE` | `/custom-rules[/:id]` | Bearer | Custom regex rule CRUD |
| `POST` | `/custom-rules/simulate` | Bearer (admin) | Regression test a custom rule |
| `POST` | `/custom-rules/test` | Bearer | Live regex test against sample text |

### Red Team

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/red-team/runs` | Bearer (admin) | Start a sandbox attack replay (202) |
| `GET` | `/red-team/runs` | Bearer | List runs (filter by agent) |
| `GET` | `/red-team/runs/:id` | Bearer | Run detail with failures |
| `GET` | `/red-team/attacks` | Bearer | Corpus summary (categories + counts) |

### MCP

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/mcp/connections` | SDK key | Register/refresh MCP server manifest |
| `GET` | `/mcp/servers` | Bearer | List MCP servers with trust levels |
| `GET` | `/mcp/servers/:id` | Bearer | Server detail (manifest, hash history) |
| `PATCH` | `/mcp/servers/:id` | Bearer (admin) | Update trust level |

### Budgets

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/budgets` | Bearer | List budgets for an agent |
| `PUT` | `/budgets` | Bearer (admin) | Upsert a budget cap |
| `DELETE` | `/budgets/:id` | Bearer (admin) | Remove a budget |

### Settings & Admin

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET/POST/DELETE` | `/api-keys[/:id]` | Bearer | API key management |
| `GET/PATCH` | `/alerts` | Bearer | Alert channel config (Slack/PD/OpsGenie) |
| `POST` | `/alerts/test` | Bearer (admin) | Send test alert |
| `GET/PATCH` | `/detector-config` | Bearer | Per-detector threshold tuning |
| `GET` | `/audit-log` | Bearer | Paginated audit log |
| `GET` | `/audit-log/export` | Bearer (admin) | SOC 2 hash-chained CSV/JSON export |
| `GET` | `/reports/compliance` | Bearer (admin) | Compliance report (HTML/PDF) |
| `GET` | `/billing/plan` | Bearer | Current plan + limits |
| `POST` | `/billing/checkout` | Bearer | Stripe checkout session |
| `GET` | `/slo` | Bearer | SLO status |
| `POST` | `/sso/login` | None | Initiate SAML SSO flow |

---

## Tech Stack

| Layer | Technology |
|---|---|
| **API** | FastAPI, Python 3.12, Pydantic v2 |
| **ORM** | SQLAlchemy 2.x (async), Alembic (14 migrations) |
| **Database** | PostgreSQL 16 + TimescaleDB |
| **Queue** | Redis 7, Celery 5 (7 task types + Beat scheduler) |
| **Detection** | 11 rule-based detectors + Claude LLM fallback |
| **Auth** | Clerk (JWT/JWKS), API keys (SHA256), WorkOS SAML SSO |
| **Billing** | Stripe (metered billing, checkout, portal, webhooks) |
| **Alerting** | Slack webhooks, PagerDuty Events API v2, OpsGenie Alerts API |
| **Dashboard** | React 18, TypeScript, Tailwind CSS, shadcn/ui, Recharts, TanStack Query + Router |
| **Real-time** | Server-Sent Events (blocked event feed, session polling) |
| **SDK** | Python, 7 framework wrappers + MCP wrapper, httpx |
| **Testing** | 644 tests total (529 backend, 90 SDK, 25 dashboard) |
| **CI** | GitHub Actions, pre-commit hooks (ruff + format + eslint) |
| **Infra** | Docker Compose (dev), multi-stage Dockerfiles (prod) |
| **Docs** | Scalar API reference at `/docs/scalar`, runbook, ADRs |

---

## Repo Structure

```
parry/
├── backend/
│   ├── app/
│   │   ├── main.py                        # FastAPI app, middleware, health check
│   │   ├── api/v1/                        # 21 route modules
│   │   │   ├── agents.py                  # CRUD + stats + spend
│   │   │   ├── budgets.py                 # Budget CRUD
│   │   │   ├── custom_rules.py            # Regex rules + simulate
│   │   │   ├── events.py                  # Ingest + list + SSE stream
│   │   │   ├── incidents.py               # List + status updates
│   │   │   ├── mcp.py                     # MCP connection + server registry
│   │   │   ├── policies.py                # CRUD + simulate
│   │   │   ├── proxy.py                   # Blocking check + response scan
│   │   │   ├── red_team.py                # Adversarial test runs
│   │   │   ├── sessions.py                # Session replay
│   │   │   └── ...                        # alerts, api_keys, audit, billing,
│   │   │                                  # detector_config, metrics, reports,
│   │   │                                  # slo, sso, webhooks
│   │   ├── core/
│   │   │   ├── config.py                  # Pydantic Settings
│   │   │   ├── dependencies.py            # Auth: Clerk JWT + API key + WorkOS SSO
│   │   │   ├── model_pricing.py           # 15-model pricing registry
│   │   │   ├── rate_limit.py              # Redis sliding window
│   │   │   ├── rbac.py                    # Role-based access control
│   │   │   └── event_bus.py               # Redis pubsub for SSE
│   │   ├── db/
│   │   │   ├── models.py                  # 12 SQLAlchemy models
│   │   │   └── session.py                 # Async engine + task session factory
│   │   ├── detection/
│   │   │   ├── pipeline.py                # Orchestrator: parallel detect -> LLM fallback
│   │   │   ├── base.py                    # BaseDetector protocol, DetectionResult
│   │   │   ├── registry.py                # 11 registered detectors
│   │   │   ├── mcp_normalize.py           # Canonical manifest hashing
│   │   │   ├── red_team_corpus.py         # Attack corpus loader + validator
│   │   │   ├── red_team_corpus/           # 48 attacks across 8 JSON category files
│   │   │   └── detectors/
│   │   │       ├── prompt_injection.py
│   │   │       ├── jailbreak.py
│   │   │       ├── tool_misuse.py
│   │   │       ├── data_exfil.py
│   │   │       ├── privilege_esc.py
│   │   │       ├── anomaly.py
│   │   │       ├── custom_rules.py
│   │   │       ├── mcp_manifest.py        # MCP injection + smuggling detection
│   │   │       ├── cost_explosion.py      # Loop / verbosity / model escalation
│   │   │       ├── policy_logic.py        # Pure policy evaluation
│   │   │       └── llm_fallback.py
│   │   ├── services/                      # 25 service modules
│   │   │   ├── detection_service.py       # Run pipeline + persist + incidents
│   │   │   ├── budget_service.py          # Redis rolling spend + DB cap enforcement
│   │   │   ├── mcp_service.py             # Server registry + trust lifecycle
│   │   │   ├── red_team_service.py        # Run lifecycle + scoring
│   │   │   ├── policy_regression_service.py  # Historical rule/policy simulation
│   │   │   ├── health_score_service.py    # Composite agent health (0-100)
│   │   │   ├── agent_stats_service.py     # Windowed behavioral charts
│   │   │   ├── alert_service.py           # Slack / PagerDuty / OpsGenie dispatch
│   │   │   ├── audit_export_service.py    # Hash-chained SOC 2 export
│   │   │   ├── report_service.py          # Compliance PDF generation
│   │   │   ├── session_service.py         # Session replay with content gating
│   │   │   ├── plan_service.py            # Plan limits + feature gates
│   │   │   └── ...                        # agent, api_key, baseline, billing,
│   │   │                                  # detector_config, event, incident,
│   │   │                                  # license, policy, slo, sso
│   │   └── workers/
│   │       ├── celery_app.py              # Task registry + Beat schedule
│   │       ├── detection_task.py          # Per-event detection (retry + timeout)
│   │       ├── red_team_task.py           # Sandbox corpus replay
│   │       ├── health_score_task.py       # Hourly score refresh
│   │       ├── baseline_refresh_task.py   # Hourly baseline recompute
│   │       ├── metered_usage_task.py      # Daily Stripe usage reporting
│   │       └── audit_export_task.py       # Monthly S3 audit export
│   ├── alembic/versions/                  # 14 migrations
│   ├── tests/                             # 529 tests
│   └── Dockerfile
├── sdk/
│   ├── parry/
│   │   ├── client.py                      # Sync client (background threads)
│   │   ├── async_client.py                # Async client (asyncio tasks)
│   │   ├── interceptor.py                 # PII stripping, intercept_completion()
│   │   ├── response_scanner.py            # Client-side response scan
│   │   ├── blocking.py                    # ParryBlockedError for /proxy/check
│   │   ├── wrappers/
│   │   │   ├── openai.py                  # ParryOpenAI
│   │   │   ├── anthropic.py               # ParryAnthropic
│   │   │   ├── langchain.py               # ParryCallbackHandler
│   │   │   ├── crewai.py                  # ParryCrewAI
│   │   │   ├── autogen.py                 # ParryAutoGen
│   │   │   ├── llamaindex.py              # ParryLlamaIndex
│   │   │   └── pydantic_ai.py             # ParryPydanticAI
│   │   └── mcp/
│   │       ├── client.py                  # SentinelMCPClient (stdio transport)
│   │       ├── normalize.py               # Client-side manifest hashing
│   │       └── errors.py                  # MCPBlockedError, MCPManifestError
│   ├── tests/                             # 90 tests
│   └── pyproject.toml
├── dashboard/
│   ├── src/
│   │   ├── pages/                         # 17 pages
│   │   │   ├── DashboardPage.tsx          # Overview + fleet health + live feed
│   │   │   ├── AgentDetailPage.tsx        # Health + cost + stats + sessions
│   │   │   ├── IncidentsPage.tsx          # Incident management
│   │   │   ├── CustomRulesPage.tsx        # Rule editor + regression preview
│   │   │   ├── PoliciesPage.tsx           # Policy editor + regression preview
│   │   │   ├── RedTeamPage.tsx            # Attack replay runs
│   │   │   ├── RedTeamRunDetailPage.tsx   # Score + category breakdown + failures
│   │   │   ├── MCPServersPage.tsx         # Server list + trust filter
│   │   │   ├── MCPServerDetailPage.tsx    # Trust controls + manifest + hash history
│   │   │   ├── SessionReplayPage.tsx      # Event timeline with detections
│   │   │   ├── ReportsPage.tsx            # Compliance PDF export
│   │   │   ├── AuditLogPage.tsx           # Full audit trail + hash export
│   │   │   ├── SLOPage.tsx                # SLO tracking
│   │   │   ├── SettingsPage.tsx           # Alerts + API keys + plan + detector config
│   │   │   └── ...
│   │   ├── components/
│   │   │   ├── charts/                    # Recharts: severity, trend, sparklines, heatmap
│   │   │   ├── RegressionPreviewPanel.tsx # Debounced simulation with by-agent/day charts
│   │   │   ├── MatchSampleList.tsx        # Inline highlight of matched spans
│   │   │   ├── RedTeamScoreCard.tsx       # Hero score + grade display
│   │   │   ├── RedTeamCategoryBreakdown.tsx # Per-category detection bars
│   │   │   ├── CostCard.tsx               # Spend display + budget progress bars
│   │   │   ├── BudgetEditor.tsx           # Budget CRUD modal
│   │   │   ├── ModelSpendBreakdown.tsx    # Per-model horizontal bars
│   │   │   ├── HealthScoreBadge.tsx       # Score + grade badge
│   │   │   ├── BlockedEventFeed.tsx       # Live SSE blocked events
│   │   │   └── ui/                        # shadcn/ui + toast system
│   │   ├── hooks/                         # 15 TanStack Query hooks
│   │   └── lib/                           # API client, types, chart theme
│   ├── src/__tests__/                     # 25 Vitest tests
│   └── vitest.config.ts
├── docs/
│   ├── architecture.md
│   ├── detection-engine.md
│   ├── api-spec.md
│   ├── schema.md
│   ├── runbook.md
│   ├── mvp-checklist.md
│   └── adr/                               # Architecture Decision Records
├── .github/workflows/
│   ├── ci.yml                             # Backend + SDK + dashboard + migrations
│   └── publish-sdk.yml                    # Tag-driven PyPI publish
├── docker-compose.yml                     # Dev (hot reload, debug ports)
├── docker-compose.prod.yml                # Prod (nginx, restart policies)
├── .env.example
└── CLAUDE.md                              # AI assistant context
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
| Scalar API Docs | http://localhost:8000/docs/scalar | - |
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
# Backend (529 tests)
cd backend && uv run pytest

# SDK (90 tests)
cd sdk && uv run pytest

# Dashboard (25 tests)
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
