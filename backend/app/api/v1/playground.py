"""Public playground endpoint — no auth required.

Runs a subset of detectors on user-provided text so prospects can
experience Parry's detection without signing up or integrating the SDK.
"""

from typing import Any

import structlog
from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.detection.base import DetectionResult
from app.detection.detectors.data_exfil import DataExfiltrationDetector
from app.detection.detectors.jailbreak import JailbreakDetector
from app.detection.detectors.privilege_esc import PrivilegeEscalationDetector
from app.detection.detectors.prompt_injection import PromptInjectionDetector
from app.detection.detectors.tool_misuse import ToolMisuseDetector

log = structlog.get_logger()

router = APIRouter()

MAX_INPUT_LENGTH = 5_000

# Singleton detectors — stateless, safe to reuse.
_PLAYGROUND_DETECTORS = [
    PromptInjectionDetector(),
    JailbreakDetector(),
    PrivilegeEscalationDetector(),
    DataExfiltrationDetector(),
    ToolMisuseDetector(),
]


class PlaygroundRequest(BaseModel):
    prompt: str = Field(..., max_length=MAX_INPUT_LENGTH)
    response: str | None = Field(None, max_length=MAX_INPUT_LENGTH)


class DetectionHit(BaseModel):
    detector: str
    triggered: bool
    severity: str
    confidence: float
    reason: str


class PlaygroundResponse(BaseModel):
    detections: list[DetectionHit]
    triggered_count: int
    max_severity: str | None


def _result_to_hit(r: DetectionResult) -> DetectionHit:
    return DetectionHit(
        detector=r.detector,
        triggered=r.triggered,
        severity=r.severity.value,
        confidence=r.confidence,
        reason=r.reason,
    )


_SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}


@router.post(
    "/analyze",
    response_model=PlaygroundResponse,
    status_code=status.HTTP_200_OK,
)
async def playground_analyze(body: PlaygroundRequest) -> PlaygroundResponse:
    """Run public detectors against user-supplied text."""
    event_data: dict[str, Any] = {
        "prompt": body.prompt,
        "response": body.response or "",
        "model": None,
        "tool_calls": [],
        "policy": {},
        "detector_config": {},
        "baseline": None,
    }

    results = [d.detect(event_data) for d in _PLAYGROUND_DETECTORS]
    hits = [_result_to_hit(r) for r in results]

    triggered = [h for h in hits if h.triggered]
    max_sev = (
        max(triggered, key=lambda h: _SEVERITY_ORDER.get(h.severity, 0)).severity
        if triggered
        else None
    )

    log.debug("playground.analyze", triggered_count=len(triggered))

    return PlaygroundResponse(
        detections=hits,
        triggered_count=len(triggered),
        max_severity=max_sev,
    )
