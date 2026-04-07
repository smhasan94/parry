# Plan 04 — Multi-Framework Native Integrations

**Priority:** 4 of 12.

**Goal:** Add first-class SDK wrappers for CrewAI, AutoGen, LlamaIndex, and Pydantic AI.
Each wrapper intercepts LLM calls transparently, exactly like the existing OpenAI and
Anthropic wrappers. Each integration ships with its own `pip install parry[crewai]` extra.

**New files:**
- `sdk/parry/wrappers/crewai.py`
- `sdk/parry/wrappers/autogen.py`
- `sdk/parry/wrappers/llamaindex.py`
- `sdk/parry/wrappers/pydantic_ai.py`
- `sdk/tests/test_crewai_wrapper.py`
- `sdk/tests/test_autogen_wrapper.py`
- `sdk/tests/test_llamaindex_wrapper.py`
- `sdk/tests/test_pydantic_ai_wrapper.py`

**Files to modify:**
- `sdk/pyproject.toml` — add optional dependency groups

---

### Task 1: pyproject.toml — add optional extras

```toml
[project.optional-dependencies]
openai = ["openai>=1.0.0"]
anthropic = ["anthropic>=0.20.0"]
langchain = ["langchain-core>=0.1.0"]
crewai = ["crewai>=0.28.0"]
autogen = ["pyautogen>=0.2.0"]
llamaindex = ["llama-index-core>=0.10.0"]
pydantic-ai = ["pydantic-ai>=0.0.8"]
all = ["parry[openai,anthropic,langchain,crewai,autogen,llamaindex,pydantic-ai]"]
```

---

### Task 2: CrewAI wrapper

**File:** `sdk/parry/wrappers/crewai.py`

CrewAI uses LLM callbacks. Implement a `ParryCrewAICallback` that:
1. Implements CrewAI's `BaseCallback` interface
2. In `on_llm_start`: records start time, extracts prompt
3. In `on_llm_end`: computes latency, extracts response, calls `intercept_completion()`

Usage:
```python
from parry.wrappers.crewai import ParryCrewAICallback
crew = Crew(agents=[...], tasks=[...], callbacks=[ParryCrewAICallback(agent_id="my-crew")])
```

---

### Task 3: AutoGen wrapper

**File:** `sdk/parry/wrappers/autogen.py`

AutoGen supports a `ConversableAgent` subclass. Implement `ParryConversableAgent` that:
1. Overrides `generate_reply()` to wrap the call with timing
2. Calls `intercept_completion()` after every reply generation

Usage:
```python
from parry.wrappers.autogen import ParryConversableAgent
agent = ParryConversableAgent(name="assistant", agent_id="my-autogen-agent", llm_config={...})
```

---

### Task 4: LlamaIndex wrapper

**File:** `sdk/parry/wrappers/llamaindex.py`

LlamaIndex has a first-class callback system. Implement `ParryCallbackHandler(BaseCallbackHandler)`:
1. Listen for `CBEventType.LLM` events
2. On `on_event_end`: extract prompt/response from `CBEventType.LLM` payload, call `intercept_completion()`

Usage:
```python
from parry.wrappers.llamaindex import ParryCallbackHandler
from llama_index.core import Settings
Settings.callback_manager.add_handler(ParryCallbackHandler(agent_id="my-llamaindex-agent"))
```

---

### Task 5: Pydantic AI wrapper

**File:** `sdk/parry/wrappers/pydantic_ai.py`

Pydantic AI supports instrument hooks. Implement `parry_instrument()` that patches the
model's `request()` method to wrap calls with timing and `intercept_completion()`.

Usage:
```python
from parry.wrappers.pydantic_ai import parry_instrument
from pydantic_ai import Agent
agent = Agent("openai:gpt-4o")
parry_instrument(agent, agent_id="my-pydantic-agent")
```

---

### Task 6: Tests for each wrapper

