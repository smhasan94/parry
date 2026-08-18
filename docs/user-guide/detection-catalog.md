# Detection Catalog

Parry ships with twelve built-in detectors, one cross-org threat
feed detector, and one LLM-based fallback. Together they cover the
attack surface that matters in practice — prompt injection,
jailbreaks, data exfiltration, tool misuse, privilege escalation,
behavioural drift, MCP manifest tampering, cost exploitation, and
cross-org pattern matching.

This catalog is the definitive reference for what each detector
looks at, when it triggers, and what severity it returns. If
you've seen a detector name show up in the dashboard, the
incidents API, or a webhook payload and want to know exactly what
it means, this is the page.

The same vocabulary is used everywhere: detection results carry a
`triggered` boolean, a `severity` (`critical` / `high` / `medium`
/ `low`), a `confidence` between 0 and 1, a human-readable
`reason`, and the `detector` name as a stable string. Every
detector below is named by its stable string identifier — that's
what shows up in webhooks, the audit log, and dashboard filters.

---

## The severity and confidence model

Severity answers "how bad is this if it's real." Confidence
answers "how sure are we that it's real." They're independent:
a detector can have very high confidence in a `medium`-severity
finding (the sensitive-data regex is rock-solid) and very low
confidence in a `critical`-severity finding (the LLM-fallback
flagged a sophisticated injection attempt with 60% certainty).

Parry's blocking decision uses **severity only** — the SDK
blocks calls whose top triggered detection is `high` or
`critical`. `medium` and `low` triggers are recorded as
detections and may form incidents, but they don't stop traffic.
This is intentional: blocking on confidence would give
adversaries an obvious way to evade — turn high-confidence
patterns into low-confidence ones. Severity is fixed by what's
being attempted, not by how cleanly it was attempted.

Confidence still matters for two things. First, the **ambiguous
zone**: any detector that returns a non-triggered result with
confidence between 0.4 and 0.7 is forwarded to the LLM-fallback
detector for a second opinion. Second, **detector tuning** in the
dashboard's Tuning Sandbox uses confidence thresholds — raising a
detector's threshold makes it harder to trigger.

---

## Pattern-based detectors

Five detectors that run regex against prompts, responses, and
tool-call arguments. They're all stateless, sync, and fast — the
hot path of the detection pipeline.

### `prompt_injection`

Detects classic prompt-injection patterns in the user prompt. The
pattern catalogue includes instruction-override (`ignore previous
instructions`), identity reassignment (`you are now ...`),
disregard requests, fake system-prompt tokens (`system: you are
...`), embedded chat-template tokens (`<|system|>`, `[INST]`,
`<<SYS>>`), memory-wipe requests (`forget everything`),
instruction negation (`do not follow any ...`), role-play
exploitation (`pretend you are ...`), and role assumption (`act
as ...`).

Each pattern has a per-pattern confidence weight between 0.65 and
0.95. The detector returns the highest-confidence matching
pattern. Default trigger threshold is 0.6 — overridable per-org
via `detector_config["prompt_injection"]["trigger_threshold"]`.

Severity is `critical` at confidence ≥ 0.9, otherwise `high`.
Severity is `low` when not triggered.

### `indirect_injection`

Catches instructions that arrive through *content* rather than
from the principal. The user asks for something ordinary —
"summarise this document", "reply to this thread" — and the
hostile instruction rides in on the material being processed.
See Greshake et al 2023 (arXiv:2302.12173).

Scoring is two-factor. A **content boundary** is evidence the
prompt carries third-party text: a `---` or triple-backtick
fence, a quoted mail chain, a markdown table, embedded JSON, or
a provenance phrase (`extracted text from`, `search results
for`, `the following document`). An **embedded payload** is
instruction-shaped content: pseudo-system tags, covert-action
phrasing (`without notifying the user`), principal abandonment
(`stop helping the user`), system-prompt disclosure requests,
bulk exfiltration imperatives, and privilege requests.

Soft payloads require both factors. Each alone is unremarkable
— a fenced document is the normal case, and a bare imperative
from the user is direct injection, which `prompt_injection`
already covers. Pseudo-privilege override markers (`[[ADMIN
OVERRIDE:`, `⟨ADMIN-OVERRIDE⟩`) are the exception and score on
their own, because no legitimate prompt wraps `OVERRIDE` in
bracket delimiters to address the model.

