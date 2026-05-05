# Compliance

Parry's Compliance module is built around the EU AI Act —
specifically Articles 26 and 27 (deployer obligations) and
Article 73 (serious incident reporting). The module is designed
for a single audience: companies deploying AI agents into the
European market who are now legally accountable for what those
agents do.

This guide explains what the module covers, how each obligation
is evaluated, and the operational workflow for using it well.
It assumes you already know whether you're a deployer of a
high-risk system; if you don't, the [European Commission's
guidance pages](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)
are the primary source. We don't give legal advice — we give
you the evidence and process to demonstrate compliance.

---

## What the module covers

The Compliance page in the dashboard is organised into five
tabs:

| Tab | Purpose |
| --- | --- |
| **Posture** | Real-time status of every Article 26 obligation |
| **AI Systems** | Your register of in-scope AI systems (Article 26(1)) |
| **Suppliers** | Third-party model and service providers you depend on |
| **FRIA** | Fundamental Rights Impact Assessments per high-risk system (Article 27) |
| **Incidents** | Serious incident log with 15-day reporting deadline (Article 73) |

The module is gated to the **Pro plan and above**. The auditor
bundle export is gated to **Enterprise**.

---

## Risk classification

The Act classifies AI systems into four tiers based on Annex III.
Parry's `risk_level` field uses these directly:

| Level | What it means | What you must do |
| --- | --- | --- |
| `unacceptable` | Forbidden by Article 5 — social scoring, real-time biometric ID, etc. | Don't deploy. Parry flags this as a configuration error. |
| `high` | Annex III categories — recruitment, credit scoring, education access, healthcare, etc. | Full Article 26 + 27 obligations, including FRIA |
| `limited` | Transparency obligations only — chatbots that interact with humans, AI-generated content | Disclosure to end users; lighter logging requirements |
| `minimal` | Everything else | No mandatory obligations, but logging is good practice |

Most operator concern lives at the `high` level. Limited-risk
systems still benefit from being registered in the AI Systems
tab — the audit trail is identical and the posture page
correctly excludes limited-risk systems from `high`-only
obligations.

The risk classification you assign at registration determines
which obligations apply on the **Posture** tab. Misclassifying a
high-risk system as limited won't make obligations disappear —
it'll just hide them from the dashboard, which is worse than
seeing them red.

---

## Posture: the seven Article 26 obligations

The Posture tab evaluates seven obligations against your live
configuration and recent activity. Each obligation returns
**green / yellow / red / na**:

- **green** — obligation satisfied, evidence available.
- **yellow** — partially satisfied or pending action required.
- **red** — not satisfied; immediate action needed.
- **na** — not applicable to your current systems (e.g. FRIA on
  an org with no high-risk systems).

The overall posture is the worst status across all applicable
obligations. The page caches results in Redis to keep the
dashboard responsive; the cache invalidates on any system,
incident, or audit-log change.

### The seven checks

| Article | Obligation | What's evaluated | When it goes red |
| --- | --- | --- | --- |
| Art. 26(2) | Human oversight assigned | RBAC enabled, org active | Org config missing (extremely rare) |
| Art. 26(4) | Monitor for risks during operation | Detector config present and recent events flowing | Detection disabled or no events in 7 days |
| Art. 26(5) | Suspension capability for serious risks | Blocking mode enabled | Stays yellow until you flip blocking on |
| Art. 26(6) | Maintain usage logs ≥ 6 months | Audit log entries exist | No audit log entries (effectively impossible after first event) |
| Art. 26(11) | EU database registration for high-risk systems | All `high` systems have `eu_database_registered=true` | Any high-risk system unregistered |
| Art. 27 | FRIA for high-risk systems | Each high-risk system has an approved, fresh FRIA | Missing or stale FRIA |
| Art. 73 | Serious incident reporting within 15 days | Every CRITICAL Parry incident has a serious-incident report filed within 15 days | Any overdue report |

