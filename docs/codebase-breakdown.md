# Parry — Codebase Breakdown

Verified against the tree at `main` (352800e). Every number below came from a command, not from the README. Where README claims diverge from code, I flag it — those are the ones that bite in interviews.

---

## 1. What it does

Parry is a **runtime security layer for AI agents** — it sits between an agent and the LLM it calls. SDKs (Python/TypeScript/Go) wrap the LLM client; every prompt/response/tool-call flows to a FastAPI backend that runs a 12-detector pipeline for prompt injection, data exfiltration, tool misuse, privilege escalation, cost-exploit loops, and behavioral drift. Detections group into incidents, fire webhooks/Slack/PagerDuty, and can **block the call pre-flight** via a synchronous check endpoint.

Buyer: security/compliance teams at B2B companies running production AI agents. Second value prop layered on top: **Shadow AI Discovery** — a read-only Okta token surfaces AI SaaS your org already authorized but nothing monitors, matched against a 200-vendor catalog, filed into an EU AI Act Article 26 register.

---

## 2. Architecture — request flow

Two distinct paths. Confusing them is the most likely interview stumble.

### Path A — async ingest (default, zero added latency)

```
Agent → SDK wrapper → interceptor.strip_pii() → background thread
     → POST /api/v1/events/ingest  (202 Accepted)
     → event_service.ingest_event() → agent_events (TimescaleDB hypertable)
     → Celery .delay() → detection_task
     → DetectionPipeline.run() — 13 detectors in a ThreadPoolExecutor
     → ambiguous (0.4–0.7 conf) → Claude LLM fallback
     → persist Detection rows → _create_or_update_incident()
     → webhooks + alerts + threat-intel extraction (conf ≥ 0.7)
```

### Path B — synchronous blocking (opt-in, hot path)

```
Agent → SDK → POST /api/v1/proxy/check (always 200; decision in body)
     → permission boundary check (runs regardless of blocking_enabled)
     → policy load (Redis, 30s TTL) → run_blocking_check()
     → budget check → {allowed: bool}
```

### Key pieces

| File | Role |
|---|---|
| `backend/app/main.py:52` | FastAPI app; lifespan does prod-config validation, Sentry, on-prem license load, graceful pool drain |
| `backend/app/api/v1/router.py` | Aggregates **33** routers; **152** route handlers across `api/v1/` |
| `backend/app/api/v1/events.py:31` | `POST /ingest` — 202, quota check, Celery dispatch |
| `backend/app/api/v1/events.py:122` | Org-wide SSE `live-stream` off a Redis pubsub bus; per-org cap of 5 connections |
| `backend/app/api/v1/proxy.py:271` | `POST /check` — the blocking hot path. Documented budget: p99 < 10ms |
| `backend/app/detection/pipeline.py:26` | Fan-out of sync detectors via `loop.run_in_executor` + `asyncio.gather` |
| `backend/app/detection/base.py:29` | `BaseDetector` — a `@runtime_checkable` Protocol, not an ABC |
| `backend/app/detection/registry.py:18` | The 12-detector list, instantiated once at import |
| `backend/app/services/detection_service.py:19` | Orchestrator: policy merge → pipeline → persist → incident → webhooks → alerts → baseline autogen |
| `backend/app/db/models.py` | 1,247 lines, **32 tables** |
| `backend/app/db/models.py:225` | `AgentEvent` — composite PK `(id, timestamp)` required for Timescale partitioning |
| `backend/app/core/dependencies.py:88` | API-key auth: SHA-256 hash lookup. Clerk JWT path derives the JWKS URL by base64-decoding the publishable key (`:48`) |
| `backend/app/workers/celery_app.py:101` | Beat schedule — 11 cron entries, deliberately ordered (discovery 02:00 → compliance 03:00) |
| `sdk/parry/interceptor.py:28` | Fail-open contract, explicitly documented: "this function MUST NEVER raise" |
| `sdk/parry/client.py:62` | Fire-and-forget via a daemon `threading.Thread` per event |

---

## 3. Key technical decisions

### 3.1 Two enforcement paths that must agree — and the duplication that admits it

Async ingest (Celery) and sync blocking (proxy) each need a merged org policy. `proxy.py:54 _merge_policies` is a **deliberate copy** of `detection_service.py:198 _merge_policies`, with a comment saying so: *"Mirrors detection_service._merge_policies so the blocking path enforces the same rules as the async ingest path."*