Each test file follows the same pattern as `test_openai_wrapper.py`:
1. Mock the underlying LLM call to return a fixture response
2. Assert `parry.get_client().send_event()` was called with correct fields
3. Assert the wrapper is transparent — returns the same response as without Parry
4. Assert fail-open: if Parry backend is unreachable, original response still returned

---

### Task 7: SDK README update

Add a section for each new integration with:
- Installation command
- 3-line usage example
- Link to full docs

---

### Notes

- **Test against real framework versions.** Pin minimum versions in pyproject.toml. Each
  framework's callback API changes between minor versions — pin and test the oldest supported.
- **All wrappers must fail open.** If `intercept_completion()` raises for any reason, the
  original LLM response is returned unchanged.
- **Blocking mode works the same way in all wrappers** — call `check_before_call()` before
  the LLM request, `scan_response_before_return()` after.

---
---

# Plan 05 — Custom Detection Rules via Dashboard UI

**Priority:** 5 of 12.

**Goal:** Let org admins create, edit, and test custom detection rules directly in the
dashboard. Rules are regex patterns with a name, severity, and target (prompt / response / both).
They are stored in the org's `detector_config` JSONB and run as part of the detection pipeline
without any SDK redeploy.

**New files:**
- `backend/app/detection/detectors/custom_rules.py`
- `backend/app/api/v1/custom_rules.py`
- `backend/tests/test_custom_rules_detector.py`
- `backend/tests/e2e/test_custom_rules_flow.py`
- `dashboard/src/pages/CustomRulesPage.tsx`
- `dashboard/src/hooks/useCustomRules.ts`

**Files to modify:**
- `backend/app/detection/registry.py` — add `CustomRulesDetector`
- `backend/app/api/v1/router.py` — register custom-rules router
- `dashboard/src/routes/router.tsx` — add `/custom-rules` route
- `dashboard/src/components/Sidebar.tsx` — add nav link

---

### Task 1: Data model — custom rules in detector_config

Custom rules are stored in `org.detector_config` as:
```json
{
  "custom_rules": [
    {
      "id": "uuid",
      "name": "Block competitor mentions",
      "pattern": "(?i)\\b(CompetitorA|CompetitorB)\\b",
      "target": "prompt",
      "severity": "medium",
      "enabled": true,
      "created_at": "ISO-8601"
    }
  ]
}
```

No new DB table needed — stored in existing `detector_config` JSONB on `Org`.

---

### Task 2: CustomRulesDetector

**File:** `backend/app/detection/detectors/custom_rules.py`

```python
import re
from typing import Any
from app.db.models import Severity
from app.detection.base import DetectionResult

class CustomRulesDetector:
    name = "custom_rules"

    def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        rules = (event_data.get("detector_config") or {}).get("custom_rules") or []
        enabled_rules = [r for r in rules if r.get("enabled", True)]

        if not enabled_rules:
            return DetectionResult(
                triggered=False, severity=Severity.LOW, confidence=0.0,
                reason="No custom rules configured", detector=self.name
            )

        prompt = event_data.get("prompt") or ""
        response = event_data.get("response") or ""
        max_severity = Severity.LOW
        matched_rules = []

        for rule in enabled_rules:
            target = rule.get("target", "both")
            text = ""
            if target in ("prompt", "both"):
                text += prompt
            if target in ("response", "both"):
                text += response

            try:
                pattern = re.compile(rule["pattern"], re.I)
            except re.error:
                continue  # Skip invalid regex — never crash

            if pattern.search(text):
                severity = Severity(rule.get("severity", "medium"))
                matched_rules.append({"rule": rule["name"], "severity": severity.value})
                if _rank(severity) > _rank(max_severity):
                    max_severity = severity

        if not matched_rules:
            return DetectionResult(
                triggered=False, severity=Severity.LOW, confidence=1.0,
                reason="No custom rules matched", detector=self.name
            )

        return DetectionResult(
            triggered=True, severity=max_severity, confidence=0.95,
            reason=f"Custom rule matched: {matched_rules[0]['rule']}",
            detector=self.name, details={"matched_rules": matched_rules}
        )

def _rank(s: Severity) -> int:
    return {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}[s]
```

