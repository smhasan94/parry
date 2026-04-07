# Plan 01 — Active Blocking Mode (Proxy)

**Priority:** 1 of 12 — implement this before anything else.

**Goal:** Transform Parry from observe-only into a real-time blocking firewall. The SDK calls
Parry synchronously before calling the LLM. Parry runs fast rule-based checks (<10ms) and
returns `allow` or `block`. If blocked, the LLM call never fires and the SDK raises a
`ParryBlockedError` to the agent.

**Architecture overview:**
```
Agent code
  └─► ParryOpenAI.chat.completions.create(...)
        └─► SDK calls POST /api/v1/proxy/check  (NEW — synchronous, <10ms)
              └─► Backend runs rule-based detectors only (no LLM fallback, no DB write)
                    ├─► allow → SDK proceeds to call OpenAI → response returned
                    │     └─► SDK fires async event ingest as before (unchanged)
                    └─► block → SDK raises ParryBlockedError → agent handles it
```

The existing async event ingest pipeline is **unchanged**. The proxy check is additive and
synchronous. LLM fallback and DB writes still happen async after the fact.

**Key constraint:** The proxy check must complete in under 10ms at p99. Only rule-based
detectors run synchronously. AnomalyDetector and LLMFallback are async-only and never run
in the blocking path.

**New files to create:**
- `backend/app/proxy/check.py` — synchronous check endpoint logic
- `backend/app/api/v1/proxy.py` — FastAPI route handler
- `sdk/parry/blocking.py` — `ParryBlockedError` exception + blocking client logic
- `backend/tests/test_proxy_check.py` — unit tests
- `backend/tests/e2e/test_blocking_flow.py` — E2E tests

**Files to modify:**
- `backend/app/api/v1/router.py` — register proxy router
- `backend/app/db/models.py` — add `blocking_enabled` bool to `Org`
- `sdk/parry/wrappers/openai.py` — add blocking check before OpenAI call
- `sdk/parry/wrappers/anthropic.py` — same
- `sdk/parry/wrappers/langchain.py` — same
- `backend/alembic/versions/` — new migration for `blocking_enabled`

---

### Task 1: DB migration — add blocking_enabled to Org

**Files:**
- Create: `backend/alembic/versions/007_add_blocking_enabled.py`
- Modify: `backend/app/db/models.py`

**Step 1: Add column to Org model**

In `backend/app/db/models.py`, add to `Org`:
```python
blocking_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

**Step 2: Generate migration**
```bash
cd backend && uv run alembic revision --autogenerate -m "add_blocking_enabled_to_orgs"
```

**Step 3: Apply migration**
```bash
uv run alembic upgrade head
```

**Step 4: Commit**

---

### Task 2: Backend — proxy check endpoint

**Files:**
- Create: `backend/app/proxy/check.py`
- Create: `backend/app/api/v1/proxy.py`

**Step 1: Create `backend/app/proxy/check.py`**

```python
"""Synchronous pre-call check for the blocking proxy mode."""
from typing import Any
from app.detection.detectors.prompt_injection import PromptInjectionDetector
from app.detection.detectors.jailbreak import JailbreakDetector
from app.detection.detectors.tool_misuse import ToolMisuseDetector
from app.detection.detectors.privilege_esc import PrivilegeEscalationDetector
from app.db.models import Severity

# Only fast rule-based detectors run in the blocking path
BLOCKING_DETECTORS = [
    PromptInjectionDetector(),
    JailbreakDetector(),
    ToolMisuseDetector(),
    PrivilegeEscalationDetector(),
]

class ProxyCheckResult:
    __slots__ = ("allowed", "reason", "detector", "severity", "confidence")
    def __init__(self, allowed, reason="", detector="", severity=None, confidence=0.0):
        self.allowed = allowed
        self.reason = reason
        self.detector = detector
        self.severity = severity
        self.confidence = confidence

def run_blocking_check(event_data: dict[str, Any], org_blocking_enabled: bool) -> ProxyCheckResult:
    """Run synchronous blocking check. Returns immediately on first HIGH/CRITICAL trigger."""
    if not org_blocking_enabled:
        return ProxyCheckResult(allowed=True, reason="blocking_disabled")

    for detector in BLOCKING_DETECTORS:
        result = detector.detect(event_data)
        if result.triggered and result.severity in (Severity.HIGH, Severity.CRITICAL):
            return ProxyCheckResult(
                allowed=False,
                reason=result.reason,
                detector=result.detector,
                severity=result.severity,
                confidence=result.confidence,
            )

    return ProxyCheckResult(allowed=True)
