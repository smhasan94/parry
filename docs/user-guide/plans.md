# Plans and Pricing

Parry ships in four tiers — **Free**, **Growth**, **Pro**, and
**Enterprise** — plus a separate on-premise license for
air-gapped deployments. This guide is the authoritative feature
matrix and explains what each tier is designed for, what's
gated where, and how the limits behave at runtime.

The plan you're on shows in **Settings → Plan & Billing**.
Upgrades are self-serve through Stripe Checkout for Free/Growth/
Pro; Enterprise and on-prem are direct contracts.

---

## At a glance

| Tier | Best for | Agents | Events / mo | Retention |
| --- | --- | --- | --- | --- |
| **Free** | Evaluation, side projects, single-agent prototypes | 1 | 10 000 | 30 days |
| **Growth** | Small teams shipping production agents | 10 | 100 000 | 365 days |
| **Pro** | Mid-market, regulated industries, compliance-conscious | 50 | 1 000 000 | 365 days |
| **Enterprise** | Large fleets, EU AI Act high-risk deployers, on-prem | unlimited | unlimited | configurable |

Limits are enforced at the API boundary. Agent and event quotas
return HTTP 402 with the `X-Upgrade-Required: true` header, which
the dashboard intercepts to show an upgrade modal. Feature gates
return the same response shape so any gated call surfaces the
upgrade path consistently.

---

## Feature matrix

The full per-feature breakdown. Features marked yes are
available on that tier; no means upgrade required.

### Core platform

| Feature | Free | Growth | Pro | Enterprise |
| --- | --- | --- | --- | --- |
| Built-in detectors (prompt injection, jailbreak, tool misuse, data exfil, privilege escalation) | yes | yes | yes | yes |
| Drop-in SDK wrappers (OpenAI, Anthropic) | yes | yes | yes | yes |
| Framework hooks (LangChain, CrewAI, AutoGen, LlamaIndex, Pydantic AI) | yes | yes | yes | yes |
| Auto-instrument mode | yes | yes | yes | yes |
| Dashboard observation, incidents, sessions | yes | yes | yes | yes |
| Audit log | yes | yes | yes | yes |
| SDK Health page | yes | yes | yes | yes |
| Email alerts | yes | yes | yes | yes |
| Slack alerts | yes | yes | yes | yes |

The core platform is intentionally available on Free.
Detection is the product — gating it would mean people couldn't
evaluate Parry at all.

### Detection extensions

| Feature | Free | Growth | Pro | Enterprise |
| --- | --- | --- | --- | --- |
| Custom Rules | no | yes | yes | yes |
| Community Rules marketplace | no | yes | yes | yes |
| Cost-exploit detection (loop, verbosity, model escalation) | no | yes | yes | yes |
| Threat intelligence feed | no | yes | yes | yes |
| MCP Security (`SentinelMCPClient` + manifest scanning) | no | yes | yes | yes |
| Tuning Sandbox | yes | yes | yes | yes |

### Enforcement

| Feature | Free | Growth | Pro | Enterprise |
| --- | --- | --- | --- | --- |
| Blocking mode (severity-based) | yes | yes | yes | yes |
| Response scan (off / redact / block) | yes | yes | yes | yes |
| Agent permissions (per-agent tool boundaries) | no | yes | yes | yes |
| Budget enforcement (hourly / daily / monthly caps) | no | yes | yes | yes |
| Policies (allowed tools, blocked tools, forbidden patterns, max token budget) | yes | yes | yes | yes |

### Operations

| Feature | Free | Growth | Pro | Enterprise |
| --- | --- | --- | --- | --- |
| Webhook subscriptions | no | yes | yes | yes |
| PagerDuty / Opsgenie integration | no | yes | yes | yes |
| Red Team sandbox runs | no | yes | yes | yes |
| Red Team live runs (real LLM calls) | no | no | yes | yes |
| SLO dashboard | yes | yes | yes | yes |
| Compliance report PDF export | no | yes | yes | yes |

### Compliance (EU AI Act)

| Feature | Free | Growth | Pro | Enterprise |
| --- | --- | --- | --- | --- |
| AI Systems register | no | no | yes | yes |
| Compliance posture (Article 26 obligations) | no | no | yes | yes |
| FRIA generator (Article 27) | no | no | no | yes |
| Serious incident reporting (Article 73) | no | no | no | yes |
| Auditor bundle export | no | no | no | yes |

The compliance module steps up across tiers because the
audience does. Pro covers organisations starting their AI Act
preparation — register, posture monitoring, baseline evidence.
Enterprise covers organisations that are deployers of high-risk
systems and need the full FRIA + Article 73 + auditor-bundle
flow.

### Authentication and admin

| Feature | Free | Growth | Pro | Enterprise |
| --- | --- | --- | --- | --- |
| Email/password auth (Clerk) | yes | yes | yes | yes |
| Org roles (owner / admin / viewer) | yes | yes | yes | yes |
| API keys with HMAC signing | yes | yes | yes | yes |
| SSO (SAML / OIDC via WorkOS) | no | no | no | yes |