- **Tradeoff:** two implementations that can drift, in exchange for the blocking path never importing the Celery/detection stack into its hot path.
- **Not taken:** running the full pipeline synchronously on every call. That would put Postgres + 13 detectors + a possible Claude call in the caller's latency budget, destroying the "zero added latency" claim.
- **Interview risk:** an interviewer will ask "why not extract the shared function?" The honest answer is that it *should* be extracted — the duplication is a known cost, mitigated by `tests/test_merge_policies.py`.

### 3.2 Protocol over ABC for detectors

`BaseDetector` is a `typing.Protocol` (`detection/base.py:29`), and `DetectionResult` uses `__slots__` (`:9`).

- **Why:** detectors are structurally typed and stateless — no inheritance, no registration decorator, no base-class constructor. A detector is any object with `name: str` and `detect(event_data) -> DetectionResult`.
- **Tradeoff:** no enforced base behavior; a detector that forgets `name` fails at registry construction, not at definition.
- **Not taken:** ABC + `@register` decorator. That would have coupled every detector to an import of the registry, creating cycles with `detector_config_service`.

### 3.3 Baseline quality gating in the anomaly detector

The most non-obvious code in the repo (`detection/detectors/anomaly.py`). A naive 3-sigma check on a small sample fires constantly. This one:

- Computes sigma with a **zero-std fallback** to a mean-relative ratio (`:16`), so `std=0` doesn't divide by zero.
- Multiplies the configured threshold by a **quality multiplier** — `{high: 1.0, medium: 1.33, low: inf}` (`:13`). A low-quality baseline literally never fires.
- Separates **categorical** signals (unknown model, unknown tool, excessive tool count) from **continuous** drift; categorical bypasses the sigma gate (`:173`).
- Serializes `inf` as the string `"inf"` because asyncpg rejects `Infinity` in a JSONB column (`:185–195`) — a real bug fix, documented in place.
- Emits drift as a Prometheus histogram **even on non-triggered events** (`detection_service.py:78`) so thresholds can be tuned from live traffic.
- **Not taken:** a fixed 3-sigma constant. The multiplier table exists because the naive version was too noisy on cold agents.

### 3.4 Fail-open everywhere, by explicit contract

The SDK swallows all exceptions (`interceptor.py:48–66`), the proxy returns `allowed=true` on error, `/check` always returns 200 so the SDK never distinguishes transport failure from a policy decision (`proxy.py:6–9`), and Redis being down is quiet.

- **Tradeoff:** a Parry outage becomes a **silent security gap**, not an agent outage.
- **Not taken:** fail-closed. For a product that intercepts production LLM calls, breaking the customer's agent is worse than missing detections. This is the single most defensible product decision in the codebase, and worth leading with.
- **Notable exception:** credential encryption fails *closed*. With no `PROBE_ENCRYPTION_KEY`, storage is refused rather than falling back to plaintext (CHANGELOG, Security section).

### 3.5 SSE pubsub decoupled from the keepalive timer

`api/v1/events.py:143–188`. The comment records an actual asyncio investigation: cancelling `wait_for` on the subscription's `__anext__` terminates the async generator (a cancelled `__anext__` makes the *next* call raise `StopAsyncIteration`). Fix: run the subscriber on its own task feeding a bounded `asyncio.Queue(maxsize=256)`, drop-oldest on full, keepalive every 15s. This is the highest-signal 40 lines in the repo for a staff-level conversation.

---

## 4. Scale & complexity

