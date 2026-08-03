# Parry

Runtime security for AI agents. Parry sits between your AI agents and the LLMs they call, detecting prompt injection, data exfiltration, tool misuse, cost exploitation, and anomalous behavior in real time.

## What is Parry?

AI agents are powerful but dangerous. They execute tool calls, handle sensitive data, and operate with broad permissions. A single prompt injection can hijack an agent's actions. A misconfigured tool policy can leak customer data. A compromised MCP server can inject instructions into every tool description your agent reads. A runaway loop can burn thousands of dollars in LLM costs in minutes.

Parry is a security layer that monitors every LLM call your agents make. Lightweight SDKs for **Python**, **TypeScript**, and **Go** wrap your existing LLM clients. Every prompt and response flows through a detection pipeline of 12 specialized detectors, policy enforcers, permission boundaries, a cross-org threat intelligence feed, and an LLM-powered fallback classifier. When something looks wrong, Parry creates an incident, alerts your team, optionally blocks the call in real time, and provides forensic replay for investigation.

Parry also finds the AI you *haven't* instrumented. A read-only SSO connection surfaces the AI systems your people already authorized — no code, no install — and files them into your EU AI Act register. See [Shadow AI Discovery](#shadow-ai-discovery).

The SDKs add zero latency to your agent's calls. Events are sent asynchronously in the background. If Parry's backend goes down, your agent keeps running. Fail-open by design.

**Python — two lines to integrate:**

```python
import parry
parry.init(api_key="sk-parry-...")

from parry.wrappers.openai import ParryOpenAI
client = ParryOpenAI()  # drop-in replacement for openai.OpenAI()
```

**TypeScript:**

```typescript
import OpenAI from "openai";
import { ParryClient, parryOpenAI } from "@parry/sdk";

const parry = new ParryClient({ apiKey: "sk-parry-..." });
const openai = parryOpenAI(new OpenAI(), parry);
```

**Go:**

```go
parryClient := parry.NewClient("sk-parry-...", parry.WithAgentID("my-agent"))
wrapped := parry.WrapOpenAI(parryClient, yourCallFn, parry.WrapOptions{})
resp, err := wrapped(ctx, req)
```

---

## Features

### Shadow AI Discovery

Find the AI systems already running in your environment that nothing is monitoring — **without installing anything or changing a line of your agent code**.

Connect a read-only Okta token and Parry reads the app grants your org has already issued, matches them against a 200-vendor catalog, and returns the AI systems present in your environment with no Parry agent attached:

```
Shadow AI — 10 systems nothing is monitoring, 3 of them high risk:
  high*      Eightfold AI       Eightfold AI, Inc.    2026-01-19
  high*      HireVue            HireVue, Inc.         2025-11-03
  high*      Beamery            Beamery, Inc.         2025-01-23
  limited*   GitHub Copilot     Microsoft             2025-03-08
  ...
* proposed from the vendor catalog, pending human review
```

Discovered systems land in the EU AI Act Article 26 register as `origin='discovered'`. The catalog's suggested risk tier arrives as a **proposal, never an approved classification** — a machine's guess at an Annex III tier is a draft for a human, not a compliance fact. Approving one promotes it to the system's tier of record and raises the Article 27 FRIA obligation, so discovery feeds the compliance workflow directly.

Unrecognized apps are kept as probe events for triage but never enter the register: if we can't say what something is, it doesn't get a compliance record.

### Detection Engine

12 detectors run in parallel on every event:

| Detector | What it catches | Method |
|---|---|---|
| **Prompt Injection** | "Ignore previous instructions", fake system prompts | 10 regex patterns, confidence-weighted |
| **Jailbreak** | DAN, developer mode, persona hijacks | 8 known jailbreak families |
| **Tool Misuse** | Tools outside policy allowlist/blocklist | Policy comparison |
| **Data Exfiltration** | Credit cards, SSNs, API keys, credentials in responses | 6 PII/secret patterns |
| **Privilege Escalation** | sudo/admin claims, disable auth/logging | 6 escalation patterns |
| **Anomaly** | Token/latency drift (3-sigma), unknown models, excessive tool calls | Statistical baseline comparison |
| **Custom Rules** | Org-defined regex patterns | Per-org rules with severity + target |
| **MCP Manifest** | Injection, jailbreaks, unicode smuggling in MCP tool descriptions | 6 pattern categories |
| **Cost Exploit Loop** | Identical tool calls repeated in rapid succession | Session history analysis |
| **Cost Exploit Verbosity** | Response tokens >10x baseline mean | Statistical comparison |
| **Cost Exploit Model Escalation** | Sudden switch to 3x+ more expensive model | Pricing comparison |
| **Threat Intelligence** | Patterns confirmed across 3+ organizations in the Parry network | Cross-org threat feed matching |
| **LLM Fallback** | Ambiguous cases (0.4-0.7 confidence) | Claude-powered classification |

