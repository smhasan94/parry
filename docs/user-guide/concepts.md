# Concepts

Parry organises everything it observes into a small set of nouns. If
you remember six of them — **org**, **agent**, **session**, **event**,
**detection**, **incident** — every page in the dashboard, every API
route, and every SDK call name will make sense. This guide defines
each one and explains how they relate.

---

## The hierarchy

```
Org
 └── Agents (your AI processes)
      └── Sessions (one conversation/run)
           └── Events (one LLM call)
                └── Detections (each detector's verdict on this event)
                     └── Incidents (triage-grouped triggered detections)
```

Each level fans out into the next. One org has many agents. One agent
runs many sessions. One session contains many events. One event is
checked by many detectors, each producing one detection record.
Triggered detections get grouped into incidents that humans triage.

Two concepts cut across this hierarchy:

- **Policies** live on the org and apply to every event.
- **API keys** live on the org and authenticate the SDK on behalf of
  any agent.

---

## Org

The **organisation** is the top-level tenant. Every other object in
Parry is scoped under exactly one org.

When a person signs up they create (or join) an org. The org owns:

- Its **agents** and the data those agents produce.
- Its **policies** (what's allowed, what's blocked).
- Its **API keys**.
- Its **plan** (Free, Growth, Pro, or Enterprise) which gates feature
  access and quota.
- Org-wide settings: blocking mode toggle, response-scan mode, alert
  channels (Slack, PagerDuty, Opsgenie), SSO configuration, threat-intel
  sharing opt-in.

Parry is multi-tenant; data never crosses an org boundary. Even the
cross-org **threat intelligence** feed is built from anonymised
pattern hashes — never raw prompts or org identifiers.

---

## Agent

An **agent** is a named, long-lived AI process. Customer support bot,
PR review bot, sales-research agent — anything you want to monitor
gets one agent record.

Agents are created **lazily**. The first time the SDK sends an event
under a new `agent_id`, Parry registers an agent with that name. You
never have to call a "create agent" endpoint manually.

Each agent has:

- A unique `name` (your `agent_id` in the SDK) that's stable across
  restarts of the underlying process. Two processes that share the
  same name are treated as the same agent.
- A **behavioural baseline** — automatically computed averages for
  prompt token counts, response token counts, latency, and the set
  of known models. This baseline drives the **AnomalyDetector**:
  unknown models, 3-sigma drift in tokens or latency, and excessive
  tool calls all fire as anomalies.
- A **health score** (0-100, mapped to letter grades A-F). The score
  starts at 100 and is reduced by recent triggered detections, weighted
  by severity. Recomputed hourly and on-demand; cached in Redis with
  a 2-hour TTL.
- An optional **group** — agents can be organised into groups for
  shared policies, permissions, and budgets.

Agents you don't care about can be **deactivated** (`is_active=false`)
which hides them from the default dashboard view but keeps the data.

---

## Session

A **session** is one logical conversation or run of an agent.

Examples of what a session corresponds to:

