# Policies and Rules

Parry's built-in detectors catch the universal threat patterns
described in the [Detection Catalog](detection-catalog.md) —
prompt injection, jailbreaks, data exfiltration, behavioural
drift. **Policies** and **rules** are how you layer your
organisation's specific constraints on top of that: which tools
each agent is allowed to call, how much they're allowed to
spend, what content is forbidden in either direction, and which
domain-specific patterns matter to your business.

This guide explains the three customisation surfaces — Policies,
Custom Rules, and Community Rules — and the **regression
simulator** that lets you preview the impact of any change
against your real historical events before activating it. The
simulator is the most under-used feature in Parry and the single
biggest source of "I shipped a rule and it nuked production"
prevention.

If you haven't seen the dashboard yet, the [Dashboard
tour](dashboard-tour.md) covers each page these sections live in;
this document is the conceptual reference for what each surface
does and when to use which.

---

## When to use what

The three surfaces solve different problems:

| Surface | Use when | Lives in |
| --- | --- | --- |
| **Policies** | Enforcing structural rules — "agent X may only call these tools, must stay under 10K tokens, may not produce these patterns" | Dashboard → Policies |
| **Custom Rules** | Org-specific regex detection — "block any mention of competitor names, flag attempts to discuss pricing" | Dashboard → Custom Rules |
| **Community Rules** | Pre-built rule bundles for verticals (healthcare, finance, PII, compliance) maintained by the Parry community | Dashboard → Community Rules |

A simple way to decide: **policies say no, rules say notice**.
A blocked tool returns a `tool_misuse` detection at `high`
severity and, with blocking enabled, prevents the LLM call. A
custom regex match returns a `custom_rules` detection at whatever
severity you configured — possibly `low` (just notice it) or
`critical` (block it). Both surfaces feed into the same severity-
based blocking decision; they just describe different kinds of
rule.

---

## Policies

A policy is a named bundle of constraints owned by your org. Most
orgs have one or two — typically a strict policy for production
agents and a relaxed one for development. Policies are applied
org-wide; per-agent policy assignment lives in the agent's
record.

### Fields

| Field | Type | What it does |
| --- | --- | --- |
| `name` | string | Human-readable identifier shown in the dashboard |
| `description` | string | Free-form explanation of what this policy enforces |
| `is_active` | bool | When `false`, the policy is stored but not applied |
| `allowed_tools` | list of strings | If non-empty, only listed tools may be called. Triggers `tool_misuse` (high) on violation |
| `blocked_tools` | list of strings | Tools in this list are never allowed. Triggers `tool_misuse` (high) on attempt |
| `allowed_domains` | list of strings | Reserved for HTTP-tool URL allow-listing |
| `blocked_domains` | list of strings | Reserved for HTTP-tool URL deny-listing |
| `max_token_budget` | integer | Per-event token cap. Triggers when exceeded |
| `forbidden_patterns` | list of strings | Regex patterns that, if matched in prompt or response, trigger a violation |
| `custom_rules` | object | Reserved policy-scoped custom rules; the org-wide Custom Rules surface is preferred |

`allowed_tools` and `blocked_tools` together cover both the
allow-list and deny-list shapes of tool authorisation. Most orgs
pick one model: an allow-list when you know exactly which tools
each agent should ever call, a block-list when you only need to
forbid a handful of dangerous tools and want to leave the rest
flexible. Mixing both is supported — the deny-list is checked
first.

`max_token_budget` is per-event, not per-session. For session-
level cost limits use [Cost & Budgets](cost-and-budgets.md).

### Lifecycle

Policies are created, edited, deactivated, and deleted. **Always
prefer deactivation over deletion** for policies that have ever
been live — keeping the row preserves the audit trail of "this
agent was operating under policy X at time Y" for compliance.
Every mutation goes through `audit_service.log_action()` and
shows up on the **Audit Log** page with an actor, action, and
diff.

The standard editing workflow is:

1. Open Policies, click into the policy you want to change.
2. Make the edit but **don't save yet**.
3. Click **Preview against last 7 days** — runs the regression
   simulator against your real historical events.
4. Review the matched count, per-agent breakdown, and sample
   events. If the impact looks right, save. If not, refine.