| Metric | Value | Source |
|---|---|---|
| Source LOC (excl. tests/deps) | **51,997** | `backend/app` + `sdk/parry` + `sdk-ts/src` + `sdk-go` + `dashboard/src` + `landing/src` |
| Backend app LOC | 26,586 across `backend/app` | |
| Backend total Python (incl. tests, alembic, scripts) | 48,142 across 322 files | |
| Backend test LOC | 17,681 | ~40% of backend Python is tests |
| Dashboard TS/TSX | 17,639 | |
| Commits | **491**, 2026-04-01 → 2026-08-05 (~4 months) | single author, two git identities |
| API route handlers | **152** across 33 routers | |
| Services layer | **48** modules in `app/services/` | |
| Detectors | **12** registered + 1 LLM fallback | `registry.py:18` |
| DB tables | **32** | `models.py`, 1,247 lines |
| Alembic migrations | **23** (001–023) | linear, no branches |
| Celery tasks | **16** task modules, **11** beat entries | |
| Dashboard pages | **28** | `dashboard/src/pages/` |
| SDKs | 3 languages; Python has **7 framework wrappers** + MCP client | `sdk/parry/wrappers/` |
| Vendor catalog | **200** entries | `catalog/services.json`, verified by parse |
| Red-team corpus | **48** attacks, 8 categories × 6 | verified by parse of `red_team_corpus/*.json` |
| Benchmark corpus | 42 attacks / 7 categories + 10 clean (FP check) | `benchmark_service.py:11` |
| Backend dependencies | 24 production | `backend/pyproject.toml` |
| Python SDK dependencies | **1 required** (`httpx`) + 8 optional extras | deliberate — SDK stays light |

### Tests — the README undercounts

| Suite | Count | Method |
|---|---|---|
| Backend | **1,148** test functions | `grep -c "def test_"` |
| Backend E2E | 33 files in `tests/e2e/` | separate CI job, real Postgres |
| Python SDK | 98 | |
| TypeScript SDK | 92 | |
| Go SDK | 16 | |
| Dashboard | 22 test files (Vitest, v8 coverage) | |
| **Total** | **~1,350+ test functions** | README says "700+" — stale, revise **upward** |

Coverage gate: `--cov-fail-under=50` on backend unit tests (`ci.yml`). The comment says this is the unit-test floor because E2E runs in a separate job and coverage isn't combined. **Do not claim 80% coverage** — the enforced number is 50%.

---

## 5. Status — honest read

**Late-prototype / pre-first-customer, with production-grade engineering hygiene.** Precisely: the *engineering* is production-hardened; the *deployment* is not.

**Evidence for maturity:**
- CI (`ci.yml`) runs **8 parallel jobs**: backend unit+coverage, backend E2E, migrations, Python SDK, dashboard, landing, TS SDK, Go SDK. The migrations job asserts expected tables exist *and* that the alembic head matches the newest migration file — a genuinely uncommon check.
- `mypy` configured `strict = true` (`backend/pyproject.toml`).
- Pre-commit hooks, `SECURITY.md` with disclosure policy, `CONTRIBUTING.md`, Keep-a-Changelog `CHANGELOG.md`, 4 compose files (dev/prod/small/onprem), Caddyfile with CSP, Sentry + Prometheus wired.
- Deploy pipeline exists (`deploy.yml`) with health gate, rollback, concurrency lock, and a deploy-ref allowlist regex to prevent SSH command injection.
- On-prem licensing module with fatal-on-tamper verification (`core/on_prem.py`).

**Evidence against "shipped":**
- **Not published.** `publish-sdk.yml` triggers on `sdk/v*` tags; `publish-sdk-ts.yml` on `sdk-ts/v*`. The only tag in the repo is `v0.1.0`. Neither publish workflow has ever fired → **not on PyPI, not on npm**. The PyPI job even notes trusted publishing isn't configured yet.
- **Deploy is gated off.** `deploy.yml` requires `vars.DEPLOY_ENABLED == 'true'`, added specifically because "until a host exists and its secrets are set, this workflow would fail on every push to main."
- All versions are `0.1.0` (backend, SDK, TS SDK, FastAPI app).
- **Sole contributor**, 491 commits, one 4-month window. No external users, issues, or PR reviewers — all 10 PRs are self-merged.

**Say:** "Built solo over four months; ~52k lines, 1,300+ tests, full CI across five packages, deploy pipeline built and gated pending a host. Not yet published or serving traffic."
**Don't say:** "in production," "used by customers," "available on PyPI."

---

## 6. Differentiation

No competitor is named anywhere in README, docs, or landing copy — so this is inferred from architecture, not quoted. Three things are genuinely unusual:

1. **Runtime interception, not a gateway.** Lakera/Rebuff-style tools classify a prompt you hand them. Parry wraps the *client* and sees the full call — prompt, response, tool calls, latency, token count, model — which is what makes the anomaly, cost-exploit, and tool-misuse detectors possible at all. A prompt classifier structurally cannot detect "identical tool call repeated 10× in 20 events" (`cost_explosion.py:49–59`) or "model escalated to a 3× more expensive tier."

