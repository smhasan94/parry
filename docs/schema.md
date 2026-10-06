# Database schema

PostgreSQL 16 with the TimescaleDB extension. All migrations live in
`backend/alembic/versions/` — treat this doc as a human-readable
companion, not a substitute for running `alembic upgrade head` to
see the exact DDL.

Naming conventions:

- Primary keys: `uuid` via `gen_random_uuid()` except `agent_events`,
  which uses a composite `(id, timestamp)` so the hypertable can
  partition cleanly.
- Timestamps: `created_at` / `updated_at` are timezone-aware and
  maintained automatically by SQLAlchemy's `TimestampMixin`.
- Tenant isolation: every mutable table carries `org_id` or inherits
  ownership through a parent (agent → org, session → agent → org).

---

## `orgs`
Top-level tenant. One per Clerk organization.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | |
| `name` | varchar(255) | |
| `clerk_org_id` | varchar(255) unique | maps to Clerk |
| `stripe_customer_id` | varchar(255) nullable | created lazily on first billing action |
| `is_active` | bool | |
| `alert_config` | jsonb nullable | `slack_webhook_url`, `alert_emails`, `webhook_url`, `pagerduty_routing_key`, `opsgenie_api_key`, `min_severity` |
| `detector_config` | jsonb nullable | per-detector thresholds + `custom_rules` list |
| `blocking_enabled` | bool | active blocking posture |
| `response_scan_mode` | enum(off/redact/block) | response scanning posture |
| `plan` | enum(free/growth/pro/enterprise) | subscription tier |
| `metadata` | jsonb nullable | |

---

## `api_keys`
SDK credentials, one org → many keys. Key material is hashed; only
the prefix is recoverable for UI display.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | |
| `org_id` | uuid FK → orgs | cascade on delete |
| `name` | varchar(255) | |
| `key_hash` | varchar(255) unique | SHA-256 of raw key |
| `key_prefix` | varchar(20) | `sk-parry-...` preview shown in UI |
| `is_active` | bool | |
| `last_used_at` | timestamptz nullable | |

---

## `agents`
Named, persistent AI processes monitored by Parry.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | |
| `org_id` | uuid FK → orgs | cascade |
| `name` | varchar(255) | unique per org via `uq_agent_org_name` |
| `description` | text nullable | |
| `is_active` | bool | |
| `baseline` | jsonb nullable | avg/std token counts, tool-call stats, quality tier |
| `metadata` | jsonb nullable | |

---

## `agent_sessions`
Groups related events within one conversation/run of an agent.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | |
| `agent_id` | uuid FK → agents | cascade |
| `ended_at` | timestamptz nullable | null = live (session replay polls every 5s) |
| `metadata` | jsonb nullable | |

---

## `agent_events` *(TimescaleDB hypertable)*
Atomic unit of monitoring — one LLM call, with full prompt + response.

**Critical:** this is a hypertable partitioned by `timestamp`, so the
primary key is the composite `(id, timestamp)`. TimescaleDB doesn't
support inbound FKs into hypertables — `detections.event_id` points
here but has no referential constraint.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | composite PK with `timestamp` |
| `timestamp` | timestamptz | composite PK, server_default `now()`, indexed |
| `agent_id` | uuid FK → agents | indexed, cascade on delete |
| `session_id` | uuid FK → agent_sessions nullable | set null on delete |
| `prompt` | text nullable | full text, SDK truncates to 4000 chars client-side |
| `response` | text nullable | full text |
| `model` | varchar(100) nullable | |
| `tool_calls` | jsonb nullable | array of `{name, args, ...}` |
| `latency_ms` | integer nullable | |
| `token_count` | integer nullable | |
| `metadata` | jsonb nullable | |

**Query discipline:** always filter by `agent_id` AND a `timestamp`
range. Never scan the table without a chunk-aware predicate.

---

## `detections`
Output of the detection pipeline — one row per detector run per event.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | |
| `event_id` | uuid indexed | **not** a FK (hypertable target) |
| `incident_id` | uuid FK → incidents nullable | set null on delete |
| `detector` | varchar(100) | `prompt_injection`, `anomaly`, `custom_rules`, … |
| `severity` | enum(critical/high/medium/low) | |
| `confidence` | float | 0.0–1.0 |
| `reason` | text | human-readable explanation |
| `triggered` | bool | false = observed, true = fired |
| `details` | jsonb nullable | detector-specific structured evidence |

---

## `incidents`
Grouped detections that require human review.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | |
| `org_id` | uuid FK → orgs | cascade |
| `agent_id` | uuid FK → agents | cascade |
| `title` | varchar(500) | auto-generated from the top detection |
| `severity` | enum(critical/high/medium/low) | |
| `status` | enum(open/acknowledged/resolved/dismissed) | default `open` |
| `resolved_at` | timestamptz nullable | |
| `metadata` | jsonb nullable | |

---

## `policies`
Org-defined guardrails. Merged into the detection event context.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | |
| `org_id` | uuid FK → orgs | cascade |
| `name` | varchar(255) | |
| `description` | text nullable | |
| `is_active` | bool | |
| `allowed_tools` | jsonb nullable | allowlist |
| `blocked_tools` | jsonb nullable | denylist |
| `allowed_domains` | jsonb nullable | |
| `blocked_domains` | jsonb nullable | |
| `max_token_budget` | integer nullable | |
| `forbidden_patterns` | jsonb nullable | regex list |
| `custom_rules` | jsonb nullable | legacy — new custom rules live on `orgs.detector_config` |

---

## `audit_log`
Append-only tamper-evident record. No updates or deletes from
application code. Used for SOC 2 / ISO 27001 review.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | |
| `org_id` | uuid FK → orgs indexed | cascade |
| `actor_type` | varchar(20) | `user` / `api_key` / `system` |
| `actor_id` | varchar(255) nullable | denormalized Clerk user id / ApiKey uuid |
| `actor_label` | varchar(255) nullable | email, key name |
| `action` | varchar(100) indexed | e.g. `custom_rule.created` |
| `resource_type` | varchar(50) nullable | |
| `resource_id` | varchar(255) nullable indexed | |
| `details` | jsonb nullable | before/after diff, IP, UA |
| `created_at` | timestamptz | server_default `now()`, indexed |

---

## Indexes worth knowing about

- `agent_events (agent_id)` + TimescaleDB chunk index on `(timestamp)`
- `detections (event_id)` — feeds the session replay join
- `audit_log (org_id, created_at)` and `(action)`, `(resource_id)` —
  for the audit timeline and filtered lookups
