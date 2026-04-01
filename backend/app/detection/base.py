from typing import Any, Protocol, runtime_checkable

from app.db.models import Severity


class DetectionResult:
    """Result from running a detector against an event."""

    __slots__ = ("triggered", "severity", "confidence", "reason", "detector", "details")

    def __init__(
        self,
        triggered: bool,
        severity: Severity,
        confidence: float,
        reason: str,
        detector: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.triggered = triggered
        self.severity = severity
        self.confidence = confidence
        self.reason = reason
        self.detector = detector
        self.details = details


@runtime_checkable
class BaseDetector(Protocol):
    """Protocol that all detectors must implement."""

    name: str

    def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        """Run detection on an event. Must be stateless."""
        ...


@runtime_checkable
class AsyncBaseDetector(Protocol):
    """Protocol for async detectors (ML/LLM-based)."""

    name: str

    async def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        """Run async detection on an event."""
        ...