Skipping step 3 is how policies break production. The simulator
runs in seconds against historical data; there's never a reason
not to use it.

### What happens at runtime

For every LLM call the SDK forwards to Parry, the active org
policies are loaded and merged into a single effective policy.
Each detector that consumes policy data (currently `tool_misuse`,
plus the `policy_logic` enforcement layer for `forbidden_patterns`
and `max_token_budget`) reads from this merged view. Multiple
overlapping policies behave additively — an event must satisfy
**all** active policies to pass.

---

## Custom Rules

Custom rules are org-specific regex detectors that run alongside
the built-ins. The use cases that show up in practice:

- Block competitor mentions in agent responses.
- Flag attempts to discuss pricing, contracts, or M&A in
  user-facing channels.
- Catch org-specific secret formats that aren't covered by the
  generic `data_exfiltration` detector (e.g. an internal token
  scheme like `INT-ABC123-...`).
- Enforce tone or vocabulary guidelines — flag profanity,
  flag mentions of unsupported features.

Built-in detectors keep running independently. Custom rules add
to coverage; they don't replace it.

### Fields

| Field | Type | Notes |
| --- | --- | --- |
| `name` | string | Shown in the dashboard and in detection reasons |
| `pattern` | string | Python `re` regex, compiled with the `IGNORECASE` flag |
| `target` | enum | `prompt`, `response`, or `both` |
| `severity` | enum | `low`, `medium`, `high`, or `critical` |
| `enabled` | bool | Disable without deleting to preserve history |

The detector's overall severity is the **maximum** across all
matched rules. A `low` rule and a `critical` rule both matching
the same event yield a `critical` detection. Disabled rules are
skipped entirely.

### Pattern safety

Patterns are validated on write to prevent runtime issues:

- **Length cap of 512 characters** — anything longer is
  rejected.
- **Regex syntax** — invalid patterns are rejected at write time.
- **Catastrophic-backtracking guard** — patterns with nested
  quantifier shapes known to blow up the stdlib `re` engine
  (e.g. `(a+)+`, `(a*)*b`) are rejected. The guard is a
  conservative pattern-set, not a full proof — if a pattern has
  borderline shapes, the regression simulator's per-event
  timeout will surface it before you commit.

A corrupted JSONB row that bypassed write-time validation is
defended against at runtime: invalid regexes are skipped silently
rather than crashing the detection pipeline. The dashboard's
**Custom Rules** page surfaces any rule that's been disabled this
way.

### Live tester and simulator

The Custom Rules editor has two sibling features that catch
mistakes before they hit production:

- **Live tester.** Paste a prompt and see whether your regex
  matches before saving. Useful for quick iteration on the
  pattern itself.