2. **Cross-org threat intelligence with anonymization** (`services/threat_intel_service.py`). Detection reasons are normalized — quoted strings, IPs, UUIDs, emails, long numbers stripped (`normalize_reason`) — then SHA-256'd into a pattern hash. An indicator promotes to the shared feed only after **3 distinct orgs** sight it, and decays at 0.95/day (~14-day half-life) without re-sighting. This is a network-effect moat that a single-tenant prompt firewall can't build. Extraction threshold: confidence ≥ 0.7.

3. **Discovery → compliance is one pipeline, and it refuses to over-claim.** The design rationale is stated directly in README:12 and the CHANGELOG: a catalog-suggested Annex III risk tier lands as `proposed`, **never approved** — "a machine's guess at an Annex III tier is a draft for a human, not a compliance fact." Unrecognized apps stay as probe events and never enter the register. The SSO matcher is deliberately **asymmetric**: extra words in the SSO label are fine, extra words in the catalog name are not, so a grant to "Figma" never claims "Figma AI"; a label matching two entries is refused rather than guessed. Validated at 0 false positives over 32 ordinary enterprise apps.

**Weakest differentiation claim:** detection itself is regex + statistics, not novel ML. Lead with architecture and the threat-intel network effect, not detection accuracy.

---

## 7. Notable engineering depth

Ranked by what a staff-level interviewer would actually find interesting.

| # | Thing | Where |
|---|---|---|
| 1 | **Async-generator cancellation bug, diagnosed and worked around.** Cancelling `wait_for` on a pubsub `__anext__` kills the generator; fix is a decoupled pump task + bounded drop-oldest queue. Comment cites the asyncio repro. | `api/v1/events.py:143–188` |
| 2 | **Quality-tiered anomaly gating** with `inf` multiplier, zero-std fallback, categorical/continuous split, and a JSONB `inf`-serialization fix. | `detectors/anomaly.py:13,16,173,185` |
| 3 | **SSRF prevention at write time, not read time.** Okta host is validated against an allowlist when a credential is *stored*, with the reasoning stated: an unattended worker will later fetch that host with a token attached, so a bad row must be rejected "when a person is present to see the error." | `services/probe_credential_service.py:1–41` |
| 4 | **Hash-chained audit export.** `row_hash_n = sha256(prev_hash_{n-1} + canonical_json(row_n))`, `prev_hash_0 = "GENESIS"`, ordered `created_at ASC, id ASC` so re-export reproduces identical hashes, with a `verify_chain()` re-walker. | `services/audit_export_service.py:9,81,216` |
| 5 | **Fernet encryption for probe credentials that fails closed.** Plaintext enters via `create`/`rotate_secret`, leaves only via `reveal_secret` immediately before an outbound call; never on the model, never in a response schema, and sync errors redact the token before persisting to `last_sync_error`. | `services/probe_credential_service.py`, `core/secret_crypto.py` |
| 6 | **Postgres-native idempotent upsert with insert-vs-update detection** — `ON CONFLICT ... RETURNING (xmax = 0) AS inserted` to distinguish a new probe event from a dedup hit. Genuine Postgres depth. | `discovery/sso_probe.py:26` |
| 7 | **Longest-prefix rate limiting** with ordering that is load-bearing — `/policies/simulate` (10/min) must be listed before `/policies` (60/min) to win the match. Limits are per-endpoint-class and justified in comments. | `core/rate_limit.py:15–45` |
| 8 | **Deploy shipped as a tarball, with the cost math written down.** `docs/DEPLOY.md` explains that `COPY --from=builder /app /app` collapses venv + app into one ~1.5 GB layer whose digest changes every commit, so a registry re-transfers ~1.9 GB/deploy — at GHCR's $0.50/GB egress that costs more than the droplet. Names the correct long-term fix (split dependency and app layers) and why it wasn't required to ship. | `docs/DEPLOY.md:11–31` |
| 9 | **Deploy-ref command-injection allowlist** — `workflow_dispatch` inputs reach an SSH command, so the ref is regex-validated `^[A-Za-z0-9._/-]{1,100}$` *before* checkout. Comment acknowledges dispatch is write-access-only and says the allowlist is cheap insurance anyway. | `.github/workflows/deploy.yml:49–60` |
| 10 | **Unicode smuggling detection in MCP tool manifests** — zero-width, bidi, and Unicode tag characters, plus manifest hashing for server identity. Genuinely early to the MCP-supply-chain threat. | `detectors/mcp_manifest.py:175` |
| 11 | **Migration CI that asserts alembic head == newest file**, catching the classic "forgot to bump down_revision" merge bug. | `ci.yml`, migrations job |