The remediation field on each obligation tells you exactly what
to do to flip it green. "Enable blocking mode to exercise Art.
26(5) suspension obligation" is the remediation for the
suspension check; "Register high-risk systems in the EU database
via your competent authority" for Art. 26(11). You don't need to
be an Act expert to act on the dashboard — every red item ships
with a fix.

### Why posture is a leading indicator

The 7-day recent-events check on Art. 26(4) is the most
operationally interesting. If your agents stop sending events
to Parry — because the SDK got removed, an environment variable
got dropped, or a deploy broke the integration — that
obligation goes yellow within days. Compliance posture surfaces
silent SDK breakage faster than the SDK Health page does, which
makes it useful even for orgs that aren't otherwise focused on
the AI Act.

---

## AI Systems register

The Article 26 deployer register requires you to maintain a list
of every in-scope AI system you deploy. The **AI Systems** tab
is that list, structured with the fields auditors and
authorities ask for:

| Field | Required | Notes |
| --- | --- | --- |
| `name` | yes | Human-readable identifier |
| `description` | no | Free-form |
| `risk_level` | yes | `unacceptable` / `high` / `limited` / `minimal` |
| `intended_purpose` | yes | Article 26(1) — what the system is supposed to do |
| `deployer_name` | yes | Your organisation's legal name |
| `provider_name` | yes | The model provider (OpenAI, Anthropic, etc.) |
| `provider_contact` | yes | Provider's compliance contact |
| `deployment_date` | yes | When the system went live |
| `retired_date` | no | Set when you stop using the system |
| `agent_ids` | yes | Maps the system to one or more Parry agents |

The `agent_ids` mapping is what links compliance to runtime
reality. A system with mapped agents inherits their detection
events, incident history, and audit log entries — that's the
evidence the auditor bundle compiles when you export.

A system with no mapped agents is just a paper register. It
satisfies the existence obligation but doesn't give you
operational evidence. Always map at least one agent.

---

## Suppliers

Article 26 mandates that deployers track upstream providers.
The **Suppliers** tab is a simpler register: name, contact,
service-level commitments, the systems they power. It's
intentionally lightweight — most orgs only have two or three
suppliers (OpenAI, Anthropic, maybe one more) and copy-pasting
the same information into a heavyweight workflow tool is
overkill.

The supplier register is referenced from the auditor bundle
export, so keeping it current saves time later when you're
under deadline pressure.

---

## FRIA

Fundamental Rights Impact Assessment is required for high-risk
systems under Article 27. The FRIA tab walks you through the
prescribed format with a generated template that's pre-filled
from the AI System record. The lifecycle:

1. **Draft.** Click **Generate FRIA** on a high-risk system to
   create a draft document. The generator pre-fills name,
   intended purpose, deployment date, mapped agents, recent
   detection statistics, and the standard FRIA section
   structure.
2. **Edit.** Work through each section. The template covers
   data subject categories, foreseeable risks, mitigation
   measures, monitoring procedures, escalation paths, and the
   review schedule. Most sections have prompts.
3. **Approve.** When the FRIA is ready, click **Approve**.
   Approval renders the document to PDF and stores both the
   structured content and the bytes for export. The system's
   `fria_status` becomes `approved` and the Art. 27 obligation
   flips green.
4. **Refresh.** FRIAs go stale — typically annually, or
   sooner if the system materially changes. The Posture page
   shows stale FRIAs as yellow; re-generate or revise to
   refresh.

The FRIA template is conservative. It captures everything
auditors typically ask for; you can prune sections that don't
apply but you can't omit the structure. This is by design —
the cost of being too thorough at FRIA time is small; the cost
of having a document the regulator deems insufficient is much
larger.

---

## Serious incidents (Article 73)

Article 73 requires deployers to report serious incidents to
the relevant authority within **15 days**. Parry treats every
`critical` incident as a candidate serious-incident report and
auto-creates a draft on the **Incidents** tab.

The auto-draft includes:

- The originating Parry incident ID and link.
- The mapped AI system (if any).
- The 15-day deadline (`created_at + 15 days`), prominently
  displayed.
- Pre-filled fields for date, description, harm assessment,
  affected parties.