Register in `backend/app/detection/registry.py`:
```python
from app.detection.detectors.custom_rules import CustomRulesDetector
DETECTORS = [..., CustomRulesDetector()]
```

---

### Task 3: API routes

**File:** `backend/app/api/v1/custom_rules.py`

Endpoints (all require `admin+` role):
- `GET /api/v1/custom-rules` — list org's custom rules
- `POST /api/v1/custom-rules` — create a rule (validate regex before saving)
- `PATCH /api/v1/custom-rules/{rule_id}` — update (name, pattern, severity, enabled)
- `DELETE /api/v1/custom-rules/{rule_id}` — remove rule
- `POST /api/v1/custom-rules/{rule_id}/test` — test a rule against sample text, returns match result

The `/test` endpoint is key for the UI — it lets admins verify their regex works before saving.

Request schema for create/update:
```python
class CustomRuleCreate(ParrySchema):
    name: str
    pattern: str  # validated as valid regex
    target: Literal["prompt", "response", "both"] = "both"
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    enabled: bool = True
```

Validate regex on write:
```python
try:
    re.compile(rule.pattern)
except re.error as e:
    raise HTTPException(400, detail=f"Invalid regex: {e}")
```

---

### Task 4: Dashboard — Custom Rules page

**File:** `dashboard/src/pages/CustomRulesPage.tsx`

UI elements:
- Table of existing rules: name, pattern, target, severity, enabled toggle, edit/delete buttons
- "New Rule" modal with fields: name, pattern (with real-time regex validation), target select,
  severity select, enabled toggle
- "Test Rule" panel in the modal: paste sample text → see match/no-match result inline
- Empty state with helpful onboarding copy explaining what custom rules are for

---

### Notes

- **Regex validation is mandatory on save.** An invalid regex that crashes the detector
  at runtime would silently break detection for all events. Validate server-side on every write.
- **Invalid regex in stored rules is skipped at runtime** (the `try/except re.error`
  in the detector). This is a safety net, not a substitute for validation on write.
- **Max 50 custom rules per org** on free tier to prevent performance degradation.
  Check and enforce this limit in the POST handler.
- **Audit log every rule create/update/delete.** Custom rules are security policy — every
  change must be traceable.

---
---

# Plan 06 — Compliance Report Export

**Priority:** 6 of 12.

**Goal:** Generate a downloadable PDF compliance report for a specified date range. The
report summarises agent activity, detection counts by severity and type, incident timeline,
policy configuration, and is formatted to be useful for SOC 2 and EU AI Act audits.

**New files:**
- `backend/app/services/report_service.py` — report data assembly
- `backend/app/api/v1/reports.py` — route handler
- `backend/tests/test_report_service.py`

**Files to modify:**
- `backend/app/api/v1/router.py` — register reports router
- `dashboard/src/pages/SettingsPage.tsx` or new `ReportsPage.tsx` — export UI

**Dependencies to add:**
- `weasyprint` or `reportlab` for PDF generation (weasyprint recommended — HTML→PDF)

---

### Task 1: Report data assembly

**File:** `backend/app/services/report_service.py`

