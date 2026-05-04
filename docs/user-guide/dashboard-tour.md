# Dashboard Tour

The Parry dashboard at `app.parry.dev` is the operator's surface
for everything the SDK reports. This guide is the page-by-page
reference: what each surface shows, who tends to use it, and the
one workflow it's optimised for. Read top to bottom on your first
day, or skim and use as a lookup later.

The sidebar is a flat list of nineteen routes. We've grouped them
in this guide by what you'd actually open them for — daily
triage, configuration, operations, governance — because the
sidebar order is alphabetic-ish and not workflow-driven. Every
section names the exact sidebar label so you can find it.

A note on roles before we start. Parry maps Clerk org membership
to three Parry roles: **owner**, **admin**, and **viewer**.
Viewers see everything but can't mutate. Admins can do everything
except billing. Owners add billing and SSO config to that.
Buttons that mutate state simply don't render for viewers — if
the page looks read-only and you expected to edit something, your
role is the reason.

---

## Daily triage

These are the four pages an on-call security engineer lives in.
If your job is to investigate what your agents did today, this is
your tab strip.

### Overview (`/dashboard`)

The landing page after login. Four stat cards across the top —
active agents, open incidents, critical alerts, total agents —
followed by a seven-day **incident trend** line chart and a
**severity breakdown** donut. Below that is the **fleet health
card** showing per-agent health grades, the **org cost summary**
for the current billing cycle, the **blocked event feed** with
real-time blocks streaming in, and an agent grid linking into
each agent's detail page. On a brand-new org with zero agents
the whole grid is replaced with a first-run prompt that walks
you back to the SDK install — Parry intentionally hides the
"wall of zeros" until there's something to show.

### Incidents (`/incidents`)

The triage queue. Each incident bundles related triggered
detections; clicking one expands the **Attack Chain Replay** — a
forensic timeline of every event leading up to the trigger, with
each step's prompt, response, and detector verdict. Filters at
the top of the page narrow by severity (`critical`, `high`,
`medium`, `low`) and status (`open`, `acknowledged`, `resolved`,
`dismissed`). Each incident also exposes a per-row history
expander so you can see who acknowledged or resolved it and
when, plus a share button for handing the URL off in Slack.
Status changes are recorded in the audit log automatically.

### Session Replay (`/sessions/$sessionId`)

Reached by clicking a session link from Agent Detail or from an
incident's attack chain. A vertical timeline of every event in
the session, oldest first, with a coloured left border on cards
that contain a triggered detection — critical and high in red,
medium in orange, low in zinc. Open sessions poll every five
seconds so events animate in live. An incident banner at the top
lists any incidents this session triggered. Role-aware: admins
see full prompt and response content; viewers see 200-character
previews so analysts who don't need raw payloads aren't exposed
to them.

### SDK Health (`/sdk-health`)

The "is anything sending data" sanity check. Four counts at the
top — total, healthy, stale, silent — and a list of every agent
with last-event timestamp, wrapper type (`ParryOpenAI`,
`ParryAnthropic`, `ParryCallbackHandler`, etc.), and SDK version.
Stale means no events in the last three hours; silent means none
ever or none in the configured silence window. Refreshes every
thirty seconds. This is where you catch a deploy that broke the
SDK init or a service that quietly stopped emitting events.

---

## Agent management

### Agents (`/agents`)

The roster. Every agent that's ever sent an event shows up here
with a health badge and a click-through to the detail page. Two
admin-only actions sit in the header: **New Agent** to create one
manually (rare — agents auto-register on their first SDK call)
and **Recompute all baselines** to force a re-evaluation across
the org after a major prompt or model change. The empty state
shows the SDK install snippet for whichever language matches the
new-agent flow.

### Agent Detail (`/agents/$agentId`)

The deepest single page in the dashboard. Top of the page is the
**health score** with its component breakdown (cost, drift,
incidents, anomalies). Below that is a chart strip — sparkline
of recent events, **detector breakdown**, **event volume**,
**tool-call heatmap**, **model-usage donut**, **anomaly trend** —
all switchable across a 7-day, 30-day, or 90-day window. Then
the **baseline drift timeline** showing how this agent's
behaviour has shifted over time, the **permissions card** with
the agent's tool boundary, the **cost card**, and the recent
events feed (live-streaming via SSE when the agent is active).
An anomalies-only filter narrows the event list to outliers
based on the baseline's known models, average tokens, and
average latency. Admin actions: recompute this agent's baseline,
start a red-team run against it, or delete the agent.

### Fleet Overview (`/fleet`)