---

## 8. Discrepancies to fix before you interview

These are places where the repo's own documentation contradicts its code. Any of them, caught by an interviewer, costs more than the claim was worth.

| # | Claim | Reality |
|---|---|---|
| 1 | `backend/pyproject.toml` declares **`spacy>=3.8.0`** and **`scikit-learn>=1.6.0`**; `CLAUDE.md` and README list them under "Detection." | **Neither is imported anywhere in `backend/app/`.** Verified by grep. There is no ML model in this codebase — detection is regex + statistics + a Claude API fallback. **Do not put "spaCy/scikit-learn" or "ML classifiers" on your resume.** Separately worth fixing on its own merits: both drag heavy transitive dependency trees into every image build for nothing. |
| 2 | README: "tamper-evident hash-chained audit log." | The chain is computed **per-export**, not persisted. `audit_export_service.py:14` says so explicitly; the `audit_log` table has no `prev_hash` column (`models.py:351–376`). It's append-only-by-convention with a verifiable export. Phrase it as "verifiable hash-chained audit export," not "hash-chained audit log." |
| 3 | `docs/architecture.md` describes `agent_events` with `prompt_hash`, `prompt_preview`, `response_preview`. | The model stores **full `prompt` and `response` as `Text`** (`models.py:245–246`). PII stripping happens client-side in the SDK only. The doc is stale relative to the schema. |
| 4 | README: "700+ tests." | ~1,350+ test functions. Stale downward. |
| 5 | README/architecture: "ML classifiers" in the detection engine. | No ML classifier exists. `llm_fallback.py` calls the Anthropic API. |
| 6 | `CLAUDE.md` references `docs/adr/` for Architecture Decision Records. | Directory does not exist. Rationale lives in module docstrings and `docs/plans/` instead — which is defensible, but don't claim ADRs. |
| 7 | `DetectionPipeline` docstring lists "3. Check policy enforcement" as a stage. | `run()` has no separate policy stage; policy is passed into `event_data` and consumed by the tool-misuse/policy-logic detectors. Cosmetic, but it's in the file you're most likely to be asked to walk through. |

---

## 9. Resume bullets you can defend

Each maps to something above; the file reference is where you'd open the laptop.

- Built an AI-agent runtime security platform — ~52k LOC across a FastAPI/Postgres+TimescaleDB backend, three language SDKs (Python/TypeScript/Go), and a 28-page React dashboard — with 1,300+ tests and an 8-job CI matrix covering every package. *(counts verified above; `ci.yml`)*
- Designed a 12-detector pipeline with a two-path enforcement model: async fire-and-forget ingest for zero added agent latency, plus a synchronous pre-call blocking endpoint with a Redis-cached policy load on a p99<10ms budget. *(`detection/pipeline.py`, `api/v1/proxy.py:1–15`)*
- Built a cross-organization threat-intelligence feed that anonymizes detection signatures via normalization + SHA-256, promotes indicators only after independent sighting by 3+ orgs, and decays them at a 14-day half-life. *(`services/threat_intel_service.py:22–70`)*
- Cut anomaly-detector false positives by gating 3-sigma drift alerts on baseline sample quality — low-quality baselines suppressed outright, medium scaled to 4σ — while emitting drift as a Prometheus histogram on non-triggered events to tune thresholds against live traffic. *(`detectors/anomaly.py:13`, `detection_service.py:78`)*
- Shipped agentless Shadow-AI discovery: a read-only Okta probe matches SSO grants against a 200-vendor catalog and files findings into an EU AI Act Article 26 register, with asymmetric name matching validated at 0 false positives over 32 enterprise apps and machine-suggested risk tiers held as human-review proposals rather than approved classifications. *(`discovery/sso_probe.py`, `catalog/services.json`, CHANGELOG)*
- Hardened the credential path against SSRF and secret leakage: Fernet encryption that refuses to store rather than fall back to plaintext, host allowlist validation at write time so an unattended worker never fetches an attacker-controlled host, and token redaction in persisted sync errors. *(`services/probe_credential_service.py`)*
