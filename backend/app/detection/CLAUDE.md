# Backend — Detection Engine

## Detection pipeline order
Every incoming event flows through this pipeline in sequence:
1. `PreProcessor` — strips PII, normalises whitespace, extracts tool calls from response
2. `RuleBasedDetectors` — run in parallel, each returns a score 0.0–1.0
3. `AggregatorNode` — combines scores, decides if LLM fallback needed (score 0.4–0.7)
4. `LLMFallbackDetector` — calls Claude API only when aggregator is ambiguous
5. `PolicyEnforcer` — checks event against org policy regardless of detection score
6. `IncidentCorrelator` — groups related detections into incidents (async, post-response)

## Detector inventory
| Detector | File | Trigger condition |
|---|---|---|
| `PromptInjectionDetector` | `detection/detectors/prompt_injection.py` | Injection patterns in prompt |
| `ToolMisuseDetector` | `detection/detectors/tool_misuse.py` | Tool calls not in org policy allowlist |
| `DataExfiltrationDetector` | `detection/detectors/data_exfil.py` | PII or secrets in response |
| `AnomalyDetector` | `detection/detectors/anomaly.py` | Drift from agent's baseline |
| `JailbreakDetector` | `detection/detectors/jailbreak.py` | Known jailbreak phrase patterns |
| `PrivilegeEscalationDetector` | `detection/detectors/privilege_esc.py` | Attempts to gain elevated access |

## Adding a new detector
1. Create `detection/detectors/your_detector.py`
2. Implement `BaseDetector` protocol from `detection/base.py`
3. Register in `detection/registry.py`
4. Add fixtures to `tests/fixtures/your_detector/`
5. Write tests in `tests/detection/test_your_detector.py` — cover trigger + non-trigger + edge cases

## Severity levels
`CRITICAL` → block call + page on-call
`HIGH` → block call + alert dashboard
`MEDIUM` → allow call + flag for review
`LOW` → allow call + log only
