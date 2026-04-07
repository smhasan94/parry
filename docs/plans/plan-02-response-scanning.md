# Plan 02 — Response Scanning Before Delivery

**Priority:** 2 of 12. Requires Plan 01 (blocking mode) to be complete first.

**Goal:** Intercept the LLM's response before it is returned to the agent. Run the
`DataExfiltrationDetector` against the response. If sensitive data is found, either
strip it (redact mode) or block the response entirely (block mode) depending on org config.

**Architecture:**
```
SDK calls OpenAI → OpenAI returns response
  └─► SDK calls POST /api/v1/proxy/scan-response  (NEW)
        └─► Backend runs DataExfiltrationDetector against response text
              ├─► clean → returns response unchanged
              ├─► redact mode → returns response with sensitive patterns replaced
              └─► block mode → returns 200 with blocked=true → SDK raises ParryBlockedError
```

The existing async ingest pipeline still runs after this — the original (pre-scan) prompt
and the (post-scan) response are both logged for forensics.

**New files:**
- `backend/app/proxy/response_scan.py` — response scanning logic
- `backend/app/api/v1/proxy.py` — add `POST /proxy/scan-response` route (to existing file)
- `sdk/parry/response_scanner.py` — SDK-side call + response handling
- `backend/tests/test_response_scan.py`
- `backend/tests/e2e/test_response_scan_flow.py`

**Files to modify:**
- `backend/app/db/models.py` — add `response_scan_mode` enum to `Org` (`off/redact/block`)
- `sdk/parry/wrappers/openai.py` — call response scanner before returning
- `sdk/parry/wrappers/anthropic.py` — same

---

### Task 1: DB migration — response_scan_mode on Org

**Files:**
- Create: `backend/alembic/versions/008_add_response_scan_mode.py`
- Modify: `backend/app/db/models.py`

Add to models:
```python
class ResponseScanMode(enum.StrEnum):
    OFF = "off"
    REDACT = "redact"
    BLOCK = "block"
```

Add to `Org`:
```python
response_scan_mode: Mapped[ResponseScanMode] = mapped_column(
    Enum(ResponseScanMode), default=ResponseScanMode.OFF, nullable=False
)
```

Generate and apply migration:
```bash
cd backend && uv run alembic revision --autogenerate -m "add_response_scan_mode"
uv run alembic upgrade head
```

---

### Task 2: Backend — response scan logic

**File:** `backend/app/proxy/response_scan.py`

```python
from app.detection.detectors.data_exfil import DataExfiltrationDetector, SENSITIVE_PATTERNS
from app.db.models import ResponseScanMode

_detector = DataExfiltrationDetector()

class ResponseScanResult:
    __slots__ = ("blocked", "redacted_response", "findings", "original_response")
    def __init__(self, blocked, redacted_response, findings, original_response):
        self.blocked = blocked
        self.redacted_response = redacted_response
        self.findings = findings
        self.original_response = original_response

def scan_response(
    response: str,
    mode: ResponseScanMode,
) -> ResponseScanResult:
    if mode == ResponseScanMode.OFF:
        return ResponseScanResult(
            blocked=False, redacted_response=response, findings=[], original_response=response
        )

    event_data = {"response": response}
    result = _detector.detect(event_data)

    if not result.triggered:
        return ResponseScanResult(
            blocked=False, redacted_response=response, findings=[], original_response=response
        )

    if mode == ResponseScanMode.BLOCK:
        return ResponseScanResult(
            blocked=True, redacted_response=None,
            findings=result.details.get("findings", []), original_response=response
        )

    # REDACT mode — replace each matching pattern with its placeholder
    redacted = response
    findings = []
    for pattern, description, severity in SENSITIVE_PATTERNS:
        if pattern.search(redacted):
            placeholder = f"[REDACTED:{description.upper().replace(' ', '_')}]"
            redacted = pattern.sub(placeholder, redacted)
            findings.append({"pattern": description, "severity": severity.value})

    return ResponseScanResult(
        blocked=False, redacted_response=redacted, findings=findings, original_response=response
    )
```

**Step 2: Add route to `backend/app/api/v1/proxy.py`**

`POST /api/v1/proxy/scan-response`
Request body: `{ "response": "...", "agent_id": "..." }`
Response: `{ "blocked": bool, "response": "...", "findings": [...] }`

The handler loads the org (via SDK key auth), gets `response_scan_mode`, calls `scan_response()`,
returns result. Always 200.

---

### Task 3: SDK — call response scanner after LLM returns

**File:** `sdk/parry/response_scanner.py`

```python
def scan_response_before_return(
    client,
    response_text: str,
    agent_id: str | None = None,
) -> str:
    """
    Call /proxy/scan-response. Returns (possibly redacted) response text.
    Raises ParryBlockedError if mode=block and sensitive data found.
    Fails open on any error.
    """
    try:
        resp = client._http.post(
            "/api/v1/proxy/scan-response",
            json={"response": response_text, "agent_id": agent_id or client.default_agent_id},
            timeout=2.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("blocked"):
                from parry.blocking import ParryBlockedError
                raise ParryBlockedError(
                    reason="Sensitive data detected in response",
                    detector="data_exfiltration",
                    severity="high",
                    confidence=0.85,
                )
            return data.get("response", response_text)
    except ParryBlockedError:
        raise
    except Exception:
        import logging
        logging.getLogger("parry").warning("parry: response scan failed, failing open")
    return response_text
```

Modify `ParryOpenAI` and `ParryAnthropic` wrappers: after receiving the LLM response,
before returning it to the caller, call `scan_response_before_return()`.

---

### Task 4: Unit tests

**File:** `backend/tests/test_response_scan.py`

Test cases:
1. `mode=off` → always returns response unchanged, blocked=False
2. `mode=redact` + clean response → unchanged, findings=[]
3. `mode=redact` + SSN in response → SSN replaced with `[REDACTED:SSN_DETECTED]`
4. `mode=redact` + credit card → replaced
5. `mode=redact` + API key → replaced
6. `mode=block` + sensitive data → blocked=True, redacted_response=None
7. `mode=block` + clean response → blocked=False

```bash
cd backend && uv run pytest tests/test_response_scan.py -v
```

---

### Task 5: E2E test

**File:** `backend/tests/e2e/test_response_scan_flow.py`

Test flow:
1. Org with `response_scan_mode=off` → `/proxy/scan-response` returns response unchanged
2. Org with `response_scan_mode=redact` + SSN → SSN redacted in returned response
3. Org with `response_scan_mode=block` + API key → `blocked=true`
4. Org with `response_scan_mode=block` + clean response → `blocked=false`

---

### Task 6: Dashboard — response scan mode setting

**File:** `dashboard/src/pages/SettingsPage.tsx`

Add a "Response Scanning" section with a three-way toggle:
- Off (default)
- Redact — sensitive patterns replaced with `[REDACTED]` placeholders
- Block — response containing sensitive data is rejected entirely

---

### Notes

- **Fail open is mandatory.** If `/proxy/scan-response` errors, return the original response.
- **2 second timeout** on the SDK side, same as the blocking proxy check.
- **Streaming responses** are the hard case. For streaming, buffer the full response before
  scanning, then either stream the (redacted) result or raise the error. This is a known
  trade-off — scanning requires buffering. Document this clearly in the SDK README.
- **The original unredacted response is still sent to the async ingest pipeline** for forensics.
  The redacted version is what gets returned to the agent. This is intentional — you want the
  full evidence of what the LLM produced.
- **Findings from the response scan are included in the async Detection record** so they show
  up in the dashboard incident view.
