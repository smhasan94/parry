# Integrations

Parry doesn't expect to be the place your team does triage. The
dashboard is the source of truth for investigations, but
practical incident response happens in Slack, PagerDuty,
Opsgenie, email, and your own internal systems. Integrations are
how Parry pushes the right signal to the right channel without
making the dashboard the only place anyone checks.

This guide covers the five outbound channels — webhooks, Slack,
PagerDuty, Opsgenie, email — and the inbound auth integration
(SSO via WorkOS). Each section explains what fires, when it
fires, and how to configure it without overwhelming your
on-call.

If you've already toured the dashboard, the **Settings → Alerts**
and **Webhooks** pages are the corresponding UI; this is the
conceptual reference for what each channel is for and how to
choose between them.

---

## Choosing a channel

The five outbound channels solve different problems:

| Channel | Best for | Latency target |
| --- | --- | --- |
| **Webhooks** | Custom integrations, internal tooling, audit pipes | Within seconds |
| **Slack** | Team awareness, async investigation | Within seconds |
| **PagerDuty** | Pages on-call for genuinely page-worthy incidents | Within seconds |
| **Opsgenie** | Same as PagerDuty if that's your IR stack | Within seconds |
| **Email** | Compliance digests, quiet channels for low-severity findings | Minutes acceptable |

Most orgs use one or two of these in production. The default
recommendation is **Slack for awareness, PagerDuty (or Opsgenie)
for paging, and webhooks for whatever bespoke pipe you already
have**. Email is most useful for stakeholders who don't live in
your incident-response channels — security leadership, audit
teams, compliance.

---

## Webhooks

Webhooks are the lowest-level integration: Parry sends an HTTP
POST to a URL you provide, with an HMAC-SHA256-signed JSON
payload, when one of seven event types fires. They're the right
choice when you have an internal system that needs to react to
Parry events programmatically, or when none of the higher-level
channels fit.

### Event types

Seven event types ship today:

| Event type | When it fires |
| --- | --- |
| `detection.triggered` | Any detector triggers, including dry-run mode |
| `incident.created` | A new incident is opened (severity ≥ medium typically) |
| `incident.resolved` | An incident is moved to resolved status |
| `permission.denied` | Permission boundary blocks a tool call |
| `threat_intel.match` | An event matches the cross-org threat feed |
| `agent.created` | A new agent registers (auto-discovery on first SDK call) |
| `budget.exceeded` | A configured budget threshold is crossed |

An endpoint with an empty `event_types` array subscribes to
**all** events. Most subscriptions are narrower — wire
`incident.created` and `permission.denied` to your internal
ticket system, leave the high-volume `detection.triggered` for
analytics-only consumers.

### Signing and verification

Every payload is signed with HMAC-SHA256 using the per-endpoint
secret. The secret is shown to you once at endpoint creation and
never again — copy it immediately and store it somewhere your
receiver can read.

Verification on your end:

