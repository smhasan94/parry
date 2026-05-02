# Changelog

All notable changes to Parry are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project follows [Semantic Versioning](https://semver.org/) once a
1.0 ships. Pre-1.0 releases may break compatibility on any minor
version bump — read the entries.

## [Unreleased]

### Added — Detection engine

- **Active blocking mode** — `/proxy/check` returns a verdict before
  the LLM call so detected attacks can be blocked inline instead of
  flagged after the fact. SDKs raise `ParryBlockedError`.
- **Response scanning** — `/proxy/scan-response` with off / redact /
  block modes. Forensics always sees the original payload.
- **Custom detection rules** — org-defined regex / keyword rules
  with full CRUD and a live-preview test endpoint.
- **MCP server security layer** — manifest fingerprinting, six
  injection categories, observed → trusted → suspicious → blocked
  trust state machine, hash-stable canonicalisation across Python
  and TypeScript SDKs. See [docs/mcp-security.md](docs/mcp-security.md).
- **Cost exploitation detectors** — loop, verbosity-explosion, and
  model-escalation detectors with per-agent budget enforcement and
  threshold alerts.
- **Threat intel feed** — cross-org pattern aggregation with score
  decay (~14-day half-life), `ThreatIntelDetector` checks every
  event against the active feed.
- **Red team runner** — replay a 48-attack corpus through the live
  detection pipeline. Sandbox mode ships now; live mode on the
  roadmap. See [docs/red-team.md](docs/red-team.md).
- **LLM fallback detector** — Claude Sonnet classifies events whose
  rule-based score is ambiguous (0.4–0.7).

### Added — Compliance

- **EU AI Act Article 26 module** — AI system register, supplier
  auto-population, FRIA generator with approval workflow,
  Article 73 serious incident reporting with 15-day deadline
  tracking, compliance posture across 7 obligations, auditor
  bundle ZIP export.
- **SOC 2 audit log export** — reproducible SHA-256 hash chain
  with offline `verify_chain()`, admin-gated CSV/JSON export, and
  a monthly S3 export task.
- **Compliance report PDF** — admin-gated date-range export with
  90-day sync cap and audit logging.
- **Policy regression simulator** — preview a custom rule or
  policy against historical events before enabling it.

### Added — Platform

- **Team RBAC** — viewer / admin / owner roles with route-level
  gating and a read-only badge in the dashboard.
- **Agent health score** — composite grade with hourly Redis-cached
  refresh and a per-agent component breakdown.
- **Agent behavioural graph** — five windowed series (event volume,
  tool calls, model usage, anomaly trend, detection counts) with
  5-minute Redis caching.
- **Real-time blocked-event SSE feed** — pause / resume / clear
  controls in the dashboard, 5-stream-per-org cap.
- **Session replay** — timeline view with severity-coloured borders,
  live polling, role-aware content gating.
- **Permission boundaries** — per-agent (or org-default) tool
  allow/blocklists with enforcing / dry-run / disabled modes.
- **Anomaly replay** — forensic timeline reconstruction for
  incidents (smart windowing, detections, permission violations,
  threat-intel hits).
- **Billing plan enforcement** — Free / Growth / Pro / Enterprise
  with per-plan limits on agents, monthly events, retention,
  custom rules, and compliance export. Stripe-driven plan
  transitions via webhook.
- **Alerts integrations** — PagerDuty (Events API v2 dedup) and
  Opsgenie (P1–P5 mapping) on top of existing email + Slack.
- **WorkOS SAML SSO** — opt-in enterprise SAML on top of Clerk.
  See [docs/sso.md](docs/sso.md).
- **On-prem mode** — air-gapped deployment with a signed Ed25519
  license file, no outbound calls, hard-fail on license verify
  failure. See [docs/on-prem.md](docs/on-prem.md).

### Added — SDKs

- **Python (`parry`)** — wrappers for OpenAI, Anthropic, LangChain,
  CrewAI, AutoGen, LlamaIndex, Pydantic AI; `SentinelMCPClient` for
  MCP; streaming support; fail-open by default.
- **TypeScript (`@parry/sdk`)** — full Python parity plus a
  duck-typed LangChain.js callback handler. Streaming on OpenAI and
  Anthropic. MCP normalize.ts is byte-identical to Python.
- **Go (`github.com/sharukhhasan/parry/sdk-go`)** — core client +
  OpenAI wrapper.

### Added — Operational

- Tag-driven publish workflows for PyPI (`sdk/v*`) and npm
  (`sdk-ts/v*`).
- CI jobs for backend (unit + e2e + migrations), Python SDK,
  TypeScript SDK, Go SDK, dashboard, and the landing site.
- Pre-commit hooks: ruff, ruff-format, dashboard ESLint, hygiene.
- Scalar API reference at `/docs/scalar`.
- On-call runbook ([docs/runbook.md](docs/runbook.md)).

### Security

- Replaced `python-jose` with `PyJWT` to remediate
  CVE-2024-33663 / CVE-2024-33664.
- Manifest hashes for MCP servers ignore volatile fields
  (`serverInfo.version`, `_meta`) so version bumps don't trigger
  drift, but **any other change** auto-demotes a `trusted` server
  to `observed`.

### Internal

- 800+ backend tests covering the detection engine, services, RBAC,
  billing, FRIA / Article 73 workflows, and MCP. 90+ Python SDK
  tests, 92+ TypeScript SDK tests.
- Mypy strict mode across `backend/app/`.
- TimescaleDB hypertable for `agent_events` with required
  `agent_id` + time-range filtering enforced via review.

---

## How to read this file

We add to the **Unreleased** section as work merges to `main`. When
we cut a release, the section is renamed to the version with a
date, and a fresh **Unreleased** section starts at the top.

Categories follow Keep a Changelog conventions:

- **Added** — new capabilities
- **Changed** — behaviour of existing capabilities (breaking or not)
- **Deprecated** — features still working but slated for removal
- **Removed** — features deleted
- **Fixed** — bug fixes
- **Security** — vulnerabilities patched