- **Regression preview.** Same engine as the policy simulator;
  see [Regression simulation](#regression-simulation) below for
  the full mechanics.

---

## Community Rules

Community Rules is a marketplace of pre-built rule bundles
(packs) maintained by the Parry community. Use them when you
need vertical-specific coverage on day one.

| Category | Typical packs |
| --- | --- |
| `healthcare` | HIPAA PHI patterns, MRN formats, prescription identifiers |
| `finance` | PCI-DSS extensions, account number formats, trade identifiers |
| `pii` | Country-specific national IDs, passport numbers, phone formats |
| `compliance` | EU AI Act prompts, GDPR-relevant patterns, SOC 2 evidence helpers |
| `prompt-injection` | Curated injection corpora the built-ins haven't yet absorbed |
| `data-exfiltration` | Domain-specific exfil patterns (medical record exports, financial statement formats) |
| `tool-misuse` | Tool-name allow/block recipes for common stacks |
| `general` | Catch-alls for things that don't fit elsewhere |

Each pack contains up to **30 rules** — a hard server-side cap.
Installing a pack copies its rules into your org's
`detector_config["custom_rules"]` so the runtime path is
identical to your hand-written rules. Uninstalling removes them
cleanly without touching historical events.

Packs are versioned. When a pack you've installed updates
upstream, the dashboard shows an **Update available** badge —
upgrading replaces the pack's rules with the new version
atomically. Your hand-written rules are unaffected.

Publishing your own pack is a separate workflow gated behind the
admin role; see the **Community Rules** page for the publish UI.

---

## Regression simulation

The regression simulator runs a proposed rule or policy against
your real historical events and returns a report. Use it before
every policy or rule change. It's the only tool Parry ships that
catches "this rule looked fine but matched 40% of last month's
events" before the rule goes live.

### How it works

The simulator compiles the proposed pattern (with a hard
512-character length cap and the same catastrophic-backtracking
guard as Custom Rules), then iterates events from the last
N days for every agent in your org. Each event is matched once
against the configured target (`prompt`, `response`, or `both`).
Matches are aggregated into a structured report.

| Setting | Default | Notes |
| --- | --- | --- |
| `days_back` | 30 | Hard cap is bounded by event retention |
| Per-event match span | First 200 chars | Returned in samples for visual review |
| Sample limit | 10 | The first ten matches; gives you concrete evidence |
| `max_events` | 500 000 | Walks halt after this; report says `truncated: true` |
| Pattern length | ≤ 512 chars | Same cap as Custom Rules |
| Pattern shape | Backtracking guard | Same guard as Custom Rules |

If the proposed pattern is invalid, the simulator returns an
empty report with `pattern_is_valid=false` and a human-readable
`error`. It never queries the database for invalid input — the
guard catches the problem before any I/O.

### The report

The report is a typed dict with these fields:

| Field | Meaning |
| --- | --- |
| `days_checked` | Window the simulator scanned |
| `total_events_checked` | Events visited (capped at `max_events`) |
| `matched_count` | How many events the pattern matched |
| `match_rate` | `matched_count / total_events_checked` |
| `by_agent` | Counter of matches per agent name |
| `by_day` | Counter of matches per ISO date |
| `samples` | Up to ten concrete sample events with previews and matched span |
| `truncated` | True if the walk hit `max_events` before finishing |
| `pattern_is_valid` | False on regex compile error |
| `error` | Human-readable error string when invalid |

The two numbers people miss but should always check are
**match rate** and **`by_agent`**. Match rate above 1% on a
"block" rule almost always indicates a too-broad pattern — real
threats are rare. The `by_agent` dictionary tells you whether
the matches are concentrated in a few agents (likely a real
signal) or spread across the fleet (likely a false positive).

### Reading sample events

The first ten matches come back with a 200-character preview of
the prompt and response, the matched field, and the matched
span. This is enough to eyeball whether the matches are what you
expected. If they aren't, refine the pattern and re-run — the
simulator is cheap.

A pattern that produces zero matches isn't necessarily bad — it
might be specifically designed to catch rare events that haven't
happened yet. But it does mean you don't have evidence that the
pattern works; consider running the **live tester** with the
exact strings you expect to match before committing.

---

## Operating model

Three habits that keep the policy and rules surface healthy:

**Quarterly review.** Policies that were urgent six months ago
often shouldn't apply any more. Open every active policy, run
the regression simulator against the last 30 days, and ask "if
this triggered today, would it be a true positive?" Deactivate
the ones that no longer earn their keep.

**Severity discipline.** Reserve `critical` for things that
should *never* happen in production — not for things you're
worried about but haven't decided to block yet. Use `low` or
`medium` for the worried-about category. The dashboard's
incident triage is designed around `critical`+`high` taking
priority; flooding `critical` weakens the signal.

**Default to deactivation.** Deleting a policy or rule loses
audit history. Deactivating preserves it. Disk is cheap;
auditability when an incident happens six months later isn't.

---

## Where to go next

- [Detection Catalog](detection-catalog.md) — the built-in
  detectors that policies and rules complement.
- [Dashboard tour](dashboard-tour.md) — the Policies, Custom
  Rules, and Community Rules pages in detail.
- [Permissions](permissions.md) — agent-level permission
  boundaries; a complementary surface to Policies for
  per-agent rather than org-wide constraints.
- [Cost & Budgets](cost-and-budgets.md) — session-level cost
  enforcement beyond per-event `max_token_budget`.
- [`docs/red-team.md`](../red-team.md) — verifying your policy
  and rule changes against the bundled attack corpus before
  rolling out.