- A `report_version` field for tracking revisions.

Your job is to:

1. Triage the incident inside Parry's normal flow.
2. Decide whether it's actually a "serious incident" under
   Article 73's definition (critical-severity in Parry doesn't
   automatically mean Article 73 applies — but the auto-draft
   ensures you don't *miss* one).
3. If it is, complete the report, file with the relevant
   authority, and record `reported_to_authority_at` in Parry.

The Posture page tracks this:

- **Green** — every recent CRITICAL incident has either been
  reported or determined-not-serious within the deadline.
- **Yellow** — there are unreported drafts but none overdue.
- **Red** — at least one report is past the 15-day deadline.

The deadline timer is not optional. Once an incident is created,
the clock starts. The page shows time-remaining, and webhook
subscribers can wire `incident.created` filtered to
`severity=critical` into a calendar reminder system to avoid
relying on dashboard checking.

---

## The auditor bundle

The auditor bundle is a single-archive export containing every
artefact a regulator typically asks for in an Article 26 audit:

- The AI Systems register, structured CSV plus PDF.
- Every approved FRIA's PDF.
- Every serious-incident report's PDF.
- The suppliers register.
- Audit log entries for the requested window.
- Detection-event statistics aggregated by system.
- Compliance posture snapshot at export time.
- A generation-manifest documenting what's in the bundle and
  when it was produced.

Bundles are generated asynchronously — the request returns a
job ID and you get a webhook (`compliance.bundle_ready`) when
the archive is ready for download. Generation takes seconds to
minutes depending on data volume.

The bundle is gated to **Enterprise**. The reasoning: it's the
artefact regulators ask for, which means producing it has to be
on-demand and high-fidelity, which costs real compute. Smaller
plans get the underlying register and FRIA exports as PDFs
individually.

---

## Operating cadence

Three habits that keep compliance from being a fire drill at
audit time:

**Quarterly posture review.** Open the Posture tab, expect
green across the board. Anything yellow gets a ticket. Anything
red gets escalated. The cadence is your forcing function —
without it, posture drifts and the next time you look is the
week before an audit, which is the worst time to discover a
red.

**Annual FRIA refresh.** Schedule a standing review of every
approved FRIA. Most won't need substantive changes; the
exercise is confirming that and recording it. The Posture
yellow-on-stale flag is the safety net.

**Pre-audit dry run.** Two weeks before an external audit,
generate the auditor bundle and walk it. Compare what's in it
against what you expect the auditor to ask for. Gaps surface
now, not in the meeting. The bundle is also useful as evidence
of "we already organised this for our quarterly internal
review" if the auditor asks.

---

## What this module is not

A few important non-promises:

- **Not legal advice.** Parry tracks evidence and surfaces
  obligations against the Act's text. Whether your specific
  deployment satisfies any given obligation in your specific
  jurisdiction is a question for your legal team.
- **Not certification.** No software product can certify you
  comply with the Act. The module makes the audit conversation
  faster and the evidence trail tighter; it doesn't replace
  the audit itself.
- **Not coverage of every regulation.** SOC 2, ISO 27001, HIPAA,
  PCI DSS, GDPR — these are separate regimes with different
  evidence requirements. Parry's audit log and webhook
  integrations support evidence collection for them, but the
  Compliance module is specifically about the EU AI Act.
- **Not a replacement for your DPO.** If your deployment is
  subject to the AI Act, you almost certainly also need GDPR
  data-protection processes. Parry's module doesn't replace
  those.

---

## Where to go next

- [Dashboard tour](dashboard-tour.md) — the Compliance and
  Reports pages in the UI.
- [Integrations](integrations.md) — wiring serious-incident
  alerts to PagerDuty, Slack, and email so the 15-day clock
  isn't tracked by humans.
- [Detection Catalog](detection-catalog.md) — what produces
  the `critical` incidents that become candidate Article 73
  reports.
- [`docs/red-team.md`](../red-team.md) — using the bundled
  attack corpus to demonstrate Article 26(4) "monitor for
  risks during operation" effectiveness.
