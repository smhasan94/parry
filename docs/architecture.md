# Parry — Architecture

## System overview

```
┌─────────────────────────────────────┐
│  Customer's AI Agent (Python)        │
│                                      │
│  from parry.wrappers.openai    │
│    import ParryOpenAI                │
└───────────────┬─────────────────────┘
                │ Every LLM call intercepted
                ▼
┌─────────────────────────────────────┐
│  Parry SDK (pip package)        │
│  - Wraps OpenAI / Anthropic / LC    │
│  - Strips PII client-side           │
│  - Sends event async to backend     │
│  - Returns original response        │
└───────────────┬─────────────────────┘
                │ POST /api/v1/events (async, fire-and-forget)
                ▼
┌─────────────────────────────────────┐
│  FastAPI Backend                     │
│  ┌─────────────────────────────┐    │
│  │  Proxy / Event Ingest Layer │    │
│  └──────────────┬──────────────┘    │
│                 │ Celery task        │
│  ┌──────────────▼──────────────┐    │
│  │  Detection Engine           │    │
│  │  - Rule-based detectors     │    │
│  │  - Statistical baselining   │    │
│  │  - LLM fallback (Claude)    │    │
│  │  - Policy enforcer          │    │
│  └──────────────┬──────────────┘    │
│                 │                    │
│  ┌──────────────▼──────────────┐    │
│  │  Incident Correlator        │    │
│  └──────────────┬──────────────┘    │
└─────────────────┼───────────────────┘
                  │
       ┌──────────┴──────────┐
       ▼                     ▼
┌────────────┐        ┌────────────────┐
│ PostgreSQL  │        │ Redis           │
│ + TimescaleDB│       │ (queue + cache) │
└────────────┘        └────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│  React Dashboard                     │
│  - Live agent feed (SSE)            │
│  - Incident review                  │
│  - Policy editor                    │
│  - Compliance export                │
└─────────────────────────────────────┘
```

## Database schema (key tables)

### orgs
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| name | text | |
| stripe_customer_id | text | |
| plan | enum | free/growth/pro/enterprise |
| created_at | timestamptz | |

### agents
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| org_id | uuid FK | |
| name | text | human-readable |
| external_id | text | caller-provided agent_id |
| baseline | jsonb | behavioral baseline stats |
| policy_id | uuid FK | |
| created_at | timestamptz | |

### agent_events (TimescaleDB hypertable, partitioned by created_at)
| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| agent_id | uuid FK | |
| session_id | uuid | |
| prompt_hash | text | SHA-256 of original prompt |
| prompt_preview | text | first 200 chars, PII-stripped |
| response_preview | text | first 200 chars, PII-stripped |
| model | text | |
| tool_calls | jsonb | |
| token_count | int | |
| latency_ms | int | |
| created_at | timestamptz | partition key |

### detections
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| event_id | uuid FK → agent_events | |
| detector | text | e.g. "PromptInjectionDetector" |
| triggered | bool | |
| severity | enum | low/medium/high/critical |
| score | float | 0.0–1.0 |
| reason | text | human-readable explanation |
| created_at | timestamptz | |

### incidents
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| org_id | uuid FK | |
| agent_id | uuid FK | |
| severity | enum | |
| status | enum | open/investigating/resolved |
| title | text | auto-generated |
| detection_ids | uuid[] | related detections |
| created_at | timestamptz | |
| resolved_at | timestamptz | nullable |

### policies
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| org_id | uuid FK | |
| name | text | |
| allowed_tools | text[] | e.g. ["web_search", "code_exec"] |
| blocked_domains | text[] | |
| max_tokens_per_call | int | nullable |
| forbidden_patterns | text[] | regex patterns |

### api_keys
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| org_id | uuid FK | |
| key_hash | text | bcrypt hash of key |
| key_preview | text | first 8 chars for display |
| name | text | |
| last_used_at | timestamptz | |

## Detection engine design

See `docs/detection-engine.md` for full detail.

Short version: every event goes through a synchronous rule-based pass first (fast, <5ms).
If confidence is ambiguous (0.4–0.7), a Celery task fires an async LLM call to Claude.
Results write to `detections` table. High/critical detections trigger SSE push to dashboard.

## Deployment (Render)

- `backend` → Render Web Service (Docker)
- `worker` → Render Background Worker (same image, different start command)
- `dashboard` → Render Static Site
- `postgres` → Render PostgreSQL (with TimescaleDB extension)
- `redis` → Render Redis

All environment variables managed via Render dashboard, never in code.