Cross-agent comparison. Four summary tiles — total agents,
average health score, healthy (A/B), needs attention (D/F) — and
a single horizontal bar showing the grade distribution at a
glance. The full agent list below sorts by score so the
highest-risk agents float to the top. Use this when you want to
ask "which agents need attention" rather than "what's wrong with
this specific agent." It's also the most efficient surface for a
weekly fleet review.

### Agent Groups (`/agent-groups`)

Organise agents into teams that inherit permissions and policies.
A "production agents" group, for example, lets you set a strict
permission boundary once and have every member agent inherit it.
Group creation is admin-only; everyone can browse memberships.
Groups are optional — most orgs don't need them until they hit
~10 agents.

---

## Detection configuration

### Policies (`/policies`)

Org-level rules every event is checked against. A policy bundles
four things: **allowed tools** (whitelist), **blocked tools**
(blacklist), **max token budget**, and **forbidden patterns**
(regex against prompts and responses). The create form takes
each as a comma-separated list. Before activating a new policy,
the **Regression Preview** panel simulates it against historical
events from the last seven days so you see exactly which
already-recorded events would have been blocked. Use it — most
policy mistakes show up immediately under regression preview and
never get a chance to break production.

### Custom Rules (`/custom-rules`)

Org-specific regex detectors. Each rule has a name, a regex
pattern, a target (`prompt`, `response`, or `both`), a severity
(`critical`/`high`/`medium`/`low`), and an enabled toggle.
Editing a rule shows a live tester where you paste a prompt and
see whether the regex matches before saving. The same regression
preview from Policies runs here too. Built-in detection
(prompt-injection, jailbreak, tool-misuse, etc.) keeps running
regardless of whether you have any custom rules — they're
additive.

### Community Rules (`/community-rules`)

A library of pre-built rule packs maintained by the Parry
community. Categories include `healthcare`, `finance`, `pii`,
`compliance`, `prompt-injection`, `data-exfiltration`,
`tool-misuse`, and `general`. Search the catalogue, install a
pack with one click, uninstall when you don't want it any more.
Installed packs show up alongside your own custom rules at
runtime; uninstalling one disables it cleanly without affecting
historical events. This is the fastest way to get vertical-
specific coverage on day one.

### Tuning Sandbox (`/tuning`)

A scratchpad for detector tuning. Paste up to fifty prompts (one
per line) and adjust per-detector trigger thresholds with a
slider — prompt-injection (default 0.6), jailbreak (0.7),
privilege-escalation (0.7), data-exfiltration (0.5), and
tool-misuse (0.5). Replay runs the prompts through the detectors
with your overrides applied and shows what would have triggered.
No LLM tokens are burned and nothing is persisted; the sandbox
is purely for finding the threshold that catches your true
positives without firing on the false ones. Move successful
overrides into Settings → Detector Tuning to make them live.

---

## Operations

### Red Team (`/red-team`)

On-demand attack runs. The bundled corpus contains roughly four
dozen attacks across eight categories (instruction-override,
jailbreak, data-exfiltration, tool-hijack, MCP-injection,
unicode-smuggling, cost-exploit, anomaly). The number is shown at
the top of the page so you'll always see the current count.
Pick an agent, choose **sandbox mode** (replays the corpus
through your detector stack without making real LLM calls — runs
in seconds), and submit. The page lists every run you've made
with grade, agent, and timestamp.

### Red Team Run Detail (`/red-team/$runId`)

The report card for one run. The score card up top gives the
overall grade. Below is a category breakdown — how Parry did on
prompt-injection vs jailbreak vs MCP-injection separately — and
then the **undetected attacks** table: every attack the corpus
threw that didn't trigger any detector, with category, severity,
and the list of detectors that did fire (if any). This table is
the single most useful surface for tuning: each row is a
specific gap, named, with enough context to fix.

### MCP Servers (`/mcp`)

Every MCP server your agents have connected to via
`SentinelMCPClient`. Columns: server name, URI, trust level,
tool count, reputation score, last-seen timestamp. Filter by
trust state — `observed` (default), `trusted`, `suspicious`, or
`blocked`. Click any row to drill into Server Detail.

### MCP Server Detail (`/mcp/$serverId`)

Per-server view. Trust level rendered large at the top with a
reputation badge and the manifest hash; admins get a
trust-level switcher to manually move a server between
`observed`, `trusted`, `suspicious`, and `blocked`. Below that
is the full tool manifest — every tool the server exposed, with
name and description, exactly as Parry saw it on connect. This
is also where you investigate a manifest-injection finding: the
description text is rendered verbatim so smuggled instructions
are easy to spot.

### Threat Intel (`/threat-intel`)