---

## What the limits actually mean

### Agent limits

The agent count is checked when an agent is **created**. Agents
auto-register on first SDK call, so in practice you hit the
limit when a new wrapper instance with a previously-unseen
`agent_id` makes its first call. The 402 response prevents that
agent's events from being ingested until you upgrade or delete an
existing agent.

Existing agents continue working through the limit — Parry
won't drop events from agents that were already registered when
your org grew past the cap. The limit only stops *new* agents.

### Event quotas

The event quota is a **rolling 30-day window**, not a calendar
month. The check happens on every `POST /events/ingest` so it
needs to be fast — a single SQL query over the agent ids
subquery.

When you hit the quota, ingest returns 402 and stops accepting
events. The UI still works, the existing data is still queryable,
but new events drop. The rolling-window design means the quota
recovers as old events age out — you don't have to wait for a
calendar reset.

The quota check is pre-ingest, so it never silently loses data.
Either an event is accepted or the SDK gets a 402 (and per the
fail-open contract, the SDK logs and continues without affecting
the LLM call).

### Retention

Retention controls how long events, detections, and incidents
stay queryable. Free's 30-day retention is the same window as
the rolling event quota — events fall off both at once. Paid
tiers retain for 365 days by default; Enterprise can configure
longer retention as part of contract.

Retention applies to **detail data** — the prompts, responses,
and detection records. Aggregated cost/health/posture metrics
are kept indefinitely so historical dashboards don't go blank
when retention rolls over. If you need primary data beyond your
retention window for compliance reasons, the Compliance module's
auditor bundle generates exports that you keep yourself.

---

## On-premise

For organisations that can't send agent telemetry to a SaaS
backend — air-gapped environments, regulated workloads, sovereign
data requirements — Parry ships an on-premise mode. On-prem
deployments use a **signed license file** as the source of truth
for limits and features instead of the `orgs.plan` column.

The license file specifies:

- `max_agents` — agent count cap.
- `max_events_per_month` — rolling event quota.
- Feature flags — same set as the plan tiers, granular per
  contract.
- Expiry — license validity period.

License renewal happens out-of-band. Expired licenses fail
closed: no new agents, no event ingest, dashboard becomes
read-only. The UI surfaces the expiry date prominently so this
isn't a surprise.

On-prem mode also disables features that have outbound
dependencies — the LLM-fallback detector skips silently
(no Anthropic API call), threat-intel sharing is disabled
(no cross-org pattern uploads), and the auditor-bundle email
delivery falls back to download-only.

Set up is a Docker Compose deployment plus your provided license
file mounted into the backend container. We share the deployment
guide separately with on-prem customers; if that's you and
you're reading this, contact your account team.

---

## Upgrades and downgrades

Plan changes happen through Stripe Checkout for self-serve tiers
(Free → Growth → Pro). Upgrades take effect immediately —
features unlock in real time and the next event ingested
operates under the new limits.

Downgrades take effect at the **end of the current billing
period**. This is intentional: downgrading mid-period would
mean a customer pays for a tier they no longer have access to,
which is the wrong direction for trust. The dashboard shows
"Downgrades to Growth on 2026-06-01" prominently so it's not
forgotten.

Going from any paid tier back to Free is treated as a
downgrade, with the same end-of-period semantics.

Enterprise contract changes go through your account manager —
Stripe Checkout doesn't apply.

---

## What's bundled with what

Three structural decisions worth calling out so you can read the
matrix above more efficiently:

**Free is for evaluation, not for production.** The 1-agent and
10K-event quotas are deliberately small. We want every
prospective customer to be able to wire Parry into one agent,
generate real events, see real detections, and decide if it's
useful. We don't want Free to be the place fully-loaded
production traffic lives.

**Compliance is tiered.** Pro gives you the AI Systems register
and the live-posture page — the two things you need to start an
AI Act readiness conversation. Enterprise gives you the
generation tools (FRIA, serious-incident workflows, auditor
bundle) — the things you need when an audit is imminent or
you've decided to run the full Article 26 program.

**SSO is Enterprise-only on purpose.** Most security teams who
buy Parry want SSO; most teams that don't want SSO are also
the ones for whom SSO isn't a hard requirement. Bundling SSO
with the tier that includes the rest of the enterprise feature
set keeps pricing predictable. We don't separately price SSO as
an add-on — the answer to "can we get SSO without going to
Enterprise" is no, and we'd rather say so cleanly than hide it
in a pricing matrix.

---

## Where to go next

- [Detection Catalog](detection-catalog.md) — every detector
  available on every tier.
- [Compliance](compliance.md) — what the Pro and Enterprise
  compliance modules actually do.
- [Permissions](permissions.md), [Cost &
  Budgets](cost-and-budgets.md), [Integrations](integrations.md)
  — the Growth-and-up enforcement and operations features.
- [Dashboard tour](dashboard-tour.md) — Settings → Plan &
  Billing for the live view of your current plan.
