"""Tests for DetectionPipeline pure methods (should_block, max_severity)."""

from app.db.models import Severity
from app.detection.base import DetectionResult
from app.detection.pipeline import DetectionPipeline


def _result(
    triggered: bool = True,
    severity: Severity = Severity.MEDIUM,
    confidence: float = 0.9,
    detector: str = "test",
    reason: str = "test reason",
) -> DetectionResult:
    return DetectionResult(
        triggered=triggered,
        severity=severity,
        confidence=confidence,
        detector=detector,
        reason=reason,
    )


class TestShouldBlock:
    def setup_method(self) -> None:
        self.pipeline = DetectionPipeline()

    def test_blocks_on_critical(self) -> None:
        results = [_result(severity=Severity.CRITICAL)]
        assert self.pipeline.should_block(results) is True

    def test_blocks_on_high(self) -> None:
        results = [_result(severity=Severity.HIGH)]
        assert self.pipeline.should_block(results) is True

    def test_does_not_block_on_medium(self) -> None:
        results = [_result(severity=Severity.MEDIUM)]
        assert self.pipeline.should_block(results) is False

    def test_does_not_block_on_low(self) -> None:
        results = [_result(severity=Severity.LOW)]
        assert self.pipeline.should_block(results) is False

    def test_does_not_block_non_triggered(self) -> None:
        results = [_result(triggered=False, severity=Severity.CRITICAL)]
        assert self.pipeline.should_block(results) is False

    def test_empty_results(self) -> None:
        assert self.pipeline.should_block([]) is False

    def test_mixed_severities_blocks_if_any_high(self) -> None:
        results = [
            _result(severity=Severity.LOW),
            _result(severity=Severity.HIGH),
            _result(severity=Severity.MEDIUM),
        ]
        assert self.pipeline.should_block(results) is True


class TestMaxSeverity:
    def setup_method(self) -> None:
        self.pipeline = DetectionPipeline()

    def test_returns_none_for_empty(self) -> None:
        assert self.pipeline.max_severity([]) is None

    def test_returns_none_when_nothing_triggered(self) -> None:
        results = [_result(triggered=False, severity=Severity.CRITICAL)]
        assert self.pipeline.max_severity(results) is None

    def test_returns_highest_severity(self) -> None:
        results = [
            _result(severity=Severity.LOW),
            _result(severity=Severity.HIGH),
            _result(severity=Severity.MEDIUM),
        ]
        assert self.pipeline.max_severity(results) == Severity.HIGH

    def test_critical_is_max(self) -> None:
        results = [
            _result(severity=Severity.HIGH),
            _result(severity=Severity.CRITICAL),
        ]
        assert self.pipeline.max_severity(results) == Severity.CRITICAL

    def test_single_result(self) -> None:
        results = [_result(severity=Severity.MEDIUM)]
        assert self.pipeline.max_severity(results) == Severity.MEDIUM

    def test_ignores_non_triggered(self) -> None:
        results = [
            _result(triggered=False, severity=Severity.CRITICAL),
            _result(triggered=True, severity=Severity.LOW),
        ]
        assert self.pipeline.max_severity(results) == Severity.LOW