Cross-org indicator feed. Three stat cards at the top — active
indicators, total tracked, distinct categories — followed by the
indicator list with severity, score (0–1, rendered as a coloured
bar), category, and first/last seen. Categories include
`instruction_override`, `jailbreak`, `data_exfil`, `tool_hijack`,
`mcp_injection`, `unicode_smuggling`, `cost_exploit`, `anomaly`,
and a few more. Indicators are derived from anonymised pattern
hashes contributed across the Parry network — your raw prompts
never leave your org. Sharing is opt-in and toggled here too.

### SLOs (`/slo`)

Internal SLO dashboard. Latency, error rate, and throughput
targets for the Parry backend itself, with a coloured budget bar
per SLO. Important caveat the page makes explicit: values come
from the in-process Prometheus registry and are cumulative since
the last backend restart, so this is **not** a rolling-30-day
SLO and **not** a public status page. For real burn-rate
tracking, scrape `/metrics` and compute in Grafana. The page is
useful for "is the backend healthy right now" but not for
contractual reporting.

### Audit Log (`/audit-log`)

Every state-changing action in the org. Each row is one entry:
actor (user, API key, or system), action (e.g.
`policy.created`, `incident.resolved`, `baseline.recomputed`),
resource type, free-form details, timestamp. Filters narrow by
action and — for baseline recomputes — by reason (`manual`,
`manual_bulk`, `stale_age`, `stale_growth`). Export to CSV or
JSON, default ninety-day window, backend caps at four hundred
days. This is the surface you point an auditor at when they ask
"who did what."

---

## Governance and admin

### Compliance (`/compliance`)

The EU AI Act Article 26 module. Five tabs: **Posture**
(traffic-light status across every applicable obligation),
**AI Systems** (your register of in-scope systems with risk
classification — `unacceptable`, `high`, `limited`, or
`minimal`), **Suppliers** (third parties whose models or services
you use), **FRIA** (Fundamental Rights Impact Assessment workflow
per high-risk system), and **Incidents** (the serious-incident
log Article 26 mandates). The Posture tab also offers an
**auditor bundle** export — a single archive bundling every
artefact a regulator typically asks for, generated on request and
streamed back as a download. Compliance is gated behind the Pro
plan and above.

### Reports (`/reports`)

Compliance report exports. Admin-only. Pick a start and end date
(default thirty days, backend caps the synchronous path at
ninety days), click generate, and the page streams a PDF back to
your browser. The last five reports you've generated are cached
in `localStorage` so you can re-download recent ones without
rebuilding — **metadata only**, the PDF bytes are never cached
locally. For a longer SOC 2 window the underlying API endpoint
accepts up to a year via direct call.

### Webhooks (`/webhooks`)

Outbound HTTP delivery for the seven event types Parry emits:
`detection.triggered`, `incident.created`, `incident.resolved`,
`permission.denied`, `threat_intel.match`, `agent.created`, and
`budget.exceeded`. Each endpoint has a URL, an optional
description, a list of subscribed event types (empty list means
all), an active flag, a failure counter, and a last-triggered
timestamp. The **Send test** button delivers a synthetic payload
so you can confirm the receiver is wired up. Expanding an
endpoint shows its delivery log — every attempt, status, and
response body. HMAC signing secret is shown once per endpoint
and never again, so copy it on creation.

### Settings (`/settings`)

The catch-all admin surface, organised into stacked cards:

- **API Keys** — create new keys (shown once, never again),
  revoke existing ones. Each key carries the org's identity.
- **Blocking** — the master toggle that flips the SDK from
  observe-only into blocking mode org-wide. Off by default for
  fresh installs so a new integration can never break customer
  traffic.
- **Response Scan** — three modes: `off`, `redact`
  (responses with sensitive findings get cleaned in place),
  `block` (the response is dropped and `ParryBlockedError` is
  raised in the SDK).
- **Detector Tuning** — per-detector enable toggle and trigger
  threshold, with a reset-to-defaults button. The drift
  histogram shows how each setting is affecting trigger volume
  in real time.
- **Alerts** — destination configs for Slack, PagerDuty,
  Opsgenie, and email. Each has a **Send test** button.
- **Plan & Billing** — owner-only, links to Stripe portal.
- **SSO** — owner-only, configured through Clerk.

---

## Where to go next

- [Concepts](concepts.md) — definitions for the nouns this tour
  used (agent, session, event, detection, incident).
- [Python SDK](sdk/python.md) — how the data on these pages gets
  there.
- [Getting Started](getting-started.md) — the introductory
  walkthrough if you skipped it.
- [`docs/mcp-security.md`](../mcp-security.md) — what the MCP
  Servers page is actually showing under the hood.
- [`docs/red-team.md`](../red-team.md) — the threat model behind
  the bundled red-team corpus.