`build_report_data(db, org_id, start_date, end_date)` returns a dict:
```python
{
    "org": {"name": ..., "id": ...},
    "period": {"start": ..., "end": ...},
    "generated_at": "ISO-8601",
    "summary": {
        "total_events": int,
        "total_detections": int,
        "triggered_detections": int,
        "total_incidents": int,
        "agents_monitored": int,
    },
    "detections_by_severity": {"critical": int, "high": int, "medium": int, "low": int},
    "detections_by_detector": {"prompt_injection": int, "jailbreak": int, ...},
    "incidents": [
        {"id": ..., "title": ..., "severity": ..., "status": ..., "created_at": ..., "resolved_at": ...}
    ],
    "policies": [
        {"name": ..., "allowed_tools": [...], "blocked_domains": [...], "forbidden_patterns": [...]}
    ],
    "agents": [
        {"name": ..., "event_count": int, "incident_count": int, "last_seen": ...}
    ]
}
```

Queries:
- All use `between(start_date, end_date)` filters
- AgentEvent queries always include `agent_id` filter (TimescaleDB requirement)
- Group detections by `detector` and `severity` using SQLAlchemy `func.count()` + `group_by()`

---

### Task 2: PDF generation

Use `weasyprint` to convert an HTML template to PDF.

Create `backend/app/services/report_template.py` with an HTML string template (inline CSS,
no external resources — WeasyPrint must be able to render it offline):

Sections:
1. Cover page — org name, report period, generated date, Parry logo (inline SVG)
2. Executive summary — metric cards: total events, incidents, agents, detection rate
3. Detection breakdown — table by detector × severity
4. Incident timeline — table of all incidents with status
5. Policy configuration — what was enforced during the period
6. Agent inventory — list of monitored agents with event counts
7. Footer — "Generated by Parry. This report is intended for compliance review purposes."

---

### Task 3: API route

**File:** `backend/app/api/v1/reports.py`

`GET /api/v1/reports/compliance?start=YYYY-MM-DD&end=YYYY-MM-DD`
Auth: admin+
Response: `Content-Type: application/pdf`, `Content-Disposition: attachment; filename=parry-compliance-{start}-{end}.pdf`

The handler:
1. Validates date range (max 366 days)
2. Calls `build_report_data()`
3. Renders HTML template with report data
4. Converts HTML to PDF via WeasyPrint
5. Streams PDF bytes as response

For large date ranges, return 202 and a job ID, then poll for completion. For MVP,
synchronous generation is acceptable (cap at 90-day reports for sync).

---

### Task 4: Dashboard — export UI

Add to `SettingsPage.tsx` or a new `ReportsPage.tsx`:
- Date range picker (start / end)
- "Generate Report" button
- Shows spinner during generation
- Auto-downloads PDF when ready
- Recent reports list (store last 5 generated reports metadata in localStorage)

---

### Notes

- **WeasyPrint requires system fonts and Cairo.** The Docker image needs:
  `apt-get install -y fonts-liberation libpango-1.0-0 libcairo2`
  Add these to `backend/Dockerfile`.
- **Cap sync generation at 90 days.** Longer periods should use async generation
  (Celery task + polling) to avoid request timeout.
- **Redact raw prompts from the report.** The compliance report shows counts and metadata,
  never raw prompt content. This is critical for data minimization under GDPR.

---
---

# Plan 07 — Agent Health Score

**Priority:** 7 of 12.

**Goal:** Compute a single 0–100 health score per agent that synthesises baseline drift,
detection frequency, and incident rate. Expose it on the agent model and surface it
prominently in the dashboard.

**Score formula:**
```
health = 100
  - (triggered_detections_last_7d * 5)      # up to -50 for detections
  - (open_incidents_count * 10)              # up to -30 for incidents
  - (critical_incidents_last_30d * 15)       # up to -30 for critical incidents
  - (anomaly_score * 20)                     # 0–1 drift score → 0–20 penalty
  clamped to [0, 100]
```

**New files:**
- `backend/app/services/health_score_service.py`
- `backend/tests/test_health_score_service.py`

**Files to modify:**
- `backend/app/api/v1/agents.py` — include health_score in agent response
- `backend/app/schemas/agent.py` — add health_score field
- `backend/app/workers/celery_app.py` — add periodic health score refresh task
- `dashboard/src/pages/AgentsPage.tsx` — show health score badge per agent
- `dashboard/src/pages/DashboardPage.tsx` — show org-wide health summary
- `dashboard/src/pages/AgentDetailPage.tsx` — show score with breakdown

