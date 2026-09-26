"""Flags optimizer-generated jailbreak suffixes (GCG-style attacks).

Deliberately does not self-trigger on its own signal — see
``_structural_anomaly.py`` and the plan this implements
(docs/superpowers/plans/2026-09-25-jailbreak-perplexity-detector.md,
finding 4) for why a confident verdict here would false-positive on
ordinary developer bug reports. Confidence is calibrated to land in the
pipeline's ambiguous band (``pipeline.py``, 0.4-0.7) so
``evaluate_ambiguous`` — the Claude-based fallback that already exists
for exactly this "regex cannot score this honestly" situation — makes
the final call.
"""

from typing import Any

from app.db.models import Severity
from app.detection.base import DetectionResult
from app.detection.detectors._structural_anomaly import structural_anomaly_score
from app.detection.normalize import scan_text
from app.services.detector_config_service import threshold_for

# Ceiling deliberately inside the pipeline's ambiguous band (0.4-0.7),
# never at or above 0.7, so this detector cannot self-trigger under the
# default threshold — only an explicit org override can lower the
# threshold enough to let it.
#
# Only a tight local cluster produces a non-zero score (0.5-1.0, so
# confidence 0.55-0.65); signals that merely co-occur far apart score
# 0.0 and stay out of the band, so they never reach the paid fallback.
_MAX_CONFIDENCE = 0.65
_MIN_AMBIGUOUS_CONFIDENCE = 0.45


class AdversarialSuffixDetector:
    name = "adversarial_suffix"

    def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        prompt = scan_text(event_data)
        score = structural_anomaly_score(prompt)

        if score is None or score == 0.0:
            confidence = 0.0
        else:
            confidence = _MIN_AMBIGUOUS_CONFIDENCE + score * (
                _MAX_CONFIDENCE - _MIN_AMBIGUOUS_CONFIDENCE
            )

        threshold = threshold_for(event_data, self.name, default=0.7)
        triggered = confidence >= threshold

        if confidence == 0.0:
            reason = "No detokenization-artifact structure detected"
        elif triggered:
            reason = "Detokenization-artifact structure exceeds configured threshold"
        else:
            reason = "Possible detokenization-artifact structure (clustered symbol + case flip)"

        return DetectionResult(
            triggered=triggered,
            severity=Severity.HIGH if triggered else Severity.LOW,
            confidence=confidence,
            reason=reason,
            detector=self.name,
        )
