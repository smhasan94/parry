# Parry API — Reference

All routes live under `/api/v1/`. Auth is either a Clerk session JWT
(dashboard) or an SDK API key via `X-Parry-Secret` (runtime ingest).
The full machine-readable contract lives at `/openapi.json` on a
running backend — this doc covers the endpoints you'll hit most
often with a short example per route.

**Interactive reference:** `/docs/scalar` renders the full spec in a
Scalar API reference UI (search, try-it-out, schema drill-down).
`/docs` and `/redoc` are also available in non-production builds.

| Auth | Header |
| --- | --- |
| Dashboard user | `Authorization: Bearer <Clerk JWT>` |
| SDK runtime | `X-Parry-Secret: <sk-parry-...>` |

Quota errors return **HTTP 402** with `X-Upgrade-Required: true`
(see plan-11). Role errors return **403**.

---

## Agents

### `GET /api/v1/agents`
List the caller's agents. Each record carries the live health score
(plan-07) and a component breakdown.

```bash
curl -H "Authorization: Bearer $TOKEN" \
     https://api.parry.dev/api/v1/agents
```

### `POST /api/v1/agents` *(admin)*
Create a new agent. Enforced against the plan's `max_agents` limit.

### `GET /api/v1/agents/{agent_id}`
Full agent detail including baseline and health score breakdown.

### `GET /api/v1/agents/{agent_id}/stats?window=7d|30d|90d`
Behavioural graph data (plan-08): event volume, tool-call counts,
model usage, anomaly trend, detection counts. 5-minute cache.

### `GET /api/v1/agents/{agent_id}/sessions?limit=20`
Recent sessions for the agent (plan-12), newest first.

---

## Events

### `POST /api/v1/events/ingest` *(SDK)*
Fire-and-forget event write from the SDK. Enforced against the plan's
rolling 30-day event quota.

```bash
curl -X POST https://api.parry.dev/api/v1/events/ingest \
  -H "X-Parry-Secret: sk-parry-..." \
  -d '{"agent_id":"support-bot","prompt":"…","response":"…","model":"gpt-4o"}'
```

### `GET /api/v1/events/stream?agent_id=...`
Per-agent SSE event stream used by AgentDetailPage.

### `GET /api/v1/events/live-stream`
Org-wide SSE stream carrying blocked-call events from the Redis
pubsub bus (plan-09). 15-second keepalive, max 5 concurrent
connections per org.

---

## Proxy (blocking mode)

### `POST /api/v1/proxy/check` *(SDK)*
Synchronous pre-flight check before the LLM call fires. Returns
`{allowed: bool, reason, detector, severity, confidence}`. Blocks
trigger a pubsub publish on the live-stream channel.

### `POST /api/v1/proxy/scan-response` *(SDK)*
Post-call scan returning `{blocked, response, findings, mode}` —
off/redact/block three-way posture from plan-02.

---

## Incidents, Detections, Sessions

| Route | Notes |
| --- | --- |
| `GET /api/v1/incidents` | Cursor-paginated, filter by severity/status |
| `PATCH /api/v1/incidents/{id}` | Update status (admin+) |
| `GET /api/v1/sessions/{session_id}` | Full replay (plan-12). Viewer gets previews, admin gets full prompt+response |

---

## Policies, Custom Rules, Detector Config

| Route | Notes |
| --- | --- |
| `GET/POST/PATCH/DELETE /api/v1/policies` | Tool allowlist, blocked domains, forbidden patterns |
| `GET/POST/PATCH/DELETE /api/v1/custom-rules` | Regex rules (plan-05). Feature-gated on GROWTH+ |
| `POST /api/v1/custom-rules/test` | Live regex preview |
| `GET/PUT /api/v1/detector-config` | Per-detector thresholds and toggles |

---

## Alerts, Reports, Billing

| Route | Notes |
| --- | --- |
| `GET/PUT/DELETE /api/v1/alerts` | Slack, email, webhook, PagerDuty (plan-10), Opsgenie (plan-10). Secrets returned masked |
| `POST /api/v1/alerts/test?channel=slack\|email\|webhook\|pagerduty\|opsgenie` | Send a synthetic test incident |
| `GET /api/v1/reports/compliance?start=...&end=...` | PDF export (plan-06). Admin+, feature-gated, 90-day sync cap |
| `GET /api/v1/billing/plan` | Current plan + limit table (plan-11) |
| `POST /api/v1/billing/checkout` | Stripe Checkout session |
| `POST /api/v1/billing/portal` | Stripe Billing Portal link |
| `POST /api/v1/webhooks/stripe` | Signed Stripe webhook receiver |

---

## Audit log

### `GET /api/v1/audit-log?action=...&resource_type=...&cursor=...`
Tamper-evident record of every mutating action. Append-only from
application code; intended for SOC 2 review and incident forensics.

---

## Error format

All non-2xx responses carry a JSON body:

```json
{"detail": "human-readable reason", "code": "optional_machine_code"}
```

402 responses additionally set `X-Upgrade-Required: true` so the
dashboard can prompt via the global UpgradeModal without every
caller catching the error locally.

---

For the live machine-readable spec, hit `/openapi.json` on any
running backend and feed it to Scalar / Swagger UI / your client
generator of choice.