### Agent Permission Boundaries

Define what each agent is allowed to do — allowlist/blocklist tool calls with deny-by-default mode. Enforced at the proxy layer independently of blocking mode. Three modes: **enforcing** (blocks violations), **dry_run** (logs only), **disabled**.

Permission resolution: agent-specific → group → org default → allow-all.

```
ParryPermissionDeniedError: Tool 'delete_database' is explicitly blocked
```

### Cross-Agent Threat Intelligence

Anonymized detection patterns aggregated across all Parry customers. When an attack pattern is confirmed across 3+ organizations, the `ThreatIntelDetector` fires for every org automatically. Pattern signatures decay over 30 days without re-sighting. Org-level opt-out for sharing while still consuming the feed.

### Agent Behavior Anomaly Replay

Forensic attack chain reconstruction for every incident. Smart windowing surfaces the 50 most relevant events around the trigger, annotated with detections, permission violations, and threat intel matches. Click "Replay" on any incident to see exactly what happened.

### Active Blocking + Budget Enforcement

Pre-call blocking via `/proxy/check` returns `allowed=false` for HIGH/CRITICAL detections. Budget enforcement blocks calls when rolling spend hits 95% of cap (hourly/daily/monthly).

### MCP Server Security

First security layer for the Model Context Protocol. `SentinelMCPClient` wraps MCP connections, scans manifests for injection and unicode smuggling, tracks server identity via manifest hashing, and enforces trust levels.

### Webhook Subscriptions

Register webhook URLs to receive HMAC-signed HTTP POST notifications for: `detection.triggered`, `incident.created`, `incident.resolved`, `permission.denied`, `threat_intel.match`, `budget.exceeded`. Retry with exponential backoff, delivery history for debugging.

### Agent Groups

Organize agents into named groups with inherited permissions and policies. Groups inherit org-wide defaults unless overridden.

### EU AI Act Article 26 Compliance

Full deployer obligations platform: AI System Register, FRIA generator (8-section template auto-populated from org data), serious incident reporting with 15-day Art. 73 deadline tracking, compliance posture dashboard (7 obligations), and auditor bundle ZIP export.

### Scheduled Security Reports

Automated weekly/monthly email digests with PDF attachment. Summarizes detections, incidents, and posture changes for the period.

### Red Team Your Agent

One-click adversarial testing against 48 attacks across 8 categories. Sandbox mode replays through the live detection pipeline without burning LLM tokens.

### Session Replay + Response Scanning + Health Scores + SLOs

Full event timeline replay, three-mode response scanning (off/redact/block), composite agent health scores (0-100, A-F), and service-level objective tracking.

### Enterprise

- **SSO**: SAML via WorkOS, layered on Clerk auth, self-service IdP configuration via Admin Portal
- **RBAC**: Three roles (owner/admin/viewer) with fine-grained route gating
- **Billing**: Four tiers (Free/Growth/Pro/Enterprise) with Stripe metered billing
- **Audit**: Tamper-evident hash-chained audit log with SOC 2 export
- **Compliance**: EU AI Act Article 26 module with auditor bundle

---

## Architecture

```
                         Your AI Agent
                              |
                              |  LLM call
                              v
                    +-------------------------+
                    |       Parry SDK          |
                    |  Python / TypeScript / Go|
                    |  8 framework wrappers    |
                    |  + MCP wrapper           |
                    |  + fail-open             |
                    +------------+------------+
                                 | async ingest + sync proxy check
                                 v
                    +-------------------------+          +--------------+
                    |    FastAPI Backend       |<-------->|  PostgreSQL  |
                    |  Auth / Rate Limiting    |          |  TimescaleDB |
                    |  Budget Enforcement      |          +--------------+
                    |  Permission Boundaries   |
                    +------------+------------+          +--------------+
                                 |                  <--->|    Redis     |
                                 v                       +--------------+
                    +-------------------------+
                    |   Detection Pipeline     |
                    |  12 detectors parallel   |
                    |  + Threat intel feed     |
                    |  + Permission check      |
                    |  + LLM fallback          |
                    +------------+------------+
                                 |
                    +------------+------------+
                    |  Incidents + Alerts      |  Webhooks
                    |  Slack / PagerDuty /     |  HMAC-signed
                    |  OpsGenie / Webhooks     |  HTTP POST
                    +------------+------------+
                                 |
                    +-------------------------+
                    |    React Dashboard       |
                    |  20+ pages               |
                    |  Forensic replay         |
                    |  Threat intel feed       |
                    |  Compliance module       |
                    |  Permission management   |
                    +-------------------------+
```

