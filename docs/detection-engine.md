# Detection Engine — Design Reference

## BaseDetector protocol

```python
from typing import Protocol
from app.schemas.detection import DetectionResult, EventContext

class BaseDetector(Protocol):
    name: str
    version: str

    async def detect(self, event: EventContext) -> DetectionResult:
        ...
```

## EventContext (what detectors receive)

```python
@dataclass
class EventContext:
    event_id: str
    agent_id: str
    org_id: str
    prompt: str           # PII-stripped, truncated
    response: str         # PII-stripped, truncated
    tool_calls: list[ToolCall]
    model: str
    session_id: str | None
    policy: OrgPolicy     # org's current policy
    agent_baseline: AgentBaseline | None
    metadata: dict
```

## DetectionResult

```python
@dataclass
class DetectionResult:
    triggered: bool
    severity: Severity    # LOW | MEDIUM | HIGH | CRITICAL
    score: float          # 0.0–1.0 confidence
    reason: str           # human-readable, shown in dashboard
    detector: str         # detector class name
    evidence: dict        # supporting data (matched patterns, etc.)
```

## Pipeline (execution order)

```
EventContext
    │
    ▼
PreProcessor.process(event)
    │  - Normalise whitespace
    │  - Extract tool_calls from response JSON
    │  - Truncate to 4000 chars
    ▼
[RuleBasedDetectors] (run in parallel via asyncio.gather)
    │  PromptInjectionDetector
    │  JailbreakDetector
    │  ToolMisuseDetector
    │  DataExfiltrationDetector
    │  PrivilegeEscalationDetector
    │  AnomalyDetector
    ▼
Aggregator
    │  max_score = max(result.score for result in results)
    │  if max_score < 0.4:  → no detection, log only
    │  if 0.4 <= max_score < 0.7:  → trigger LLM fallback
    │  if max_score >= 0.7:  → detection confirmed, write to DB
    ▼
[LLMFallbackDetector] (only when 0.4–0.7)
    │  Sends structured prompt to claude-sonnet-4-6
    │  Returns final triggered/not-triggered verdict
    ▼
PolicyEnforcer
    │  Checks tool_calls against policy.allowed_tools
    │  Checks any URLs against policy.blocked_domains
    │  Checks prompt against policy.forbidden_patterns
    │  Policy violations always write to DB regardless of above
    ▼
Write DetectionResult(s) to DB
    │
    ▼
IncidentCorrelator (async Celery task)
    │  Groups related detections into incidents
    │  Pushes SSE event to dashboard if HIGH/CRITICAL
```

## LLM fallback prompt template

The fallback sends a structured prompt to Claude. Template lives at
`detection/templates/llm_fallback.jinja2`.

Key fields injected: prompt_preview, response_preview, tool_calls,
matched_patterns, rule_scores. Response format: JSON with `triggered`,
`severity`, `reason`.

## Anomaly detection baseline

Each agent builds a baseline over its first 100 events:
- Mean/stddev of token counts per call
- Distribution of tool calls used
- Typical response latency
- Common prompt topic clusters (via TF-IDF)

Anomaly score = weighted z-score across these dimensions.
Baseline refreshes every 1000 events (Celery periodic task).
New agents (< 100 events) skip anomaly detection — score = 0.0.

## Adding a new detector

```python
# detection/detectors/my_detector.py
from app.detection.base import BaseDetector, EventContext, DetectionResult, Severity

class MyDetector:
    name = "MyDetector"
    version = "1.0.0"

    async def detect(self, event: EventContext) -> DetectionResult:
        triggered = False
        score = 0.0
        reason = "No issues detected"

        # your logic here

        return DetectionResult(
            triggered=triggered,
            severity=Severity.MEDIUM if triggered else Severity.LOW,
            score=score,
            reason=reason,
            detector=self.name,
            evidence={},
        )
```

Then register in `detection/registry.py`:
```python
from app.detection.detectors.my_detector import MyDetector
DETECTORS = [
    ...,
    MyDetector(),
]
```