```python
import hmac, hashlib

def verify(payload: bytes, secret: str, signature: str) -> bool:
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

Use a constant-time comparison (`hmac.compare_digest`) — a
naïve string `==` leaks timing information that lets an attacker
forge signatures.

### Retry and failure handling

Delivery runs through Celery with `retry_backoff=True` and
`max_retries=3`. Each delivery attempt has a hard 30-second time
limit. The full timeline if your endpoint is unreachable:

1. First attempt — fails.
2. Retry after a backoff (Celery default: 0–60 s).
3. Retry after exponential backoff up to `retry_backoff_max=300 s`.
4. Final retry.
5. After three failed attempts, the delivery is recorded with
   the final error and the endpoint's `failure_count` is
   incremented.

Endpoints that hit **10 consecutive failures** are
auto-disabled. The dashboard surfaces this with a "Disabled"
badge and the failure count; you re-enable manually after
fixing the receiver. The auto-disable exists because a customer
endpoint that's been broken for hours is almost always
permanently broken, and continuing to retry just wastes worker
capacity.

Every attempt is recorded in the **Webhook Deliveries** view —
status code, response body, error, attempt number — for
debugging without having to grep your own logs.

### Testing

The dashboard's **Send test** button delivers a synthetic
payload using whichever event types your endpoint subscribes to,
signed with the real secret. Use it during initial setup and
any time you change your receiver. The synthetic payload is
flagged with a `test: true` field so your receiver can ignore it
in production logic.

---

## Slack

Slack is configured at **Settings → Alerts → Slack** with an
incoming-webhook URL. There's no app to install — incoming
webhooks are a Slack-native concept, and Parry's payload uses
the standard Block Kit shape.

The default configuration sends one message per `incident.created`
event, with severity, agent, detector, reason, and a link back
to the dashboard. The message format is intentionally compact;
the dashboard is one click away, and a wall of text in Slack
makes the signal harder to find.

### Severity gating

Every alert channel respects a `min_severity` setting. Default
is `high`, meaning Slack only gets `high` and `critical`
incidents — `medium` and below stay in the dashboard. You can
override per-channel if your team wants tighter or looser
filtering. For Slack we recommend keeping the default — anything
lower turns the channel into noise.

### What gets sent

Each Slack alert includes:

- Severity badge (colour-coded).
- Incident title.
- Detector name and reason.
- Affected agent name with link to the agent-detail page.
- "View incident" button linking to the triage queue.

The payload is rendered through `build_slack_payload`. If you
need a different format, fork the channel and use a webhook
endpoint instead — most teams find the default sufficient.

---

## PagerDuty

PagerDuty integration uses Events API v2 with a routing key per
service. Configure at **Settings → Alerts → PagerDuty** by
pasting a routing key from a PagerDuty service that's wired to
your on-call rotation.

PagerDuty's priority levels map to Parry severities:

| Parry severity | PagerDuty priority |
| --- | --- |
| `critical` | P1 |
| `high` | P2 |
| `medium` | P3 |
| `low` | P4 |

The alert dedup-key is the incident ID, so multiple detections
that group into the same incident don't page twice. Resolving
the incident in Parry sends a corresponding `resolve` event to
PagerDuty so the page closes automatically.

The default `min_severity` for PagerDuty is `high`. **Don't
lower this** — paging on `medium` or `low` is how on-call
fatigue starts. If you're getting too many high-severity
incidents that don't actually need a page, the right fix is
detector tuning ([Detection Catalog](detection-catalog.md) and
the Tuning Sandbox), not a quieter PagerDuty config.

---

## Opsgenie

Opsgenie configuration mirrors PagerDuty. Same idea, different
incident-response stack. Configure at **Settings → Alerts →
Opsgenie** with an API key from your Opsgenie integration
(`Genie integration` → API).

Severity-to-priority mapping is built into the dispatch service:
`critical` → P1, `high` → P2, `medium` → P3, `low` → P4. The
default `min_severity` is again `high`.

If you have both PagerDuty and Opsgenie configured (rare,
usually a migration scenario), both fire. Each channel's
delivery is independent — failure on one doesn't suppress the
other.

---

## Email

Email is the slowest and quietest channel and that's the point.
It's where compliance digests, quarterly summaries, and
low-severity rollups go. Configuration requires SMTP at the
deployment level (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`,
`SMTP_FROM`); per-org config is just the recipient list at
**Settings → Alerts → Email**.

Email payloads are HTML formatted and include the same incident
details as Slack but rendered for offline reading: severity,
agent, detector, reason, dashboard link. Email is also the
channel the **Compliance Reports** export uses to deliver
generated PDF bundles to recipients, scheduled or on-demand.

The `min_severity` default for email is `high`, but many orgs
configure email at `medium` so audit teams have a paper trail
of every escalation event. If you do that, send to a
dedicated list — never to individuals.

---

## Configuring multiple channels at once

The alert service evaluates all configured channels for every
incident. The flow is:

