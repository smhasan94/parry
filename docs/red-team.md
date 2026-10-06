# Red Team Your Agent

Parry ships a built-in red team runner that replays a curated corpus
of attack prompts through your agent's live detection configuration.
You get a single number — the percentage of attacks the pipeline
caught — plus the exact prompts that slipped through, so you can
prove your detection setup before something hostile actually arrives.

## What it does, concretely

A red team **run** is a one-shot evaluation. The orchestrator:

1. Loads the bundled corpus of attack prompts (see below).
2. Replays each prompt through the same `DetectionPipeline` your
   live traffic flows through, using the **target agent's** merged
   detector config and active policies.
3. Records `triggered`, `severity`, and `detector` per attack.
4. Computes a score (`detected / total`) and a per-category
   breakdown.

Sandbox runs do **not** persist `AgentEvent` or `Detection` rows —
they leave no footprint on your real telemetry, dashboards, or
quotas. Only `red_team_runs` and `red_team_results` rows are
written.

## The bundled corpus

48 attack prompts across 8 categories, 6 per category:

| Category | Tests for |
| --- | --- |
| `instruction_override` | "Ignore previous instructions"–style hijacks |
| `jailbreak` | DAN, role-play, "you are now…", grandma exploits |
| `data_exfil` | Steering toward leaking system prompt or secrets |
| `tool_hijack` | Convincing the agent to call destructive tools |
| `privilege_escalation` | Asking for admin actions outside scope |
| `content_smuggling` | Unicode bidi/zero-width payloads, encoding tricks |
| `indirect` | Payloads embedded in fake tool output / retrieved docs |
| `cost_exploit` | Forcing expensive recursion, max-token loops |

The corpus lives at
`backend/app/detection/red_team_corpus/*.json`. It's validated and
de-duplicated at import time. The API never returns prompt text to
the client — only counts. This is intentional: the corpus is part
of the product, and shipping it raw to every dashboard view would
let it leak.

`GET /api/v1/red-team/attacks` returns category counts only:

```json
{ "total": 48, "by_category": { "instruction_override": 6, "jailbreak": 6, ... } }
```

## Starting a run

```bash
curl -X POST https://api.parry.dev/api/v1/red-team/runs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "<uuid>", "mode": "sandbox"}'
```

Returns `202 Accepted` with the run ID. The actual replay happens in
a Celery task — the API doesn't block while 48 detectors fire.

Polling pattern (the dashboard uses 2-second intervals while a run
is `queued` or `running`, then stops):

```bash
curl -H "Authorization: Bearer $TOKEN" \
     https://api.parry.dev/api/v1/red-team/runs/$RUN_ID
```

Run status transitions:

```
  queued ──▶ running ──▶ completed
                  │
                  └────▶ failed   (orchestration error, not a detection miss)
```

A "missed" attack — one the pipeline failed to detect — counts as a
result, not a run failure. The point of the run is to find those.

## Reading the results

The detail response includes:

- `score` — `detected / total`, expressed as a fraction
- `grade` — A/B/C/D/F derived from `score` thresholds
- `by_category` — same shape, scoped per category
- `undetected` — list of `{ attack_id, category, prompt }` for the
  attacks that slipped through, so you can see exactly what to tune

The dashboard's run detail page is built around the `undetected`
list. That's where you find the prompts to feed back into custom
rules or send to product as detector improvements.

## Plan gating

| Plan | `red_team` (sandbox) | `red_team_live` |
| --- | --- | --- |
| Free | ❌ | ❌ |
| Growth | ✅ | ❌ |
| Pro | ✅ | ✅ (planned) |
| Enterprise | ✅ | ✅ (planned) |

Sandbox mode is the only mode shipping today. Live mode (replaying
attacks against the real agent's LLM and observing actual responses)
is gated behind `red_team_live` and is on the roadmap for Pro+.

`POST /red-team/runs` is rate-limited to 5/min per org — these runs
are cheap individually but expensive in aggregate.

## API reference

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/v1/red-team/runs` | **Admin** | Start a run (202) |
| `GET`  | `/api/v1/red-team/runs` | Viewer | List runs |
| `GET`  | `/api/v1/red-team/runs/{id}` | Viewer | Run detail incl. undetected attacks |
| `GET`  | `/api/v1/red-team/attacks` | Viewer | Corpus counts only (no prompts) |

## Operational notes

- **Detection config drift.** A run is a snapshot of your
  configuration at run time. Changing detectors or policies after
  a run does not retroactively change the score. Re-run after
  policy changes to confirm improvements.
- **What to do with misses.** The `undetected` attacks are
  candidates for custom rules (`/api/v1/custom-rules`). The
  policy regression simulator lets you preview a custom
  rule against historical events before you enable it.
- **No live customer data is sent.** Sandbox mode does not call
  any LLM, does not touch your agent's runtime, and does not
  consume tokens. It's purely a pipeline replay.

## Roadmap

- **Live mode** — replay attacks through the real agent's LLM,
  capture responses, and grade detection + behavioural compliance
  separately. Pro+ feature, gated by `red_team_live`.
- **Customer-contributed attacks** — let orgs add their own
  prompts to a private corpus that runs alongside the bundled set.
- **Trend graphs** — sparkline of pass rate over time on the
  agent detail page, so you can see drift across releases.
