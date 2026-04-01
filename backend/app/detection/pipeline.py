import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import structlog

from app.db.models import Severity
from app.detection.base import DetectionResult
from app.detection.registry import get_all_detectors

log = structlog.get_logger()

_executor = ThreadPoolExecutor(max_workers=4)


class DetectionPipeline:
    """Orchestrates the full detection pipeline for an event.

    Pipeline stages:
    1. Run all rule-based detectors in parallel
    2. Aggregate scores — if ambiguous (0.4–0.7), flag for LLM fallback
    3. Check policy enforcement
    4. Return all results
    """

    async def run(self, event_data: dict[str, Any]) -> list[DetectionResult]:
        detectors = get_all_detectors()

        # Run all sync detectors in parallel via thread pool
        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(_executor, detector.detect, event_data)
            for detector in detectors
        ]
        results: list[DetectionResult] = await asyncio.gather(*tasks)

        triggered = [r for r in results if r.triggered]
        ambiguous = [r for r in results if not r.triggered and 0.4 <= r.confidence <= 0.7]

        if triggered:
            log.info(
                "detection.triggered",
                count=len(triggered),
                detectors=[r.detector for r in triggered],
                max_severity=max(r.severity.value for r in triggered),
            )

        if ambiguous:
            log.info(
                "detection.ambiguous",
                count=len(ambiguous),
                detectors=[r.detector for r in ambiguous],
            )
            # TODO: call LLM fallback detector for ambiguous results

        return results

    def should_block(self, results: list[DetectionResult]) -> bool:
        """Determine if the call should be blocked based on detection results."""
        for r in results:
            if r.triggered and r.severity in (Severity.CRITICAL, Severity.HIGH):
                return True
        return False

    def max_severity(self, results: list[DetectionResult]) -> Severity | None:
        triggered = [r for r in results if r.triggered]
        if not triggered:
            return None
        severity_order = {
            Severity.LOW: 0,
            Severity.MEDIUM: 1,
            Severity.HIGH: 2,
            Severity.CRITICAL: 3,
        }
        return max(triggered, key=lambda r: severity_order[r.severity]).severity
