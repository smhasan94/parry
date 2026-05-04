# Permissions

Parry's permission system answers a single question: **which
tools is this agent allowed to call?** It runs at the proxy
layer, independently of every other detector and independently
of blocking mode, and it's the surface security teams reach for
first when a customer asks "what stops a compromised agent from
calling something it shouldn't?"

This guide explains the model — three modes, two default
actions, three resolution layers — and the operational
patterns that keep it useful: dry-run before enforcement, group
inheritance for fleets, deny-by-default for sensitive agents.

If you've read [Policies and Rules](policies-and-rules.md) you've
seen the `tool_misuse` detector check tool calls against an
org-wide policy. Permissions are the **agent-scoped** equivalent
of that and are enforced earlier and more strictly. The two
surfaces complement each other rather than overlap.

---

## Why permissions are separate from policies

The shortest answer: scope and enforcement timing.

Policies are org-wide and run as a detector. They produce
detections that participate in the normal triggering / blocking
pipeline; a `tool_misuse` violation gets caught alongside other
detector findings and is subject to the same severity-based
blocking decision.

Permissions are **per-agent** (or per-group, or org-default) and
run **before** the detection pipeline. A permission violation
returns a denial response immediately with `detector=
"permission_boundary"`, severity `high`, confidence 1.0 — and
it does this even when blocking mode is otherwise off.

That distinction matters because it lets you ship a strict
authorisation boundary on critical agents without flipping the
master blocking switch for the whole org. A dev agent can stay
in observe-only mode while your production support bot has hard
deny-by-default permissions. Same deployment, different blast
radius.

---

## The model

A permission record has four primary fields:

| Field | Values | Meaning |
| --- | --- | --- |
| `mode` | `enforcing` / `dry_run` / `disabled` | How violations behave |
| `default_action` | `allow` / `deny` | What to do for tools that aren't on either list |
| `allowed_tools` | list of strings | Explicit allow-list |
| `blocked_tools` | list of strings | Explicit block-list |

The four together describe a complete authorisation policy. Tool
names are matched case-insensitively (lowercased on both sides)
so `send_email` and `Send_Email` are the same tool.

### Mode

Mode controls what happens when a violation is detected:

- **`enforcing`** — the proxy returns a denial response. The
  SDK raises `ParryPermissionDeniedError` (a subclass of
  `ParryBlockedError`), the LLM call doesn't happen, and a
  `permission.denied` webhook fires. The denial is recorded
  in the dashboard's incident view.
- **`dry_run`** — the violation is logged with structured
  `permission.dry_run_denied` events but the call proceeds.
  Dashboards count dry-run denials separately so you can see
  exactly which calls *would have been* blocked. This is the
  mode you start in.
- **`disabled`** — permission checking is skipped entirely.
  The record exists for configuration purposes (so you can
  flip to dry-run later without losing the tool lists) but
  has no runtime effect.

### Default action

Default action determines what happens to tools that aren't
explicitly listed:

- **`allow`** — block-list mode. Only tools in `blocked_tools`
  are denied; everything else is permitted. Use when you have a
  short list of forbidden operations and don't want to enumerate
  the long tail of permitted ones.
- **`deny`** — allow-list mode. Only tools in `allowed_tools`
  are permitted; everything else is denied. Use when you know
  exactly what an agent should ever call. Deny-by-default is
  the right setting for production agents in regulated
  industries.

The blocklist always wins over the allowlist. A tool that
appears in both lists is denied — there's no scenario where
deliberately blocking and explicitly allowing the same tool
isn't a misconfiguration, and the safer interpretation wins.

### Resolution order

When the proxy needs to decide whether to allow a tool call, it
walks three layers in order and uses the first record it finds:

1. **Agent-specific record** — `org_id = X, agent_id = Y`. The
   most specific layer; written when you configure permissions
   for a single named agent.
2. **Group record** — looked up via the agent's `group_id`.
   Lets a "production-agents" group apply the same permission
   policy to every member without per-agent configuration.
3. **Org-wide default** — `org_id = X, agent_id = NULL`. The
   blanket policy applied when neither of the above is set.

If none of those match, the agent is **allowed all tools**. This
backwards-compatible default is intentional — orgs that haven't
adopted permissions yet keep working without surprise denials.

You can see which layer applied to any given decision in the
permission record's `source` field (`agent`, `org_default`, or
`no_record`); it's surfaced on the agent-detail page's
**Permissions** card.

---

## Operating model

### Always start in `dry_run`

Permissions in `enforcing` mode block real calls. A wrong
allow-list shipped on Monday is a customer-visible outage on
Monday. The pattern that catches this:

1. Configure your `allowed_tools` / `blocked_tools` and
   `default_action` in `dry_run` mode.
2. Let the agent run for at least 24 hours of representative
   traffic — longer for low-volume agents.
3. Watch the **Audit Log** and the agent-detail page for
   `permission.dry_run_denied` entries. Each one is a call
   that *would have been* blocked.