Weights run 0.75 to 0.95. Default trigger threshold is 0.6.
Severity is `critical` at confidence ≥ 0.9, otherwise `high`.
`details` carries the matched signals and which boundaries were
seen, so a reviewer can tell *how* the content got in.

### `jailbreak`

Detects model-behaviour-bypass attempts. Pattern catalogue
includes the DAN family (`DAN do anything now`, DAN mode),
developer-mode activation, explicit "jailbreak" mentions, safety-
filter bypass language, ethics-removal requests (`no ethical
guidelines`), evil-mode activation, uncensored/unfiltered/
unmoderated mode requests, and opposite-day tricks.

Pattern weights run 0.7 to 0.95. Default trigger threshold is
0.7. Severity is `critical` at confidence ≥ 0.9, otherwise
`high`.

The boundary with `prompt_injection` is intentional:
prompt-injection rewrites *what* the model is doing; jailbreak
rewrites *how* it's allowed to behave. They overlap and often
co-trigger — that's expected, not a bug.

### `privilege_escalation`

Looks for attempts to gain elevated permissions or disable
security controls. Runs against both the prompt and any tool-call
arguments. Patterns include sudo/root/admin permission requests,
self-elevation (`grant me admin`), permission-modification
attempts, run-as-admin patterns, security-override requests, and
auth/logging-disable requests.

When a pattern matches inside tool-call arguments rather than
the prompt itself, the detector appends `(in tool arguments)` to
the reason so reviewers can spot indirect attempts. Default
trigger threshold is 0.7. Severity is `critical` at confidence
≥ 0.9, otherwise `high`.

### `data_exfiltration`

Scans the LLM **response** (not the prompt) for sensitive data
that shouldn't have been generated. Patterns and their fixed
severities:

| Pattern | Severity |
| --- | --- |
| 16-digit credit-card number | `critical` |
| US SSN (`XXX-XX-XXXX`) | `critical` |
| API keys / secrets (`sk-...`, `api_key="..."`) | `high` |
| Password values (`password=...`) | `high` |
| PEM private keys | `critical` |
| AWS access/secret keys | `critical` |

Fixed confidence of 0.85 when triggered. Detection severity is
the maximum across all matched patterns. The detector is also
what powers the SDK's response-scan path — `mode=block`
configurations turn a triggered detection into a
`ParryBlockedError` raised at the agent.

Note that the SDK's PII-stripping happens **before** the prompt
or response leaves your process, so this detector is a defense-
in-depth layer for things the SDK regex didn't catch and for
content generated server-side.

### `tool_misuse`

The only pattern-free detector in this group — it consults
policy, not regex. Runs over each tool call in the event and
checks against the org's policy:

- if the tool name is in `blocked_tools` → triggered, severity
  `high`, confidence 0.95;
- if `allowed_tools` is non-empty and the tool name is not in
  it → triggered, severity `high`, confidence 0.95;
- otherwise → not triggered.

Reason text includes the count of violations and a `details.violations`
list naming each offending tool and why. With no policy
configured the detector is effectively off — there's nothing to
compare against. Configure policies on the **Policies** dashboard
page.

---

## User-defined detectors

### `custom_rules`

Runs every enabled custom rule against the event and reports
matches. Rules live in `detector_config["custom_rules"]` and are
managed through the dashboard's **Custom Rules** page. Each rule
has a name, a regex pattern, a target (`prompt`, `response`, or
`both`), an enabled flag, and a severity.