1. Incident is created with severity X.
2. For each channel (Slack, PagerDuty, Opsgenie, email,
   webhooks): check `min_severity` for that channel.
3. Channels that pass the gate dispatch in parallel.
4. Failures on one channel don't suppress others. Each is
   logged separately so you can debug a single channel's
   failures.

This is why the recommended posture is multiple channels
serving different purposes: Slack at `high` for team awareness,
PagerDuty at `critical` for paging only, email at `medium` for
the paper trail. One incident might fire Slack and email but
not PagerDuty; another might fire all three. Each channel does
the right thing without coordinating with the others.

---

## SSO

Single sign-on is the inbound auth integration. Parry uses
WorkOS for SAML and OIDC, which means the SSO setup looks the
same whether your IdP is Okta, Microsoft Entra, Google
Workspace, JumpCloud, or any other SAML/OIDC provider.

SSO is gated to the **Enterprise plan**. Once enabled, the
configuration flow is:

1. **Owner** clicks **Settings → SSO → Configure** in the
   dashboard.
2. The dashboard launches a WorkOS Admin Portal in a new tab
   with your org pre-provisioned.
3. Your IdP admin completes the connection inside the Admin
   Portal — pasting metadata, configuring attribute mappings,
   testing the assertion.
4. Once the connection shows "Active", users from your domain
   can sign in via `app.parry.dev/sso/<your-domain>`.

The Admin Portal handles all the IdP-specific quirks (entity
IDs, ACS URLs, attribute names) so you don't need to. From
Parry's side, every successful login produces an `SSOProfile`
with the user's email, first/last name, and IdP-provided
profile fields; new users are auto-created in your org with the
`viewer` role and an admin can promote.

### Justification for owner-only

SSO setup affects every user in the org and is rarely undone.
Keeping it owner-only matches the broader pattern that "things
that affect billing or org-wide auth are owner-controlled" —
admins manage day-to-day operations, owners manage how the org
exists.

### SCIM

SCIM directory sync is on the roadmap and not yet shipped.
For now, user provisioning is JIT (just-in-time) on first SSO
sign-in; deprovisioning happens through the dashboard's user
management UI rather than auto-disabling on IdP removal.

---

## Operational tips

### Use webhooks as the audit pipe

Even if you're using Slack, PagerDuty, and email for the
human-facing channels, configure a low-volume webhook subscribed
to all seven event types and send the payloads to your data
warehouse or audit pipe. This gives you a queryable record of
every event Parry fired without having to integrate against the
Parry API on a polling cadence.

### Test channels quarterly

Each alert channel has a **Send test** button. Run them on a
schedule (your engineering ops channel can own this). The
worst time to discover that your PagerDuty routing key got
revoked six months ago is during a real incident.

### Don't over-subscribe

`detection.triggered` fires on every triggered detection,
including `low` and `medium`. A webhook subscribed to it on a
high-traffic agent will fire hundreds of times per day. Subscribe
narrowly unless your downstream system can handle (and care
about) that volume.

### Separate paging from awareness

The single most common alerting mistake is sending the same
threshold to both PagerDuty and Slack. PagerDuty wakes someone
up; Slack notifies a channel. They have different escalation
contracts. Slack at `high`, PagerDuty at `critical`, and
explicit per-channel tuning. If a `medium` incident is worth
discussing it goes to Slack; if it's worth paging an on-call,
the severity should be `high` or higher.

---

## Where to go next

- [Dashboard tour](dashboard-tour.md) — the **Settings →
  Alerts** and **Webhooks** pages where every channel above is
  configured.
- [Permissions](permissions.md) — `permission.denied` is one of
  the seven webhook events; the permissions guide explains
  what triggers it.
- [Cost & Budgets](cost-and-budgets.md) — `budget.exceeded` is
  another; the budgets guide explains the threshold model.
- [Detection Catalog](detection-catalog.md) — what each
  detector emits when it triggers, which feeds
  `detection.triggered` and `incident.created`.