---

## SDKs

### Python SDK (`pip install parry`)

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

### TypeScript SDK (`npm install @parry/sdk`)

```typescript
import { ParryClient, parryOpenAI, ParryBlockedError, ParryPermissionDeniedError } from "@parry/sdk";
```

Drop-in OpenAI wrapper via `parryOpenAI()`. ESM + CJS dual build.

### Go SDK (`go get github.com/smhasan94/parry/sdk-go`)

```go
import parry "github.com/smhasan94/parry/sdk-go"

client := parry.NewClient("sk-parry-...", parry.WithAgentID("my-agent"))
```

Library-agnostic OpenAI wrapper via `WrapOpenAI()` callback pattern. Includes `VerifyWebhookSignature()` helper for webhook handlers.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **API** | FastAPI, Python 3.12, Pydantic v2 |
| **ORM** | SQLAlchemy 2.x (async), Alembic (20 migrations) |
| **Database** | PostgreSQL 16 + TimescaleDB |
| **Queue** | Redis 7, Celery 5 (12 task types + Beat scheduler) |
| **Detection** | 12 rule-based detectors + Claude LLM fallback + cross-org threat feed |
| **Auth** | Clerk (JWT/JWKS), API keys (SHA256), WorkOS SAML SSO |
| **Billing** | Stripe (metered billing, checkout, portal, webhooks) |
| **Alerting** | Slack, PagerDuty, OpsGenie, custom webhooks (HMAC-signed) |
| **Dashboard** | React 18, TypeScript, Tailwind CSS, shadcn/ui, Recharts, TanStack Query + Router |
| **SDKs** | Python (8 wrappers), TypeScript (ESM/CJS), Go |
| **Testing** | 700+ tests (backend unit + E2E, Python SDK, TypeScript SDK, Go, dashboard) |
| **CI** | GitHub Actions, pre-commit hooks (ruff + format + eslint) |
| **Infra** | Docker Compose (dev), multi-stage Dockerfiles (prod) |

---

## Running Locally

### Prerequisites

- Docker + Docker Compose
- Python 3.12+
- Node.js 20+
- Go 1.22+ (for Go SDK development)
- [uv](https://docs.astral.sh/uv/) (`pip install uv` or `brew install uv`)

### Docker Compose (recommended)

```bash
git clone https://github.com/smhasan94/parry.git
cd parry

cp .env.example .env
# Set ANTHROPIC_API_KEY, CLERK_SECRET_KEY, CLERK_PUBLISHABLE_KEY

cp dashboard/.env.example dashboard/.env
# Set VITE_CLERK_PUBLISHABLE_KEY

docker compose up -d
docker compose exec backend uv run python scripts/seed.py

curl http://localhost:8000/health
```

To see Shadow AI Discovery without wiring up a real Okta tenant, seed the
demo tenant — 18 apps and 410 grants driven through the live pipeline,
nothing stubbed:

```bash
docker compose exec backend uv run python scripts/seed_catalog.py
docker compose exec backend uv run python scripts/seed_shadow_ai_demo.py
# then open the dashboard at /shadow-ai
```

| Service | URL |
|---------|-----|
| Backend API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs/scalar |
| Dashboard | http://localhost:5173 |

### Running Tests

```bash
# Backend (600+ unit tests)
cd backend && uv run pytest

# Python SDK (90 tests)
cd sdk && uv run pytest

# TypeScript SDK (19 tests)
cd sdk-ts && npm test

# Go SDK (14 tests)
cd sdk-go && go test ./...

# Dashboard
cd dashboard && npm test

# E2E (requires test Postgres on port 5434)
cd backend && uv run pytest tests/e2e/
```

---

## License

MIT