The detector's severity is the **maximum** across all matched
rules. Confidence is reported per-rule rather than aggregated —
the trigger condition is binary (regex matched or didn't), so
confidence here reflects rule-set state rather than a continuous
score. Invalid regex patterns are skipped at runtime; the API
write-path is the real validation guard.

The empty-rules case returns a non-triggered result with the
reason `No custom rules configured` so it's clearly visible on
the **Sessions** page when an event was checked but had nothing
to check against.

---

## Behavioural detectors

Four detectors that need state — either the agent's behavioural
baseline or recent session history — to operate.

### `anomaly`

The drift detector. Compares the current event's metrics
(`token_count`, `latency_ms`, `model`) against the agent's stored
baseline and flags significant deviations. Internally it computes
a **sigma deviation** — the absolute distance from the baseline
mean divided by the baseline's standard deviation — for each
metric.

| Setting | Default | Notes |
| --- | --- | --- |
| Sigma threshold | 3.0 | Configurable per-org. Lower = more sensitive |
| Min baseline quality | `medium` | `low`-quality baselines never alert (too few samples) |
| Quality multiplier | 1.0 / 1.33 / ∞ | High / medium / low — demands stronger evidence on noisier baselines |

Categorical anomalies (event used a model the baseline has never
seen, tool count is way outside the norm) are binary signals and
trigger regardless of sigma. Token-count and latency anomalies
trigger only above the effective sigma threshold.

Severity is `medium` for most drift; `high` is reserved for
combined drift (multiple metrics simultaneously off-baseline).
Confidence reflects the maximum sigma observed, normalised. Use
**Recompute baseline** in the dashboard whenever an agent's
prompt or model intentionally changes — drift alerts after a
deploy that legitimately shifted the agent's profile are noise,
not signal.

### `cost_exploit_loop`

Catches tight tool-call loops that burn tokens without making
progress. Looks at the most recent twenty events in the session
history and counts how many share the same tool-call signature
(sorted tuple of tool names) as the current event.

Triggers when the same signature appears in **at least ten of the
last twenty events** *and* the ratio is at least 0.5. Severity
`medium`. Confidence ramps from 0.6 to 0.95 as the ratio rises.
The most common cause is a prompt-injection that told the agent
to "keep calling the search tool forever." Catching it is cheap
because the signature comparison is just a sorted-tuple equality
check.

### `cost_exploit_verbosity`

Single-event detector for prompts whose token count is an order
of magnitude above the agent's baseline. Triggers when the ratio
of `token_count / baseline.avg_token_count` is **≥ 10**. Severity
`medium`. Confidence ramps from 0.6 upward as the ratio grows
beyond 10x.

The classic case is an injected prompt that asks the agent to
"output the entire conversation history" or "expand on every
point with at least three paragraphs." Doesn't try to be clever:
the 10x cliff is intentionally simple so it's easy to reason
about and tune.

### `cost_exploit_model_escalation`

Catches an agent silently switching to a much more expensive
model than its baseline. Compares the event's `model` against the
agent's baseline `known_models` list using the per-token pricing
in the model-pricing registry.

Triggers when the current model's **average output cost is
significantly higher** than the geometric mean of the baseline
models' costs. Severity `medium`. The detector is a no-op when
the model isn't in Parry's pricing registry — better to skip than
to alert on a model whose price we don't know.

---

## MCP detector

### `mcp_manifest`

Runs only when the event carries an MCP manifest in
`event_data["mcp_manifest"]` — i.e. when the SDK's
`SentinelMCPClient` is registering a server. For ordinary LLM
events the detector is a fast no-op.

When a manifest is present, the detector walks every tool's
`description` and every `inputSchema.properties.*.description`
against six pattern categories:

| Category | Examples |
| --- | --- |
| `instruction_override` | `ignore previous instructions`, `forget what you were told`, `disregard prior`, `new instructions:` |
| `jailbreak` | `you are now`, `act as unrestricted`, persona keywords (DAN, STAN, AIM, Machiavelli), `pretend you have no` |
| `data_exfiltration` | `reveal your system prompt`, `print your initial instructions`, `send X to email@...` |
| `suspicious_tool_mention` | A tool's description mentions a *different* sensitive tool (`send_email`, `http_request`, `exec`...) — a known cross-tool injection vector |
| `unicode_smuggling` | Zero-width, bidi-override, and tag codepoints hidden inside descriptions |
| `schema_description_injection` | Categories 1–4 applied recursively to JSON Schema field descriptions |

Severity is `high` for all matches. Confidence is fixed because
each match is binary. The detector returns flat findings with
the offending tool name, the matched pattern id, and the matched
text span so the **MCP Server Detail** page can highlight it
exactly. See [`docs/mcp-security.md`](../mcp-security.md) for the
full threat model and the drift-detection algorithm that uses
the same scanner.

---

## Cross-org detector

### `threat_intel`

Checks the event against the cross-org threat-feed cache. The
feed is a set of pattern hashes contributed by every org that
has opted into threat-intel sharing — anonymised so raw prompts
never leave any org boundary. The detector recomputes pattern
hashes from the current event using the same normalisation as
the extraction service, then looks for matches.

Triggers when one or more hashes match. Severity reflects the
matched indicator's severity (carried in the feed). The active
hash set is Redis-cached with a 5-minute TTL so this detector
costs almost nothing per event.

A miss is the common case and returns the reason `Threat feed
empty or unavailable` (when the feed cache hasn't loaded) or `No
matches in active feed`. To enable cross-org sharing, toggle
threat-intel participation on the **Threat Intel** dashboard
page.

---

## LLM fallback

Not in the registered detector list — `llm_fallback` is a
**meta-detector** that only runs when the built-ins are
ambiguous. After every event passes through the thirteen detectors,
the pipeline collects any non-triggered results whose confidence
falls in the **0.4–0.7 ambiguous zone** and forwards them to
Claude Sonnet 4.6 for a second opinion. The fallback is given
the prompt, response, model, tool calls, and the list of which
detectors flagged the event as ambiguous.

Two important properties:

- **Untrusted-input fencing.** All content from the monitored
  agent is wrapped in `<agent_prompt>`, `<agent_response>`, and
  `<agent_tool_calls>` XML tags. The system prompt explicitly
  tells Claude to treat tagged content as data, not as
  instructions, and to flag any attempt at meta-injection as
  evidence of prompt injection. Closing tags inside content are
  escaped to prevent fence-breaking.
- **On-prem mode disables it.** Air-gapped deployments skip the
  fallback entirely — the ambiguous zone falls through to "no
  confirmed detection" and the built-ins' verdicts stand on
  their own.

The fallback has a hard 20-second timeout (the Celery detection
task has a 30-second soft limit; the gap leaves room for the
hanging-API case to fail gracefully). Each call's input/output
tokens are tracked against the org's billing record so you can
see fallback spend on the **Org Cost Summary** card. When the
fallback confirms a threat, its result is appended to the event's
detection list with `detector="llm_fallback"`.

---

## Reference table

Every detector at a glance. Trigger threshold is the value
overridable via `detector_config["<name>"]["trigger_threshold"]`
where applicable; "n/a" means the detector triggers on something
other than a confidence score.

| Detector | Default threshold | Severity range | Stateful |
| --- | --- | --- | --- |
| `prompt_injection` | 0.6 | low → critical | no |
| `indirect_injection` | 0.6 | low → critical | no |
| `jailbreak` | 0.7 | low → critical | no |
| `privilege_escalation` | 0.7 | low → critical | no |
| `data_exfiltration` | n/a | low → critical | no |
| `tool_misuse` | n/a | low / high | needs policy |
| `custom_rules` | n/a | low → critical (per rule) | needs rules |
| `anomaly` | 3.0σ | low → high | needs baseline |
| `cost_exploit_loop` | 10/20 ratio ≥ 0.5 | low / medium | needs session history |
| `cost_exploit_verbosity` | 10x baseline | low / medium | needs baseline |
| `cost_exploit_model_escalation` | pricing comparison | low / medium | needs baseline |
| `mcp_manifest` | n/a | low / high | needs MCP manifest |
| `threat_intel` | n/a | mirrors indicator | needs feed cache |
| `llm_fallback` | ambiguous-zone gate | mirrors LLM verdict | meta-detector |

---

## Where to go next

- [Concepts](concepts.md) — definitions for the nouns this
  catalog used (event, detection, severity, confidence).
- [Dashboard tour](dashboard-tour.md) — where each detector's
  output shows up: Tuning Sandbox, Custom Rules, Threat Intel,
  Settings → Detector Tuning.
- [`docs/mcp-security.md`](../mcp-security.md) — the deeper
  threat model behind the MCP-manifest detector.
- [`docs/red-team.md`](../red-team.md) — how the bundled
  red-team corpus exercises every detector above.