---

### Task 1: Health score service

**File:** `backend/app/services/health_score_service.py`

```python
async def compute_health_score(db: AsyncSession, agent_id: UUID) -> dict:
    """Returns health score and component breakdown."""
    now = datetime.now(UTC)
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)

    # Triggered detections in last 7 days
    triggered_7d = await _count_triggered_detections(db, agent_id, since=seven_days_ago)

    # Open incidents
    open_incidents = await _count_incidents(db, agent_id, status=IncidentStatus.OPEN)

    # Critical incidents in last 30 days
    critical_30d = await _count_incidents(
        db, agent_id, since=thirty_days_ago, severity=Severity.CRITICAL
    )

    # Latest anomaly score from most recent detection
    anomaly_score = await _latest_anomaly_score(db, agent_id)

    penalty = (
        min(triggered_7d * 5, 50)
        + min(open_incidents * 10, 30)
        + min(critical_30d * 15, 30)
        + int(anomaly_score * 20)
    )

    score = max(0, 100 - penalty)
    grade = _grade(score)

    return {
        "score": score,
        "grade": grade,  # "A" | "B" | "C" | "D" | "F"
        "components": {
            "triggered_detections_7d": triggered_7d,
            "open_incidents": open_incidents,
            "critical_incidents_30d": critical_30d,
            "anomaly_score": round(anomaly_score, 3),
        },
        "computed_at": now.isoformat(),
    }

def _grade(score: int) -> str:
    if score >= 90: return "A"
    if score >= 75: return "B"
    if score >= 60: return "C"
    if score >= 40: return "D"
    return "F"
```

---

### Task 2: Include health score in agent API response

**File:** `backend/app/schemas/agent.py`

Add to `AgentResponse`:
```python
health_score: int | None = None
health_grade: str | None = None  # "A" | "B" | "C" | "D" | "F"
```

**File:** `backend/app/api/v1/agents.py`

In `get_agent()` handler, call `compute_health_score()` and include in response.
For `list_agents()`, compute scores for all agents (batch).

---

### Task 3: Periodic health score cache

Rather than computing on every GET request, compute every hour via Celery Beat and cache
in Redis (`health:{agent_id}`, 2h TTL). The GET handler reads from cache first, falls back
to live computation on cache miss.

Add to `backend/app/workers/celery_app.py`:
```python
"refresh-health-scores": {
    "task": "refresh_health_scores",
    "schedule": crontab(minute=0),  # hourly
}
```

Create `backend/app/workers/health_score_task.py`.

---

### Task 4: Dashboard — health score display

**`AgentsPage.tsx`:** Add a coloured score badge next to each agent name.
- 90–100: green
- 75–89: blue
- 60–74: yellow
- 40–59: orange
- 0–39: red

**`DashboardPage.tsx`:** Add an org-wide "Fleet Health" metric card showing the average
score across all agents, with a mini bar chart breakdown by grade.

**`AgentDetailPage.tsx`:** Show the full score breakdown — the component scores displayed
as a scorecard so the user can see exactly what's hurting their agent's score.

---

### Notes

- **Score is always 0–100, lower is worse.** This is intuitive and matches what engineers
  expect from a health metric.
- **Grade labels ("A" through "F")** are more useful in exec reporting than raw numbers.
  Include both.
- **New agents with no events score 100** (no evidence of problems). This is intentional —
  don't penalise agents for being new.
- **Score is informational, not a gating mechanism.** Never block API calls based on score.

---
---

# Plan 08 — Agent Behavioral Graph

**Priority:** 8 of 12.

