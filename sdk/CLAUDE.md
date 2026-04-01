# SDK — parry Python package

## Design constraints
- **Fail open always** — if backend unreachable, log warning, pass call through unchanged
- **Zero latency impact on happy path** — events sent async/fire-and-forget; don't await backend
- **2-line integration** — wrapping should require minimal code change from the user
- **No data stored locally** — SDK is stateless; all persistence is backend's job

## Usage pattern (what we're building toward)
```python
import parry
parry.init(api_key="sk-sentinel-...")

# Drop-in OpenAI wrapper
from parry.wrappers.openai import SentinelOpenAI
client = SentinelOpenAI()  # wraps openai.OpenAI transparently
```

## Wrapper implementation pattern
Each wrapper (openai, anthropic, langchain) must:
1. Accept all the same args as the underlying client
2. Intercept every completion call via `interceptor.py`
3. Strip PII client-side before sending event to backend
4. Never mutate the response returned to the caller

## PII stripping rules (client-side, before sending to backend)
- Redact credit card patterns: `r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'`
- Redact SSN: `r'\b\d{3}-\d{2}-\d{4}\b'`
- Redact emails in prompt: replace with `[EMAIL]`
- Truncate prompt to 4000 chars before sending (full prompt stays local)

## Event payload sent to backend
```python
{
  "agent_id": str,          # required, set on init or per-call
  "session_id": str,        # optional, groups related calls
  "prompt": str,            # truncated, PII-stripped
  "response": str,          # truncated, PII-stripped
  "model": str,             # e.g. "gpt-4o", "claude-sonnet-4-6"
  "tool_calls": list,       # extracted tool calls from response
  "latency_ms": int,
  "token_count": int,
  "timestamp": str,         # ISO 8601
  "metadata": dict          # arbitrary caller-provided k/v
}
```

## Testing the SDK
```bash
cd sdk
uv run pytest                          # unit tests (no network)
SENTINEL_TEST_BACKEND=1 uv run pytest  # integration tests (needs backend running)
```