4. Either the dry-run denials are all real misuse (great —
   flip to `enforcing`), or some are legitimate (refine the
   tool lists and continue dry-running until you're clean).

Dry-run is also what you flip to when something breaks in
production. Switching from `enforcing` to `dry_run` instantly
restores agent functionality while preserving the visibility you
need to debug what changed. Once you've fixed the underlying
issue (the agent legitimately needs a new tool, the tool list
is stale), flip back.

### Use deny-by-default on sensitive agents

For any agent that handles regulated data, executes shell
commands, makes financial decisions, or talks to customers
under your brand: **deny-by-default**. Set
`default_action="deny"`, populate `allowed_tools` with the exact
list the agent needs, and run in dry-run for a week to catch
anything you forgot.

Allow-by-default is fine for development, prototyping, and
agents whose tool surface is genuinely open-ended (e.g. coding
assistants on internal repos). For the production support bot
that can refund customer charges, allow-by-default is wrong.

### Use group records for fleets

Once you have more than three agents that should share a
permission policy, create an **agent group** (Dashboard → Agent
Groups) and attach the permission record to the group rather
than to each agent individually. Group inheritance picks up
through the resolution layer automatically.

This is mostly an operational quality-of-life improvement —
you'd otherwise be copy-pasting the same `allowed_tools` list
across N agents and missing one when you update it. The runtime
behaviour is identical to per-agent records.

### The org-default trap

The org-wide default record is the easiest one to misconfigure
because its blast radius is the entire fleet. The most common
mistake is setting `default_action="deny"` org-wide with a tight
`allowed_tools` list — every agent that doesn't have its own
specific permission record now denies anything outside that
list, which is rarely what was intended.

The recommended shape for the org default is **`disabled` mode**.
It exists, the tool lists are populated for documentation, but
nothing fires unless you bump it to `dry_run` deliberately.
Per-agent and per-group records do the actual enforcement.

---

## What violations look like

When permissions deny a call, the SDK raises
`ParryPermissionDeniedError`. The exception inherits from
`ParryBlockedError` so a generic catch-all still works; the
specific exception lets you handle authorisation failures
differently from threat-detection blocks:

```python
from parry import ParryBlockedError, ParryPermissionDeniedError

try:
    response = client.chat.completions.create(...)
except ParryPermissionDeniedError as e:
    log.warn(
        "agent_not_authorized",
        tool=e.tool_name,
        reason=e.reason,
    )
    return canned_refusal()
except ParryBlockedError as e:
    log.warn("security_block", detector=e.detector, reason=e.reason)
    return canned_refusal()
```

The `tool_name` attribute is a best-effort extraction from the
denial reason; it's set when the reason follows the standard
format `Tool 'X' is explicitly blocked` or `Tool 'X' not in
allowlist`. For free-form reasons the attribute is `None`.

In the dashboard, denials show up in three places:

- **Incidents** — denials with `detector=permission_boundary`
  appear in the triage queue at `high` severity. They cluster
  by tool name, so a sudden burst of denials on a single tool
  surfaces immediately.
- **Audit Log** — every permission decision (and every
  permission record edit) is logged with actor, agent, tool,
  and reason. Useful for compliance evidence.
- **Webhooks** — the `permission.denied` event type fires with
  a payload containing `agent_id`, `tool_name`, and `reason`.
  Wire it into PagerDuty or Slack alongside `incident.created`.

---

## Reference: writing permission records

Permission records are managed through the API or the
dashboard. The fields are documented in the model:

```python
# Org-wide default — disabled, populated for documentation
upsert_permission(
    org_id=org.id,
    agent_id=None,                  # NULL = org default
    mode="disabled",
    default_action="allow",
    allowed_tools=[],
    blocked_tools=[],
)

# Production support bot — strict allowlist, enforcing
upsert_permission(
    org_id=org.id,
    agent_id=production_bot.id,
    mode="enforcing",
    default_action="deny",
    allowed_tools=[
        "lookup_customer",
        "issue_refund",
        "send_email",
    ],
    blocked_tools=[],               # nothing extra needed
)

# Dev agent — start in dry_run before tightening
upsert_permission(
    org_id=org.id,
    agent_id=dev_agent.id,
    mode="dry_run",
    default_action="deny",
    allowed_tools=["lookup_customer", "issue_refund"],
    blocked_tools=[],
)
```

Deleting a permission record falls back to the next layer in the
resolution order — deleting an agent-specific record means the
agent inherits from its group (if any) or the org default; if
neither exists, it falls back to allow-all. Audit-log entries
are preserved across deletion so you can still see what the
permissions looked like at any past point in time.

---

## Where to go next

- [Policies and Rules](policies-and-rules.md) — org-wide
  policies including the `tool_misuse` detector, which is the
  policy-side complement to per-agent permissions.
- [Detection Catalog](detection-catalog.md) — the
  `permission_boundary` decision in context with all other
  detectors.
- [Dashboard tour](dashboard-tour.md) — the Agent Detail page's
  Permissions card and the Agent Groups page.
- [Integrations](integrations.md) — wiring the
  `permission.denied` webhook into PagerDuty, Slack, or
  Opsgenie.