**Goal:** Visualise each agent's behaviour over time as a set of interactive charts on
the AgentDetailPage. Show tool call sequences, model usage, anomaly score trend, and
event volume — all in a single scrollable view that tells the story of what the agent
has been doing.

**New files:**
- `backend/app/api/v1/agent_stats.py` — stats API endpoint
- `backend/app/services/agent_stats_service.py` — query logic
- `dashboard/src/components/charts/ToolCallHeatmap.tsx`
- `dashboard/src/components/charts/AnomalyTrend.tsx`
- `dashboard/src/components/charts/ModelUsageDonut.tsx`
- `dashboard/src/components/charts/EventVolume.tsx`
- `dashboard/src/hooks/useAgentStats.ts`

**Files to modify:**
- `backend/app/api/v1/router.py` — register agent stats route
- `dashboard/src/pages/AgentDetailPage.tsx` — add charts section

---

### Task 1: Agent stats API

**Route:** `GET /api/v1/agents/{agent_id}/stats?window=7d|30d|90d`

Response:
```json
{
  "event_volume": [
    {"date": "2026-04-01", "count": 142},
    ...
  ],
  "tool_calls": [
    {"tool": "web_search", "count": 87},
    {"tool": "read_file", "count": 23}
  ],
  "model_usage": [
    {"model": "gpt-4o", "count": 120},
    {"model": "gpt-4o-mini", "count": 22}
  ],
  "anomaly_trend": [
    {"date": "2026-04-01", "avg_score": 0.12},
    ...
  ],
  "detection_counts": {
    "prompt_injection": 3,
    "jailbreak": 0,
    "tool_misuse": 1,
    "data_exfiltration": 0,
    "privilege_escalation": 0,
    "anomaly": 2
  }
}
```

**Implementation notes:**
- `event_volume`: `SELECT date_trunc('day', timestamp), count(*) FROM agent_events WHERE agent_id=X AND timestamp > now()-interval GROUP BY 1 ORDER BY 1`
- `tool_calls`: unnest `tool_calls` JSONB array, extract `name` field, group and count
- `model_usage`: `SELECT model, count(*) FROM agent_events WHERE agent_id=X GROUP BY model`
- `anomaly_trend`: join `agent_events` with `detections` where `detector='anomaly'`, group by day, avg confidence
- All queries must include `agent_id` and time range filter (TimescaleDB requirement)

---

### Task 2: Charts

**`EventVolume.tsx`** — Recharts `AreaChart`. X-axis: dates. Y-axis: event count.
Fill color matches the agent's health grade colour.

**`ToolCallHeatmap.tsx`** — Recharts `BarChart` (horizontal). Y-axis: tool names.
X-axis: call count. Shows top 10 tools by frequency.

**`ModelUsageDonut.tsx`** — Recharts `PieChart`. Each slice = a model. Shows distribution.
Useful when agents switch models unexpectedly.

**`AnomalyTrend.tsx`** — Recharts `LineChart`. X-axis: dates. Y-axis: avg anomaly confidence
(0.0–1.0). Draws a horizontal dashed line at 0.5 (the "ambiguous" threshold) and 0.7
(the "triggered" threshold). Spikes above 0.7 appear in red.

---

### Task 3: Window selector

Add a `7d / 30d / 90d` toggle above the charts on `AgentDetailPage.tsx`.
State lives in the component (not URL) — it's a view preference, not a bookmarkable state.
Changing the window re-fetches via `useAgentStats(agentId, window)`.

---

### Notes

- **Cache stats responses in Redis** (`stats:{agent_id}:{window}`, 5 minute TTL).
  Stats are read-heavy and expensive to compute. The 5 minute staleness is acceptable.
- **TimescaleDB time_bucket()** is more efficient than `date_trunc()` for the volume and
  anomaly trend queries. Use it if the TimescaleDB extension is available.
- **Empty state matters.** New agents with no events should show a helpful empty state:
  "No events yet. Install the SDK to start monitoring this agent."