```

**Step 2: Create `backend/app/api/v1/proxy.py`**

Route: `POST /api/v1/proxy/check`
Auth: `X-Parry-Secret` (same as event ingest)
Response schema:
```json
{
  "allowed": true/false,
  "reason": "string",
  "detector": "string",
  "severity": "high|critical|null",
  "confidence": 0.0-1.0
}
```

The handler:
1. Authenticates via `get_org_from_sdk_key`
2. Builds `event_data` from request body (prompt, tool_calls, policy from org)
3. Loads org policies from DB (cached in Redis with 30s TTL to avoid per-request DB hit)
4. Calls `run_blocking_check(event_data, org.blocking_enabled)`
5. Returns result as JSON — always 200, never raises (blocking is in the response body)

**Step 3: Register in router**

In `backend/app/api/v1/router.py`:
```python
from app.api.v1 import proxy
api_router.include_router(proxy.router, prefix="/proxy", tags=["proxy"])
```

---

### Task 3: Unit tests — proxy check logic

**File:** `backend/tests/test_proxy_check.py`

Test cases:
1. `blocking_enabled=False` → always allowed regardless of prompt
2. Clean prompt → allowed
3. Prompt injection pattern → blocked, severity=HIGH or CRITICAL
4. Jailbreak pattern → blocked
5. Tool call not in allowlist → blocked
6. MEDIUM severity trigger → allowed (only HIGH/CRITICAL block)
7. Returns immediately on first trigger (doesn't run all detectors)

```bash
cd backend && uv run pytest tests/test_proxy_check.py -v
```

---

### Task 4: SDK — blocking client integration

**Files:**
- Create: `sdk/parry/blocking.py`
- Modify: `sdk/parry/wrappers/openai.py`
- Modify: `sdk/parry/wrappers/anthropic.py`

**Step 1: Create `sdk/parry/blocking.py`**

```python
class ParryBlockedError(Exception):
    """Raised when Parry's blocking proxy rejects an LLM call."""
    def __init__(self, reason: str, detector: str, severity: str, confidence: float):
        self.reason = reason
        self.detector = detector
        self.severity = severity
        self.confidence = confidence
        super().__init__(f"Parry blocked this call: [{detector}] {reason}")

def check_before_call(
    client,  # ParryClient instance
    prompt: str | None,
    tool_calls: list | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """Call /proxy/check synchronously. Raises ParryBlockedError if blocked."""
    payload = {
        "agent_id": agent_id or client.default_agent_id,
        "prompt": prompt,
        "tool_calls": tool_calls or [],
    }
    try:
        resp = client._http.post("/api/v1/proxy/check", json=payload, timeout=2.0)
        if resp.status_code == 200:
            data = resp.json()
            if not data.get("allowed", True):
                raise ParryBlockedError(
                    reason=data.get("reason", ""),
                    detector=data.get("detector", ""),
                    severity=data.get("severity", ""),
                    confidence=data.get("confidence", 0.0),
                )
    except ParryBlockedError:
        raise
    except Exception:
        # Fail open — if proxy check fails, let the call through
        import logging
        logging.getLogger("parry").warning("parry: proxy check failed, failing open", exc_info=True)
```

**Step 2: Modify `ParryOpenAI` wrapper**

Before the OpenAI call in `_CompletionsNamespace.create()`, add:
```python
from parry.blocking import check_before_call
check_before_call(parry.get_client(), prompt=prompt, model=model)
```

This runs only if `parry.get_client()` exists (SDK initialized). Always fails open if the
proxy check errors.

**Step 3: Same pattern for `ParryAnthropic`**

---

### Task 5: E2E test — blocking flow

**File:** `backend/tests/e2e/test_blocking_flow.py`

Test cases:
1. Org with `blocking_enabled=False` → `/proxy/check` returns `allowed=true` even for injection
2. Org with `blocking_enabled=True` + clean prompt → `allowed=true`
3. Org with `blocking_enabled=True` + injection prompt → `allowed=false`, correct detector/reason
4. No auth header → 401
5. Invalid API key → 401

```bash
cd backend && uv run pytest tests/e2e/test_blocking_flow.py -v
```

---

### Task 6: SDK tests — blocking

**File:** `sdk/tests/test_blocking.py`

Test cases:
1. Mock backend returns `allowed=true` → no exception raised
2. Mock backend returns `allowed=false` → `ParryBlockedError` raised with correct fields
3. Backend unreachable → no exception (fail open)
4. Backend returns 500 → no exception (fail open)
5. `ParryOpenAI.chat.completions.create()` raises `ParryBlockedError` when blocked

---

### Task 7: Wire blocking_enabled to SettingsPage

**File:** `dashboard/src/pages/SettingsPage.tsx`

Add a toggle in the "Security" section of settings:
- Label: "Blocking Mode"
- Description: "When enabled, Parry will reject LLM calls that trigger HIGH or CRITICAL detectors before they reach the model."
- Backend: `PATCH /api/v1/agents/{id}` or a new `PATCH /api/v1/settings/blocking` endpoint

---

### Notes

- **Fail open is non-negotiable.** If the proxy check errors for any reason (network, timeout, Redis down), the SDK must let the call through. Parry must never be the reason an agent breaks.
- **2 second timeout** on the proxy check in the SDK. If the backend hasn't responded in 2s, fail open.
- **Policy caching:** Load org policies from Redis cache (30s TTL) in the proxy handler to avoid a DB round-trip on every LLM call. Cache key: `policy:{org_id}`.
- **Don't run AnomalyDetector or LLMFallback in the blocking path.** Both are too slow. They stay async in the Celery pipeline only.
- **The existing async ingest pipeline is unchanged.** Blocking mode is additive, not a replacement.