- One user chat thread with a support agent.
- One end-to-end run of a workflow agent (e.g., "research this
  company and produce a brief").
- One CI build invocation of a code-review agent.

Sessions are how Parry groups related events for **session replay**
and for **session-history-based detectors** like the
`CostExploitLoopDetector` (which looks for identical tool-call
signatures repeated within a session).

Sessions are optional from the SDK side. Pass `session_id` to the
wrapper if you have a stable identifier; otherwise events stand alone
without grouping. Sessions can also be left open indefinitely
(`ended_at` is nullable) — Parry doesn't force you to close them.

---

## Event

An **event** is a single LLM call: prompt in, response out, plus
metadata. It is the **atomic unit** of everything Parry analyses.

Each event records:

| Field | What it holds |
| --- | --- |
| `prompt` | The user message text (last message if multi-turn) |
| `response` | The assistant message text |
| `model` | e.g. `gpt-4o`, `claude-sonnet-4-6` |
| `tool_calls` | Array of `{name, arguments}` if the response invoked tools |
| `token_count` | Total tokens (input + output) |
| `latency_ms` | Time the LLM call took |
| `estimated_cost_usd` | Computed at ingest using the model-pricing registry |
| `agent_id`, `session_id`, `timestamp` | Foreign keys + when |
| `metadata` | Free-form JSONB — anything you pass through the wrapper |

Events are stored in a TimescaleDB hypertable partitioned by time.
Queries against the events table are always time-bounded — there is
no full-table-scan path. This is what lets Parry stay fast at high
event volume.

The SDK sends events **fire-and-forget** asynchronously after the LLM
call returns. If Parry's backend is unreachable the event is dropped,
your agent keeps running, and a warning is logged. **Fail-open by
design.**

---

## Detection

A **detection** is one detector's verdict on one event.

Crucially, every detector that runs on an event produces a detection
record — not just the ones that fired. A detection has:

- `triggered: bool` — did this detector flag this event?
- `detector` — which one (`prompt_injection`, `anomaly`,
  `data_exfiltration`, etc.)
- `severity` — CRITICAL, HIGH, MEDIUM, or LOW
- `confidence` — float 0.0-1.0
- `reason` — human-readable explanation
- `details` — JSONB with detector-specific data (matched pattern,
  baseline values, etc.)

Most detection records have `triggered=false`. They're kept so you
can audit *why* an event wasn't flagged later — useful when tuning
custom rules or investigating a missed attack.

Triggered detections are what you actually care about. They're
surfaced in the dashboard's **Incidents** view, drive **alerts**, and
feed the **health score** computation.

A detection with confidence in the **0.4-0.7 ambiguous band** triggers
the **LLM Fallback Detector** — Parry asks Claude (Sonnet) to make
the final call, with the original detection as context. This catches
attacks that match no individual rule but read as obviously malicious
to a smart model.

### How blocking decides

When blocking is enabled, the SDK's pre-flight `/proxy/check` returns
`allowed=false` if **any** detection on the prompt is `triggered=true`
with severity `HIGH` or `CRITICAL`. Lower severity detections are
recorded but don't block. This threshold is the same for every org
and is intentional — `MEDIUM`/`LOW` are noise levels you want logged
but not interrupting traffic.

---

## Incident

An **incident** is a human-triage unit. One or more triggered
detections, automatically grouped, with a status workflow:

```
open → acknowledged → resolved
                  └── dismissed
```

Every triggered detection becomes part of an incident. Multiple
detections from the same event, or from a tight cluster of events on
the same agent, are grouped into one incident so triagers don't drown
in duplicates.

Incidents carry:

- A **title** auto-generated from the highest-severity detection.
- A **severity** equal to the max severity of its detections.
- An **agent_id** — incidents are scoped to an agent, not just an org.
- A **status** — open by default; admins acknowledge, resolve, or
  dismiss them.
- An optional **session_id** in metadata (the trigger session) —
  enables the **Attack Chain Replay** view that reconstructs the
  forensic timeline leading up to the incident.

Incidents are the unit that gets sent to your alert channels
(PagerDuty, Opsgenie, Slack). Detections do not page on their own.

---

## Policy

A **policy** is an org-defined declarative rule that applies to every
event. Unlike detectors (which look at content), policies look at
structure:

- **Allowed tools** — only these tool names may be called.
- **Allowed domains** — tool calls that touch URLs may only call
  these hosts.
- **Forbidden patterns** — regexes that, if matched in prompt or
  response, fire a violation.
- **Token budget** — caps the maximum prompt+response token count.

Policies have an `is_active` flag so you can stage and toggle them.
The **Regression Runner** lets you simulate any policy against your
historical events before activating it — you'll see exactly which
past events would have been blocked and on which agents.

Policies cooperate with the **AgentPermission** boundary (see below):
permissions are evaluated *before* policies and short-circuit them
when an explicit deny matches.

---

## API key

An **API key** is the SDK credential. One org has many keys; each
key has a name (e.g., "production", "staging", "ci-tests") and is
shown to you exactly once at creation time.

Keys are stored hashed; revocation is instant. Each event the SDK
sends is authenticated with one key, and the audit log records which
key initiated which mutation.

Keys are always scoped to the org — they have no agent-level scope.
The `agent_id` is supplied per-call by the SDK.

---

## Severity and confidence

Every triggered detection (and every incident) has both a **severity**
and a **confidence**. They mean different things and you'll see them
together everywhere.

- **Severity** answers *"if this is real, how bad is it?"* —
  CRITICAL > HIGH > MEDIUM > LOW. Set by the detector based on the
  category of finding (e.g., unicode-smuggling is always CRITICAL;
  a generic suspicious phrase is MEDIUM).
- **Confidence** answers *"how sure am I this is real?"* — a 0.0-1.0
  float. High-confidence pattern matches sit above 0.8; the
  0.4-0.7 ambiguous band escalates to the LLM Fallback Detector.

Blocking decisions look at severity, not confidence. Alerts look at
both: the org-wide alert minimum-severity gate (default HIGH) is
checked first, and within that, ordering by confidence helps triage.

---

## Putting it together: the lifecycle of one LLM call

A concrete walkthrough so the nouns connect:

1. Your agent calls `client.chat.completions.create(...)`. The Parry
   wrapper intercepts.
2. **Pre-flight `/proxy/check`** — backend runs the prompt through
   the synchronous detection pipeline (rule-based detectors only;
   ML/LLM detectors are async). If any detection is HIGH+ severity
   and blocking is enabled, the wrapper raises `ParryBlockedError`
   and the LLM is never called.
3. **LLM call** — your existing OpenAI/Anthropic call runs unchanged.
4. **Response scan** — if the org has response-scanning enabled, the
   response is checked for exfiltration patterns and either passed
   through, redacted in place, or blocked.
5. **Async ingest** — the full event (prompt, response, model,
   tokens, latency, tool calls) is sent to the backend in a
   background thread. The backend creates the **Event** record, runs
   the **full** detection pipeline (including async detectors:
   anomaly, threat intel, LLM fallback), writes one **Detection**
   record per detector, and groups any triggered detections into an
   **Incident**.
6. **Alerts fire** if the incident's severity meets your org's alert
   minimum and the relevant channel is configured.
7. The **agent's health score** is recomputed at the next hourly tick
   and the **baseline** is updated to incorporate this event's tokens
   and latency.

That single call has now produced 1 event, ~12 detection records
(one per detector), 0–1 incidents, and updated the agent's baseline.

---

## Secondary concepts

These come into play with specific features. Each gets its own guide.

| Concept | One-liner | Guide |
| --- | --- | --- |
| **Custom rule** | An org-defined regex detector | *Policies & Custom Rules* |
| **Permission** | Per-agent allowlist/blocklist of tool names | *Agent Permissions* |
| **Budget** | Hard cap on agent or org spend per hour/day/month | *Cost & Budgets* |
| **MCP server** | A Model Context Protocol tool source, with a trust state machine | [MCP Security](../mcp-security.md) |
| **Threat indicator** | A pattern hash confirmed across 3+ orgs in the network | *Threat Intelligence* |
| **AI system** | An EU AI Act register entry — an agent or product mapped to risk-tier obligations | *Compliance* |
| **FRIA** | Fundamental Rights Impact Assessment — versioned compliance document for high-risk AI systems | *Compliance* |
| **Serious incident** | An Article 73 reportable event with a 15-day deadline | *Compliance* |
| **Red team run** | A bundled-corpus or live attack replay against an agent's detector config | [Red Team](../red-team.md) |

---

You now have the full vocabulary. Every other guide assumes you know
what an agent, session, event, detection, incident, and policy mean —
flip back here whenever a term feels fuzzy.
